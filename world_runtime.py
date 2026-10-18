"""Per-playthrough world state. Static world facts never become shared memory."""
import json
import re
import uuid
import story_engine as engine
import world_memory

PARTY_LIMIT = 4


def check_party(state, additions=()):
    members = list(dict.fromkeys(state['party_character_ids'] + list(additions)))
    if len(members) > PARTY_LIMIT:
        raise engine.StoryError('最多同行 4 人（玩家另計）；請先安排一位同伴留守或離隊。')
    return members


class ConflictError(engine.StoryError):
    pass


def initialize(story, session):
    if session.get('world_state'):
        revision = story['world'].get('author_settings', {}).get('revision', 0)
        if session['world_state'].get('author_settings_revision', 0) != revision:
            session['world_state']['author_settings_revision'] = revision
            return True
        return False
    definition = story['world']['definition']
    session['world_state'] = {
        'world_id':definition['world_id'], 'world_version':definition['world_version'],
        'run_id':session['id'], 'revision':0, 'world_tick':0,
        'author_settings_revision':story['world'].get('author_settings', {}).get('revision', 0),
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
            state['characters'][c['id']]['location_id'] is None
            and state['characters'][c['id']]['availability'] != 'traveling'
            and c['region_id'] == scene.get('region_id')) or (
            state['characters'][c['id']].get('journey', {}).get('status') == 'departed'
            and state['characters'][c['id']]['journey']['location_id'] == scene['id']))]


def character_journeys(story, session, proposed, public, accompanying=()):
    """Record witnessed NPC travel, never invent a trip for an unseen remote NPC."""
    if not isinstance(proposed, list):
        return []
    state = session['world_state']
    locations = {s['id'] for s in story['scenes']}
    sources = [m['text'] for m in public]
    accepted = []
    for trip in proposed[:3]:
        if not isinstance(trip, dict):
            continue
        cid, target = trip.get('character_id'), trip.get('location_id')
        if isinstance(cid, str) and cid in accompanying:
            continue
        purpose, status = trip.get('purpose'), trip.get('status')
        evidence = engine._short(trip.get('evidence'), 240)
        if (not isinstance(cid, str) or cid not in state['characters']
                or not isinstance(target, str) or target not in locations
                or purpose not in ('quest', 'adventure') or status not in ('departed', 'arrived')
                or len(evidence) < 6 or not any(evidence in text for text in sources)):
            continue
        value = state['characters'][cid]
        known = value.get('journey') or {}
        if cid not in session['cast'] and not (
                known.get('status') == 'departed' and known.get('location_id') == target and status == 'arrived'):
            continue
        if target == session['scene_id'] and cid in session['cast']:
            continue
        value['journey'] = {'location_id':target, 'purpose':purpose, 'status':status, 'evidence':evidence}
        value['location_id'] = target if status == 'arrived' else None
        value['availability'] = 'present' if status == 'arrived' and target == session['scene_id'] else 'traveling' if status == 'departed' else 'away'
        state['party_character_ids'] = [x for x in state['party_character_ids'] if x != cid]
        session['cast'] = [x for x in session['cast'] if x != cid]
        if status == 'arrived' and target == session['scene_id']:
            session['cast'].append(cid)
        accepted.append({'character_id':cid, **value['journey']})
    return accepted


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
            if character['id'] in r.get('holders', [])],
        'home_region_setting':world.get('author_settings', {}).get('public_regions', {}).get(character['region_id'], '')}


def travel_companions(story, session, proposed):
    """Only people already here can join a trip; mentioning a remote ID cannot."""
    chars = {c['id']:c for c in story['characters']}
    return [cid for cid in engine._presence_ids(proposed, chars)
            if cid in session['cast'] and (cid in session['world_state']['party_character_ids']
                or chars[cid]['identity'].get('follower_candidate') is not False)]


