"""Per-playthrough world state. Static world facts never become shared memory."""
import json
import uuid
import story_engine as engine


class ConflictError(engine.StoryError):
    pass


def initialize(story, session):
    if session.get('world_state'):
        return False
    definition = story['world']['definition']
    session['world_state'] = {
        'world_id':definition['world_id'], 'world_version':definition['world_version'],
        'run_id':session['id'], 'revision':0, 'world_tick':0,
        'player':{'location_id':session['scene_id']}, 'party_character_ids':[],
        'characters':{c['id']:{'location_id':None, 'home_region_id':c['region_id'],
            'availability':'working' if c['identity'].get('fixed_identity') else 'away',
            'active_allegiance':c['identity'].get('allegiance_faction_id')}
            for c in story['characters']},
        'accepted_event_ids':[], 'events':[], 'event_states':{},
        'memory_entries':{c['id']:[] for c in story['characters']}, 'pending_travel':None}
    return True


def check_event(session, event_id, base_revision):
    engine._id(event_id)
    state = session['world_state']
    if event_id in state['accepted_event_ids']:
        return False
    if type(base_revision) is not int or base_revision != state['revision']:
        raise ConflictError('這份紀錄已更新，請重新載入後操作；本次沒有覆蓋進度。')
    return True


def commit(session, event_id, kind, details):
    state = session['world_state']
    state['revision'] += 1
    state['world_tick'] += 1
    state['accepted_event_ids'].append(event_id)
    # IDs are kept for the lifetime of a run, even when dialogue is trimmed.
    state['events'].append({'event_id':event_id, 'world_tick':state['world_tick'], 'kind':kind, **details})
    state['player']['location_id'] = session['scene_id']


def eligible(story, session):
    scene = engine._scene(story, session['scene_id'])
    state = session['world_state']
    return [c for c in story['characters'] if (
        state['characters'][c['id']]['location_id'] == scene['id'] or (
            state['characters'][c['id']]['location_id'] is None and c['region_id'] == scene.get('region_id')))]


def knowledge_for(story, character):
    world = story['world']
    facts = {f['id']:f for f in world['definition']['facts']}
    allowed = set()
    for grant in world['knowledge'].get('grants', []):
        audience = grant.get('audience')
        if ((audience == 'important_characters' and character['kind'] == 'important_character')
                or audience == character['id'] or (isinstance(audience, list) and character['id'] in audience)):
            allowed.update(grant.get('fact_ids', []))
    return {'facts':[{'id':fid, 'text':facts[fid]['text'], 'certainty':facts[fid].get('evidence_status', 'unknown')}
        for fid in sorted(allowed) if fid in facts and facts[fid].get('scope') != 'author_only'],
        'your_relationships':[r for r in world['knowledge'].get('relationships', [])
            if character['id'] in r.get('holders', [])]}


def move(story, session, target):
    if target not in {s['id'] for s in story['scenes']}:
        raise engine.StoryError('找不到目的地。')
    state = session['world_state']
    session['scene_id'] = target
    session['situation'] = ''
    state['pending_travel'] = None
    for cid in state['party_character_ids']:
        state['characters'][cid]['location_id'] = target
        state['characters'][cid]['availability'] = 'following'
    session['cast'] = list(dict.fromkeys(state['party_character_ids'] + [
        cid for cid, value in state['characters'].items() if value['location_id'] == target]))
    session['messages'].append({'scene_id':target, 'speaker':'narrator',
        'text':'確認抵達：' + engine._scene(story, target)['title'], 'witness_ids':list(session['cast'])})


