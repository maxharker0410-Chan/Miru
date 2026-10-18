"""Witness-scoped, resumable summaries; raw accepted interactions are archived."""
import json
import re


def _text(value, limit=300):
    return value.strip()[:limit] if isinstance(value, str) else ''


def initialize(session):
    return session['world_state'].setdefault('memory_system', {
        'version':1, 'characters':{}, 'journal':{'pending':[], 'summaries':[]}})


def select(session, cid, query=''):
    """Only this character's legacy facts and summaries, never another ledger."""
    ledger = initialize(session)['characters'].get(cid, {})
    values = list(session.get('memories', {}).get(cid, []))
    values += [x['content'] for x in ledger.get('summaries', [])]
    terms = set(re.findall(r'[a-zA-Z]{3,}|[\u3400-\u9fff]{2,}', query))
    # CJK bigrams allow useful matching without requiring a remote embedding API.
    terms |= {term[i:i+2] for term in list(terms) for i in range(len(term)-1)}
    recent = values[-3:]
    ranked = sorted(enumerate(values[:-3]), key=lambda pair:(
        sum(term in pair[1] for term in terms), pair[0]), reverse=True)
    selected = [v for _, v in ranked[:3] if any(term in v for term in terms)] + recent
    return list(dict.fromkeys(selected))[-6:]


def _compact(ledger, generate, cid, boundary):
    pending = ledger['pending']
    if len(pending) < (5 if boundary else 8):
        return
    batch = pending[:10]
    system = ('把已接受的互動整合為一句繁體中文重點記憶，不超過300字。'
              '保留來源與不確定性，不新增事件、能力或秘密。'
              'character_id 非空時只寫此人的親見、聽聞與有依據的感受；'
              '空值時只寫玩家已知旅程，不寫幕後真相。JSON：{"summary":"一句重點"}。')
    try:
        answer = generate(system, json.dumps({'character_id':cid, 'interactions':batch},
                          ensure_ascii=False), 'schat_memory' if cid else 'schat_journal')
        content = _text(answer.get('summary')) if isinstance(answer, dict) else ''
        if not content:
            raise ValueError('empty summary')
    except Exception:
        # Dialogue and committed gameplay survive a summary-provider failure.
        ledger['summary_pending'] = True
        return
    ledger['summaries'].append({'content':content,
        'event_ids':[row['event_id'] for row in batch],
        'source_type':'witness_summary' if cid else 'player_journal',
        'certainty':'summary_interpretation'})
    del pending[:len(batch)]
    ledger.pop('summary_pending', None)


def record(user_dir, story, session, messages, suggestions, event_id, generate, boundary=False):
    import story_engine as engine
    memory = initialize(session)
    # The session remains the commit point. Orphan archive files from a failed
    # session write are ignored because their IDs are not in accepted_event_ids.
    folder = engine._root(user_dir) / 'archives' / engine._id(story['id']) / engine._id(session['id'])
    folder.mkdir(parents=True, exist_ok=True)
    engine._write(folder / (engine._id(event_id) + '.json'), {
        'event_id':event_id, 'messages':messages, 'memory_suggestions':suggestions})
    witnesses = set(cid for message in messages for cid in message.get('witness_ids', []))
    for cid in sorted(witnesses):
        if cid not in session.get('memories', {}):
            continue
        visible = [{'speaker':m['speaker'], 'text':_text(m.get('text'), 1800)}
                   for m in messages if cid in m.get('witness_ids', [])]
        ledger = memory['characters'].setdefault(cid, {'pending':[], 'summaries':[]})
        for index, content in enumerate(suggestions.get(cid, [])):
            session['world_state']['memory_entries'][cid].append({
                'memory_id':event_id + ':' + cid + ':' + str(index), 'character_id':cid,
                'event_id':event_id, 'world_tick':session['world_state']['world_tick'],
                'source_type':'witnessed', 'content':content,
                'certainty':'personal_observation', 'share_scope':'character_only'})
        ledger['pending'].append({'event_id':event_id, 'scene_id':session['scene_id'],
            'observations':visible, 'own_notes':suggestions.get(cid, [])})
        _compact(ledger, generate, cid, boundary)
    journal = memory['journal']
    journal['pending'].append({'event_id':event_id, 'scene_id':session['scene_id'],
        'observations':[{'speaker':m['speaker'], 'text':_text(m.get('text'), 1800)} for m in messages]})
    _compact(journal, generate, None, boundary)


def public_journal(session):
    return initialize(session)['journal']['summaries']