def explicit_arrival(story, line):
    """Recognize a player's own completed action, not quotes or future plans."""
    line = re.sub(r'「[^」]*」|『[^』]*』|“[^”]*”|"[^"]*"', '', line)
    found = None
    for clause in re.split(r'[。!！;；\n]', line):
        clause = clause.strip(' *')
        if not re.match(r'^(?:(?:現在|此時|然後|於是)[，,\s]*)?我', clause):
            continue
        if re.match(r'^(?:(?:現在|此時|然後|於是)[，,\s]*)?我(?:們)?的', clause) or re.search(r'[?？]', clause):
            continue
        move = re.search(r'抵達|到達|回到|返回|走到|來到|進入', clause)
        if not move:
            continue
        prefix = clause[:move.start()]
        if re.search(r'沒有|還沒|尚未|不曾|並未|未曾|如果|假如|假設|是否|要是|想|打算|準備|明天|下次|下週|下周|昨天|之前|上次|以前|曾經|回憶|回想|聽|說|告訴|通知|轉告|轉述|看到|看見|記得|得知|知道|覺得|認為|發現', prefix):
            continue
        destination = re.split(r'[，,]', clause[move.end():], maxsplit=1)[0].strip()
        if re.search(r'途中|路上|尚未|還沒', destination):
            continue
        matches = [s for s in story['scenes'] if s['title'] in destination]
        if matches:
            # Prefer the most specific named place, never its broader image area.
            found = max(matches, key=lambda s:len(s['title']))['id']
        else:
            for label, target in (('公會','loc_03_guild'),('圖書館','loc_02_library')):
                if destination.endswith((label, label+'門口', label+'總部')) and any(s['id']==target for s in story['scenes']):
                    found = target
    return found