def action(user_dir, story_id, session_id, body):
    if not isinstance(body, dict):
        raise engine.StoryError('世界操作格式錯誤。')
    with engine._LOCK:
        story = engine.get_story(user_dir, story_id)
        if not story.get('world'):
            raise engine.StoryError('此故事不是已匯入的世界。')
        session = engine.get_session(user_dir, story_id, session_id)
        initialize(story, session)
        event_id = body.get('event_id')
        if not check_event(session, event_id, body.get('base_revision')):
            return session
        state = session['world_state']
        kind = body.get('action')
        cid = body.get('character_id')
        characters = {c['id']:c for c in story['characters']}
        if kind == 'travel':
            move(story, session, body.get('location_id'))
        elif kind in ('arrive', 'join', 'leave', 'depart'):
            if cid not in characters:
                raise engine.StoryError('找不到這名角色。')
            value = state['characters'][cid]
            if kind == 'arrive':
                # User explicitly confirms this arrival; no elapsed travel time
                # is inferred from a null duration or a mere name in dialogue.
                value['location_id'] = session['scene_id']
                value['availability'] = 'present'
                session['cast'] = list(dict.fromkeys(session['cast'] + [cid]))
            elif kind == 'join':
                if cid not in session['cast']:
                    raise engine.StoryError('請先確認角色已抵達目前場景。')
                if characters[cid]['identity'].get('follower_candidate') is False:
                    raise engine.StoryError('作者設定此角色目前不可同行。')
                state['party_character_ids'] = list(dict.fromkeys(state['party_character_ids'] + [cid]))
                value['availability'] = 'following'
            else:
                state['party_character_ids'] = [x for x in state['party_character_ids'] if x != cid]
                value['availability'] = 'working' if characters[cid]['identity'].get('fixed_identity') else 'away'
                if kind == 'depart':
                    session['cast'] = [x for x in session['cast'] if x != cid]
                    value['location_id'] = None
            session['messages'].append({'scene_id':session['scene_id'], 'speaker':'narrator',
                'text':characters[cid]['name'] + {'arrive':'已抵達。', 'join':'加入同行。', 'leave':'結束同行，留在此處。', 'depart':'離開目前場景。'}[kind],
                'witness_ids':list(session['cast'])})
        else:
            raise engine.StoryError('不支援的世界操作。')
        commit(session, event_id, kind, {key:body[key] for key in ('character_id','location_id') if key in body})
        engine._write(engine._session_path(user_dir, story_id, session_id), session)
        return session