def move(story, session, target, companion_ids=None):
    if not isinstance(target, str) or target not in {s['id'] for s in story['scenes']}:
        raise engine.StoryError('找不到目的地。')
    # A repeated destination is not another arrival and must not rebuild the
    # current cast from a party list which may have been empty in older saves.
    if target == session['scene_id']:
        return None
    state = session['world_state']
    travelers = travel_companions(story, session, state['party_character_ids'] + (companion_ids or []))
    state['party_character_ids'] = check_party(state, travelers)
    session['scene_id'] = target
    session['situation'] = ''
    state['pending_travel'] = None
    for cid in travelers:
        state['characters'][cid]['location_id'] = target
        state['characters'][cid]['availability'] = 'following'
        state['characters'][cid].pop('journey', None)
    session['cast'] = list(dict.fromkeys(travelers + [
        cid for cid, value in state['characters'].items() if value['location_id'] == target]))
    return {'scene_id':target, 'speaker':'narrator',
        'text':'確認抵達：' + engine._scene(story, target)['title'], 'witness_ids':list(session['cast'])}


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
            pending = state.get('pending_travel') or {}
            companions = pending.get('companion_ids', []) if (
                pending.get('location_id') == body.get('location_id')
                and pending.get('source_location_id', session['scene_id']) == session['scene_id']) else []
            arrival = move(story, session, body.get('location_id'), companions)
            if arrival:
                session['messages'].append(arrival)
        elif kind in ('arrive', 'join', 'leave', 'depart'):
            if cid not in characters:
                raise engine.StoryError('找不到這名角色。')
            value = state['characters'][cid]
            if kind == 'arrive':
                # User explicitly confirms this arrival; no elapsed travel time
                # is inferred from a null duration or a mere name in dialogue.
                value['location_id'] = session['scene_id']
                value['availability'] = 'present'
                value.pop('journey', None)
                session['cast'] = list(dict.fromkeys(session['cast'] + [cid]))
            elif kind == 'join':
                if cid not in session['cast']:
                    raise engine.StoryError('請先確認角色已抵達目前場景。')
                if characters[cid]['identity'].get('follower_candidate') is False:
                    raise engine.StoryError('作者設定此角色目前不可同行。')
                state['party_character_ids'] = check_party(state, [cid])
                value['availability'] = 'following'
                value.pop('journey', None)
            else:
                state['party_character_ids'] = [x for x in state['party_character_ids'] if x != cid]
                value['last_departure'] = {'location_id':session['scene_id'],
                    'world_tick':state['world_tick'] + 1, 'reason':kind}
                value['availability'] = 'working' if characters[cid]['identity'].get('fixed_identity') else 'away'
                if kind == 'depart':
                    session['cast'] = [x for x in session['cast'] if x != cid]
                    value['location_id'] = None
                    value.pop('journey', None)
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
    local_ids = {c['id'] for c in available}
    candidate_ids = list(dict.fromkeys(session['cast'] + [cid for cid in state['party_character_ids'] if cid in local_ids]
        + [c['id'] for c in named]))
    candidates = [chars[cid] for cid in candidate_ids]
    # A small local directory supports meeting new NPCs. No full 153-person
    # world book, image URL or someone else's memory enters a model request.
    candidates += [c for c in available if c['id'] not in candidate_ids][:12]
    accessible = {c['id'] for c in candidates}
    public = [m for m in session['messages'][-40:] if m.get('scene_id') == scene['id']]
    player_message = {'scene_id':scene['id'], 'speaker':'player', 'text':line, 'witness_ids':list(session['cast'])}
    public.append(player_message)
    director_system = ('你是世界故事導演。玩家另計，同行最多4人；滿員不得自動踢人或招募第5人。'
        '目前優先採用 content_release 的規則；人物缺少完整技能數值時不得編造已解鎖技能。'
        '你只能提出情節，未執行的想像不當成交易、戰鬥勝利或物品移轉。'
        '保留穩定角色ID；只安排 available_characters 中同處此地或可合理到場的人。'
        '重要角色通常留在其 home_region_id 區域執行工作與生活；跨區出現需要已有同行或冒險、任務移動紀錄。'
        '不因提到名字或需要人說話就把遠方人物搬來，不臨時編造任務當跨區理由，也不讓整個區域的人都聚在一起。'
        'follow_conditions 是作者同行條件；候選不代表立即加入，需符合信任、職務安排或任務條件。'
        '故事已開始就不要反覆要求玩家重新選身世，不能替玩家決定行動、能力或感情。'
        '玩家明確做出前往、走到、帶某人到目的地等移動行動，或敘述已抵達時，本回合完成換場：'
        'next_scene_id 用目的地ID，travel_status 用 arrived。玩家不必再點選目的地確認。'
        '例如「我和她一起走到星輝圖書館」就是 arrived；問路、「想去」、「明天再去」或尚未行動只是 proposed。'
        '回憶、轉述角色的話、假設、否定移動與詢問都不能更改玩家位置。若作者規則明確禁止這次移動，'
        'travel_allowed 用 false 並在 situation 說明原因；合法移動用 true，不能漏填已返回的目的地。'
        '不能將不知道的交通時間發明成零秒；換場只記錄本回合完成的行動，不推算天數或離線時間。'
        'traveling_ids 列出劇情中一起移動的當下在場角色，既有同行者通常繼續同行；'
        '不可同行者、遠方人物、被提到的角色和留在原地的人不得放入 traveling_ids。'
        'leave_ids 只列出本回合明確離隊、留在原地或離開玩家的角色，不因未發言就離隊。'
        'present_ids 為本回合結束時完整在場者；換場時是目的地的名單，必須保留一起抵達的人。'
        '私人會面只保留實際同處者；speaker_ids 最多3人且必須在場。未設定姓名只用職位稱呼，不把素材標籤定稿。'
        'character_journeys 只記錄本回合有公開依據的角色自行冒險或任務移動，沒有就空陣列。'
        '與玩家一起前往的角色只列 traveling_ids，不得同時列 character_journeys；同行和獨自移動不能混用。'
        'character_id 必須是當下在場者或已有該旅程紀錄的人；location_id 是目的地，purpose 用 adventure 或 quest，'
        'status 用 departed 或 arrived；evidence 必須逐字引用 player_input 或 history 的公開片段（至少6字）。'
        '只是出發時用 departed，不能假定已到達或將作者事件種子當已發生。'
        '不要改寫共通設定、擅自啟動事件種子或共享私人記憶。輸出JSON：'
        '{"speaker_ids":[],"present_ids":[],"next_scene_id":null,"travel_status":"proposed","travel_allowed":true,'
        '"traveling_ids":[],"leave_ids":[],"character_journeys":[],"situation":"當下環境","character_statuses":{}}。')
    direction = generate(director_system, json.dumps({
        'scene':{'id':scene['id'], 'title':scene['title'], 'region_id':scene.get('region_id'), 'cast':session['cast']},
        'available_characters':[{'id':c['id'], 'name':c['name'], 'role':c['identity'].get('display_label'),
            'availability':state['characters'][c['id']]['availability'],
            'home_region_id':c['region_id'], 'known_location_id':state['characters'][c['id']]['location_id'],
            'known_journey':state['characters'][c['id']].get('journey'),
            'follow_conditions':{key:value for key,value in c['identity'].get('author_card', {}).items()
                if key in ('跟隨角色設定', '可跟隨設定', '可跟隨條件方向')},
            'can_follow':c['id'] in state['party_character_ids'] or c['identity'].get('follower_candidate') is not False} for c in candidates],
        'party_character_ids':state['party_character_ids'], 'pending_travel':state['pending_travel'],
        'current_situation':session['situation'],
        'content_release':story['world'].get('content_release', {}).get('runtime_rules', {}),
        'author_story_context':story['world'].get('content_release', {}).get('narrative_context', []),
        'journey_recap':world_memory.public_journal(session)[-3:],
        'world_rules':story['world'].get('author_settings', {}).get('public_rules', ''),
        'region_setting':story['world'].get('author_settings', {}).get('public_regions', {}).get(scene.get('region_id'), ''),
        'next_scenes':[{'id':s['id'], 'title':s['title']} for s in story['scenes'] if s['id'] != scene['id']],
        'canon_rules':[r['text'] for r in story['world']['definition'].get('canon_rules', [])],
        'player_input':line, 'history':public[-20:]}, ensure_ascii=False), 'schat_director')
    if not isinstance(direction, dict):
        raise engine.StoryError('故事導演回覆格式錯誤。')
    confirmed = explicit_arrival(story, line)
    if confirmed and direction.get('travel_allowed') is not False:
        direction['next_scene_id'] = confirmed
        direction['travel_status'] = 'arrived'
    elif direction.get('travel_allowed') is False:
        direction['next_scene_id'] = None
    target = direction.get('next_scene_id')
    arrived = (isinstance(target, str) and target in {s['id'] for s in story['scenes']}
               and target != scene['id'] and direction.get('travel_status') == 'arrived')
    # present_ids describes the destination on an arrived turn. An existing
    # on-screen character there is a companion even when traveling_ids was
    # omitted. This also tolerates directors returning both travel fields.
    explicit_travelers = engine._presence_ids(direction.get('traveling_ids'), chars)
    companions = travel_companions(story, session, explicit_travelers + (
        engine._presence_ids(direction.get('present_ids'), chars) if arrived else []))
    leaving = [cid for cid in engine._presence_ids(direction.get('leave_ids'), chars) if cid in session['cast']]
    if len(set(state['party_character_ids'] + companions)) > PARTY_LIMIT:
        # A director cannot silently free a slot by evicting a companion.
        for cid in leaving:
            labels = [chars[cid]['name'], chars[cid].get('search_label'),
                      chars[cid]['identity'].get('display_label')]
            if not (any(label and label in line for label in labels)
                    and re.search(r'留|離隊|離開|解散|回去|回家', line)):
                raise engine.StoryError('同行已滿四人，請明確安排誰留守或離隊；沒有自動移除同伴。')
    companions = [cid for cid in companions if cid not in leaving]
    accompanying = explicit_travelers + companions + (state['party_character_ids'] if arrived else [])
    accompanying = [cid for cid in accompanying if cid not in leaving]
    journeys = character_journeys(story, session, direction.get('character_journeys'), public, accompanying)
    accessible = {cid for cid in accessible if state['characters'][cid]['availability'] != 'traveling'
                  and (state['characters'][cid]['location_id'] in (None, scene['id']))}
    state['party_character_ids'] = [cid for cid in state['party_character_ids'] if cid not in leaving]
    arrival = None
    arrival_companions = []
    if isinstance(target, str) and target in {s['id'] for s in story['scenes']} and target != scene['id']:
        if direction.get('travel_status') == 'arrived':
            arrival_companions = travel_companions(story, session, state['party_character_ids'] + companions)
            arrival = move(story, session, target, companions)
            scene = engine._scene(story, target)
            # Source-local candidates cannot teleport into a different region.
            accessible = set(session['cast']) | (accessible & {c['id'] for c in eligible(story, session)})
            player_message['scene_id'] = target
        else:
            state['pending_travel'] = {'location_id':target, 'source_location_id':scene['id'],
                'companion_ids':companions, 'duration':None, 'status':'proposed'}
    present = direction.get('present_ids')
    valid_presence = isinstance(present, list) and all(isinstance(cid,str) and cid in accessible for cid in present)
    if valid_presence:
        old = set(session['cast'])
        # Explicit travelers remain present even if the director only lists the
        # speaking character. Non-travel turns still allow private meetings.
        session['cast'] = list(dict.fromkeys(present + arrival_companions))
        session['cast'] = [cid for cid in session['cast'] if cid not in leaving]
        for cid in old - set(session['cast']):
            # Private meeting means the others are elsewhere; they retain
            # their last known location rather than becoming different people.
            state['characters'][cid]['availability'] = 'away'
        for cid in session['cast']:
            state['characters'][cid]['location_id'] = scene['id']
            state['characters'][cid]['availability'] = 'following' if cid in state['party_character_ids'] else 'present'
    else:
        session['cast'] = [cid for cid in session['cast'] if cid not in leaving]
    for cid in leaving:
        state['characters'][cid]['availability'] = 'away'
        state['characters'][cid]['last_departure'] = {
            'location_id':state['characters'][cid]['location_id'],
            'world_tick':state['world_tick'] + 1, 'reason':'narrative_leave'}
    player_message['witness_ids'] = list(session['cast'])
    if valid_presence:
        session['situation'] = engine._short(direction.get('situation'), 600)
    for cid, value in direction.get('character_statuses', {}).items() if isinstance(direction.get('character_statuses'), dict) else []:
        if cid in session['cast']:
            engine._set_public_status(session, cid, value)
    selected = [cid for cid in engine._presence_ids(direction.get('speaker_ids'), chars) if cid in session['cast']][:3]
    if not selected:
        selected = session['cast'][:1]
    new_messages = [player_message]
    memory_suggestions = {}
    for journey in journeys:
        new_messages.append({'scene_id':scene['id'], 'speaker':'narrator',
            'text':chars[journey['character_id']]['name'] + '：' + journey['evidence'],
            'witness_ids':list(player_message['witness_ids'])})
    if arrival:
        arrival['witness_ids'] = list(session['cast'])
        new_messages.append(arrival)
    for cid in selected:
        character = chars[cid]
        history = [m for m in session['messages'][-40:] if cid in m.get('witness_ids', [])] + new_messages
        actor_system = ('你扮演自己的角色，只讀取授權的知識與自己的記憶。公開名錄不代表見過面或有私交；'
            '未授權事實不知道，傳言保持傳言。未設定姓名或個性不要自行定稿。'
            '只能描述自己的完整回覆和動作，不把不在場的人寫成在旁邊。'
            '作者同行條件與自己的職務仍需遵守；已開始的旅程不要要求玩家重選開局或擅自指定玩家的身世、能力、感情。'
            'scene 是本回合實際位置；已換場才描述抵達目的地，pending_travel 只是提案時不能說已抵達。'
            '只能從已設定圖片狀態選圖，未改變時省略。繁體中文JSON：'
            '{"text":"完整回覆","remember":["本人記住的經歷"],"public_status":"可觀察狀態","visual_state":""}。')
        answer = generate(actor_system, json.dumps({
            'character':{'id':cid, 'name':character['name'], 'personality':character['personality'],
                         'backstory':character['backstory'], 'author_identity':{k:v for k,v in character['identity'].items() if k not in ('portrait_asset_key','author_card')}},
            'authorized_knowledge':knowledge_for(story, character),
            'world_rules':story['world'].get('author_settings', {}).get('public_rules', ''),
            'scene':{'id':scene['id'], 'title':scene['title'], 'cast':session['cast']},
            'current_situation':session['situation'], 'your_private_memory':world_memory.select(session, cid, line),
            'your_ability_blueprint':story['world'].get('content_release', {}).get('character_directions', {}).get(cid),
            'pending_travel':state['pending_travel'],
            'available_visual_states':engine._visual_options(character),
            'player_input':line, 'public_history':history[-20:]}, ensure_ascii=False), 'schat_character')
        if not isinstance(answer, dict) or not engine._short(answer.get('text'), 12000):
            raise engine.StoryError('角色回覆格式錯誤。')
        message = {'scene_id':scene['id'], 'speaker':cid, 'text':engine._short(answer['text'], 12000),
                   'witness_ids':list(session['cast'])}
        new_messages.append(message)
        engine._set_public_status(session, cid, answer.get('public_status'))
        engine._set_visual(session, character, answer.get('visual_state'))
        memory_suggestions[cid] = [engine._short(fact, 240)
            for fact in answer.get('remember', [])[:2] if engine._short(fact, 240)] if isinstance(answer.get('remember'), list) else []
    commit(session, event_id, 'turn', {'present_character_ids':list(session['cast']),
        'location_id':session['scene_id'], 'character_journeys':journeys})
    world_memory.record(user_dir, story, session, new_messages, memory_suggestions,
                        event_id, generate, boundary=arrival is not None)
    session['messages'] = (session['messages'] + new_messages)[-200:]
    engine._write(engine._session_path(user_dir, story['id'], session['id']), session)
    return session