def take_turn(user_dir, story, session, text, generate, event_id, base_revision):
    initialize(story, session)
    if not check_event(session, event_id, base_revision):
        return session
    line = engine._short(text, 1800)
    if not line:
        raise engine.StoryError('請先輸入內容。')
    chars = {c['id']:c for c in story['characters']}
    state = session['world_state']
    scene = engine._scene(story, session['scene_id'])
    available = eligible(story, session)
    named = [c for c in available if c['id'] in line or c['name'] in line or c.get('search_label', '') and c['search_label'] in line]
    candidate_ids = list(dict.fromkeys(session['cast'] + state['party_character_ids'] + [c['id'] for c in named]))
    candidates = [chars[cid] for cid in candidate_ids]
    # A small local directory supports meeting new NPCs. No full 153-person
    # world book, image URL or someone else's memory enters a model request.
    candidates += [c for c in available if c['id'] not in candidate_ids][:12]
    accessible = {c['id'] for c in candidates}
    public = [m for m in session['messages'][-40:] if m.get('scene_id') == scene['id']]
    player_message = {'scene_id':scene['id'], 'speaker':'player', 'text':line, 'witness_ids':list(session['cast'])}
    public.append(player_message)
    director_system = ('你是世界故事導演。保留穩定角色ID；只安排 available_characters 中同處此地或可合理到場的人。'
        '提到遠方人物不是到場，想去遠方不是已抵達；next_scene_id 只是旅行提案，玩家需確認抵達。'
        'present_ids 為當下完整在場者；speaker_ids 最多3人且必須在場。未設定姓名只用職位稱呼，不把素材標籤定稿。'
        '不要改寫共通設定、擅自啟動事件種子或共享私人記憶。輸出JSON：'
        '{"speaker_ids":[],"present_ids":[],"next_scene_id":null,"situation":"當下環境","character_statuses":{}}。')
    direction = generate(director_system, json.dumps({
        'scene':{'id':scene['id'], 'title':scene['title'], 'cast':session['cast']},
        'available_characters':[{'id':c['id'], 'name':c['name'], 'role':c['identity'].get('display_label'),
            'availability':state['characters'][c['id']]['availability']} for c in candidates],
        'next_scenes':[{'id':s['id'], 'title':s['title']} for s in story['scenes'] if s['id'] != scene['id']],
        'canon_rules':[r['text'] for r in story['world']['definition'].get('canon_rules', [])],
        'player_input':line, 'history':public[-20:]}, ensure_ascii=False), 'schat_director')
    if not isinstance(direction, dict):
        raise engine.StoryError('故事導演回覆格式錯誤。')
    present = direction.get('present_ids')
    if isinstance(present, list) and all(isinstance(cid,str) and cid in accessible for cid in present):
        old = set(session['cast'])
        session['cast'] = list(dict.fromkeys(present))
        for cid in old - set(session['cast']):
            # Private meeting means the others are elsewhere; they retain
            # their last known location rather than becoming different people.
            state['characters'][cid]['availability'] = 'away'
        for cid in session['cast']:
            state['characters'][cid]['location_id'] = scene['id']
            state['characters'][cid]['availability'] = 'following' if cid in state['party_character_ids'] else 'present'
    target = direction.get('next_scene_id')
    if target in {s['id'] for s in story['scenes']} and target != scene['id']:
        state['pending_travel'] = {'location_id':target, 'duration':None, 'status':'proposed'}
    if isinstance(present, list) and all(isinstance(cid,str) and cid in accessible for cid in present):
        session['situation'] = engine._short(direction.get('situation'), 600)
    for cid, value in direction.get('character_statuses', {}).items() if isinstance(direction.get('character_statuses'), dict) else []:
        if cid in session['cast']:
            engine._set_public_status(session, cid, value)
    selected = [cid for cid in engine._presence_ids(direction.get('speaker_ids'), chars) if cid in session['cast']][:3]
    if not selected:
        selected = session['cast'][:1]
    new_messages = [player_message]
    for cid in selected:
        character = chars[cid]
        history = [m for m in session['messages'][-40:] if cid in m.get('witness_ids', [])] + new_messages
        actor_system = ('你扮演自己的角色，只讀取授權的知識與自己的記憶。公開名錄不代表見過面或有私交；'
            '未授權事實不知道，傳言保持傳言。未設定姓名或個性不要自行定稿。'
            '只能描述自己的完整回覆和動作，不把不在場的人寫成在旁邊。'
            '只能從已設定圖片狀態選圖，未改變時省略。繁體中文JSON：'
            '{"text":"完整回覆","remember":["本人記住的經歷"],"public_status":"可觀察狀態","visual_state":""}。')
        answer = generate(actor_system, json.dumps({
            'character':{'id':cid, 'name':character['name'], 'personality':character['personality'],
                         'backstory':character['backstory'], 'author_identity':{k:v for k,v in character['identity'].items() if k != 'portrait_asset_key'}},
            'authorized_knowledge':knowledge_for(story, character),
            'scene':{'id':scene['id'], 'title':scene['title'], 'cast':session['cast']},
            'current_situation':session['situation'], 'your_private_memory':session['memories'][cid][-20:],
            'available_visual_states':engine._visual_options(character),
            'player_input':line, 'public_history':history[-20:]}, ensure_ascii=False), 'schat_character')
        if not isinstance(answer, dict) or not engine._short(answer.get('text'), 12000):
            raise engine.StoryError('角色回覆格式錯誤。')
        message = {'scene_id':scene['id'], 'speaker':cid, 'text':engine._short(answer['text'], 12000),
                   'witness_ids':list(session['cast'])}
        new_messages.append(message)
        engine._set_public_status(session, cid, answer.get('public_status'))
        engine._set_visual(session, character, answer.get('visual_state'))
        for fact in answer.get('remember', [])[:2] if isinstance(answer.get('remember'), list) else []:
            content = engine._short(fact, 240)
            if content and content not in session['memories'][cid]:
                session['memories'][cid].append(content)
                state['memory_entries'][cid].append({'memory_id':uuid.uuid4().hex, 'character_id':cid,
                    'event_id':event_id, 'world_tick':state['world_tick'] + 1,
                    'source_type':'witnessed', 'content':content, 'certainty':'personal_observation', 'share_scope':'character_only'})
    commit(session, event_id, 'turn', {'present_character_ids':list(session['cast'])})
    session['messages'] = (session['messages'] + new_messages)[-200:]
    engine._write(engine._session_path(user_dir, story['id'], session['id']), session)
    return session
