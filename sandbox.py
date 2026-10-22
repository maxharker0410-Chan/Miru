"""Versioned, per-run sandbox rules. No wall clock or background model calls.

The director proposes changes; this module validates and records them. Actor
views and player panels are projections, never copies of another NPC's state.
"""
from __future__ import annotations

import copy
import json
import re
import uuid

RULES_VERSION = "1.1"
DIMENSIONS = ("trust", "affection", "respect", "fear", "interest", "alignment")
CERTAINTIES = {"known", "suspected", "rumor", "false_belief"}
DIRECTOR_RULES = """
平台沙盒規則 v1.1：玩家掌控自己的言行與秘密，NPC 可拒絕、沉默、彼此交談。
「繼續／推進故事」只演出一輪必要發言，每人最多一次；可無人發言。
需要玩家決策或重大即時反應就 await_player=true 並停下，不代替玩家答應或說話。
按背景承認能力，綜合環境、對手、裝備、傷勢、疲勞、情報合理判定；不預設升級或必勝。
世界時鐘由系統維護；本回合並行行動只計一次 elapsed_seconds，不用玩家打字或離線時間。
普通互動 0..600 秒，緊急戰鬥/追逐 0..30 秒；跳時以玩家明確要求為準，事件可中斷。
只推進相關人物和已啟動事項，未接觸居民不逐日模擬。未知地點的人不必認識玩家。
客觀事實和個別人的認知不同；rumor/suspected/false_belief 不可升格成客觀真相。
NPC 的情報要有來源、持有人和傳播時間，不能知道未授權玩家秘密或他人私密記憶。
NPC 可調查、合作、背叛、戀愛、結婚或改變陣營，但要有動機、途徑、資源、時間及結果。
長期人格改變需經歷佐證，不可重寫已發生背景。多面向關係不等於單一好感或必然服從。
玩家及重要NPC都可能死亡，需合理判定；死亡不自動轉讓權力，不讓死者繼續活人互動。
可以加入有工作/接觸機會/動機的新NPC，不用圖片也能互動，不借別人的圖。
在原 JSON 額外輸出 sandbox 物件（無變化可省略），欄位：
elapsed_seconds:整數, context:"ordinary"或"urgent", await_player:布林,
narration:本回合可見敘事（不能洩漏私人事件或替玩家行動）,
new_npcs:[{key:本回合唯一短代碼,name,role,background,motive,evidence}],
knowledge_updates:[{holder:角色ID或player,text,certainty:known/suspected/rumor/false_belief,
 source:引用本回合公開文字,evidence:同一引用,channel:witness/report/investigation}],
relationship_changes:[{holder:角色ID,target:player或角色ID,dimension:trust/affection/respect/fear/interest/alignment,delta:-10..10,evidence}],
npc_actions:[{id:穩定行動ID,actor:角色ID,targets:[目標ID],intent,method,resources,duration_seconds:正整數,
 visibility:public/private,evidence}],
action_results:[{id:已啟動行動ID,result:succeeded/partial/failed,text,evidence}],
outcomes:[{character_id:角色ID或player,result:dead,evidence,reason,action_id:相關已結算行動ID}],
inventory_changes:[{id:物品ID,name,delta:整數,evidence}]。
evidence 必須逐字引用 player_input 或 history 的文字，至少四字，無依據不要更新。
新人物用 key 暫時引用，系統會配置永久ID。調查有期限不代表一定成功；不能一宣布就完成。
若 player_profile 只是未知秘密，不可在 narration/situation/character_statuses 暴露。
"""
ACTOR_RULES = """
你只知道你的 personal_context 與親歷對話。玩家背景只包含授權給你的部分；
未知秘密不可猜成事實，傳言和懷疑維持原確定度。可以拒絕、沉默、向其他在場NPC發問。
只完成自己這一次發言，不代替玩家或其他NPC回答。重大決策後停下等玩家。
專業能力、關係與組織立場綜合判斷；感激不等於服從，服從不等於忠誠。
"""


def _engine():
    import story_engine
    return story_engine


def _text(value, limit=1000):
    return value.strip()[:limit] if isinstance(value, str) else ""


def profile(value, ids):
    if value is None:
        return {"name":"", "background":"", "abilities":"", "opening_event":"", "secrets":[]}
    if not isinstance(value, dict):
        raise _engine().StoryError("玩家開局格式錯誤。")
    result = {key:_text(value.get(key), 2400) for key in ("name", "background", "abilities", "opening_event")}
    secrets = value.get("secrets", [])
    if not isinstance(secrets, list) or len(secrets) > 30:
        raise _engine().StoryError("最多可設定 30 項背景秘密。")
    result["secrets"] = []
    for item in secrets:
        if not isinstance(item, dict) or not _text(item.get("text")):
            raise _engine().StoryError("秘密需填寫內容與知情者。")
        audience = item.get("audience", [])
        if audience != "public" and (not isinstance(audience, list) or any(cid not in ids for cid in audience)):
            raise _engine().StoryError("秘密知情者必須是這個故事的角色。")
        result["secrets"].append({"id":uuid.uuid4().hex, "text":_text(item["text"]), "audience":audience})
    return result


def initialize(story, session, player_profile=None):
    if "sandbox" in session:
        return reconcile_extensions(story, session)
    session["sandbox"] = {
        "schema_version":1, "rules_version":RULES_VERSION, "revision":0,
        "elapsed_seconds":0, "turn_index":0, "run_status":"playing", "await_player":False,
        "player_profile":profile(player_profile, {c["id"] for c in story["characters"]}),
        "accepted_event_ids":[], "events":[], "knowledge":{}, "relationships":{},
        "actions":{}, "life":{}, "inventory":{}, "dynamic_characters":[],
        "known_character_ids":list(dict.fromkeys(list(session.get("cast", [])) + [m["speaker"] for m in session.get("messages", []) if m.get("speaker") in {c["id"] for c in story["characters"]}])), "installed_events":{},
        "objective_facts":[], "journal":[]}
    reconcile_extensions(story, session)
    return True


def reconcile_extensions(story, session):
    changed = False
    state = session['sandbox']
    for event in story.get('content_extensions', {}).get('events', []):
        if event['id'] not in state['installed_events']:
            state['installed_events'][event['id']] = {'installed_at':state['elapsed_seconds'],
                'installed_turn':state['turn_index'], 'triggered':False}
            changed = True
    return changed


def effective_story(story, session):
    result = copy.deepcopy(session.get("definition_snapshot") or story)
    if session.get('definition_snapshot'):
        # A restored branch keeps its historical definitions, while genuinely
        # new DLC content can still be added without rewriting that history.
        extension = story.get('content_extensions', {})
        for field, key in (('characters','character_ids'), ('scenes','scene_ids')):
            known = {item['id'] for item in result[field]}
            allowed = set(extension.get(key, []))
            result[field].extend(copy.deepcopy(item) for item in story[field] if item['id'] in allowed - known)
        merged = result.setdefault('content_extensions', {'character_ids':[], 'scene_ids':[], 'events':[]})
        for key in ('character_ids','scene_ids'):
            merged[key] = list(dict.fromkeys(merged.get(key, []) + extension.get(key, [])))
        prior = {item['id'] for item in merged['events']}
        merged['events'].extend(copy.deepcopy(item) for item in extension.get('events', []) if item['id'] not in prior)
    existing = {c["id"] for c in result["characters"]}
    result["characters"].extend(copy.deepcopy(c) for c in session.get("sandbox", {}).get("dynamic_characters", []) if c["id"] not in existing)
    for character in result['characters']:
        art = session.get('sandbox', {}).get('character_art', {}).get(character['id'])
        if art:
            character['avatar'] = art
    return result


def alive(session, cid):
    return session.get("sandbox", {}).get("life", {}).get(cid, {}).get("state") != "dead"


def require_playing(session):
    status = session["sandbox"]["run_status"]
    if status != "playing":
        raise _engine().StoryError("故事已結束，請讀檔或重新開始。" if status == "dead" else "故事已暫停，請先繼續遊玩。")


def check_event(session, event_id, revision):
    if event_id is None:
        return True
    _engine()._id(event_id)
    state = session["sandbox"]
    if event_id in state["accepted_event_ids"]:
        return False
    if type(revision) is not int or revision != state["revision"]:
        from world_runtime import ConflictError
        raise ConflictError("紀錄已更新，請重新載入；本次未覆蓋進度。")
    return True


def finish(session, event_id=None):
    state = session["sandbox"]
    state["revision"] += 1
    state["turn_index"] += 1
    if event_id:
        state["accepted_event_ids"].append(event_id)


def command(line):
    return {"/pause":"pause", "暫停":"pause", "/resume":"resume", "繼續遊玩":"resume"}.get(line.strip())


def wait_seconds(line):
    # Only explicit system/wait input; a quoted sentence or tomorrow's plan
    # does not request a time jump. Never derive time from real typing speed.
    raw = line.strip().strip("*").strip()
    match = re.fullmatch(r"(?:/wait\s+|(?:我)?(?:等待|等候|等|休息|跳時|跳過時間)\s*)([\d零一二兩三四五六七八九十百千半]{1,5})\s*(?:個)?(秒|分鐘|分|小時|天)(?:。)?", raw)
    if not match:
        return None
    units = {"秒":1, "分鐘":60, "分":60, "小時":3600, "天":86400}
    token = match[1]
    if token.isascii() and token.isdecimal():
        amount = int(token)
    elif token == '半':
        amount = .5
    else:
        numbers = dict(zip('零一二三四五六七八九',range(10)));numbers['兩']=2
        amount, digit = 0, 0
        for char in token:
            if char in numbers:
                digit = numbers[char]
            elif char in '十百千':
                amount += (digit or 1) * {'十':10,'百':100,'千':1000}[char];digit=0
            else:
                return None
        amount += digit
    return min(int(amount * units[match[2]]), 30 * 86400)


def director_context(session):
    state = session["sandbox"]
    return {"rules_version":RULES_VERSION, "elapsed_seconds":state["elapsed_seconds"],
            "player_profile":state["player_profile"], "active_actions":list(state["actions"].values())[-40:],
            "life":state["life"], "await_player":state["await_player"],
            "established_facts":state["objective_facts"][-40:]}


def actor_context(session, cid):
    state = session["sandbox"]
    own_profile = {k:v for k,v in state["player_profile"].items() if k != "secrets"}
    own_profile["authorized_background"] = [s["text"] for s in state["player_profile"]["secrets"]
        if s["audience"] == "public" or cid in s["audience"]]
    return {"player_profile":own_profile, "elapsed_seconds":state["elapsed_seconds"],
            "your_beliefs":state["knowledge"].get(cid, [])[-40:],
            "your_relationships":state["relationships"].get(cid, {}),
            "your_actions":[a for a in state["actions"].values() if a["actor"] == cid][-10:]}


def _record(state, kind, content, *, public=True, **extra):
    event = {"id":uuid.uuid4().hex, "kind":kind, "at":state["elapsed_seconds"],
             "text":content, "public":public, **extra}
    state["events"].append(event)
    if public:
        state["journal"].append(copy.deepcopy(event))
    return event


def _sources(public, line):
    return [line] + [m.get("text", "") for m in public[-20:]]


def apply_direction(story, session, direction, line, public):
    """Validate a bounded proposal, then advance one shared timeline once."""
    state = session["sandbox"]
    value = direction.get("sandbox")
    value = value if isinstance(value, dict) else {}
    sources = _sources(public, line)
    def evidence(item):
        text = _text(item.get("evidence"), 300)
        return text if len(text) >= 4 and any(text in source for source in sources) else ""
    def entries(key, limit=12):
        values = value.get(key, [])
        return [v for v in values[:limit] if isinstance(v, dict)] if isinstance(values, list) else []
    ids = {c["id"] for c in story["characters"]}
    present = set(session["cast"])
    journal_start = len(state['journal'])
    introduced = {}
    for item in entries("new_npcs", 3):
        if (len(state["dynamic_characters"]) >= 200 or not evidence(item) or not _text(item.get("name"), 60)
                or not _text(item.get("role")) or not _text(item.get("motive"))):
            continue
        key = _text(item.get("key"), 64)
        # Reuse a named, established person rather than inventing a duplicate.
        prior = next((c for c in story["characters"] if c["name"] == item["name"].strip()), None)
        if prior:
            introduced[key] = prior["id"]
            continue
        cid = "npc_" + uuid.uuid4().hex
        character = {"id":cid, "name":_text(item["name"], 60), "kind":"dynamic_npc",
            "personality":_text(item.get("personality"), 1000),
            "backstory":_text(item.get("background"), 1600), "avatar":"", "visual_states":[], "default_visual_state":"",
            "region_id":_engine()._scene(story, session["scene_id"]).get("region_id"),
            "identity":{"display_label":_text(item["role"]), "follower_candidate":True, "fixed_identity":False}}
        state["dynamic_characters"].append(character)
        story["characters"].append(character)
        session["memories"][cid] = []
        session["visuals"][cid] = {"state_id":"", "locked":False}
        if "world_state" in session:
            session["world_state"]["characters"][cid] = {"location_id":session["scene_id"], "home_region_id":character["region_id"], "availability":"present"}
            session["world_state"]["memory_entries"][cid] = []
        ids.add(cid)
        introduced[key] = cid
        session["cast"].append(cid)
        present.add(cid)
        _record(state, "new_npc", character["name"] + "出現在現場。", character_id=cid)
    if introduced:
        for key in ("speaker_ids", "present_ids"):
            if isinstance(direction.get(key), list):
                direction[key] = [introduced.get(cid, cid) for cid in direction[key] if isinstance(cid, str)]
                if key == "present_ids":
                    direction[key] = list(dict.fromkeys(direction[key] + list(introduced.values())))

    # Bound context-sensitive AI estimates; explicit waiting uses the player's
    # requested duration and stops at the first relevant deadline.
    requested = wait_seconds(line)
    seconds = value.get("elapsed_seconds", 0)
    cap = 30 if value.get("context") == "urgent" else 600
    seconds = min(max(seconds, 0), cap) if type(seconds) is int else 0
    if requested is not None:
        seconds = requested
    now = state["elapsed_seconds"]
    # Actions are scheduled before elapsed time, so a new short deadline can
    # also interrupt a wait in this same turn.
    for item in entries("npc_actions", 6):
        aid, actor = _text(item.get("id"), 64), item.get("actor")
        duration = item.get("duration_seconds")
        if (not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", aid) or aid in state["actions"]
                or actor not in ids or actor not in present or not alive(session, actor)
                or type(duration) is not int or not 1 <= duration <= 30 * 86400
                or not all(_text(item.get(k)) for k in ("intent", "method", "resources")) or not evidence(item)):
            continue
        state["actions"][aid] = {"id":aid, "actor":actor, "intent":_text(item["intent"]),
            "method":_text(item["method"]), "resources":_text(item["resources"]), "phase":"executing",
            "started_at":now, "due_at":now + duration, "public":item.get("visibility") == "public",
            "evidence":evidence(item),
            "targets":[cid for cid in item.get('targets', []) if isinstance(cid, str) and cid in ids | {'player'}]
                if isinstance(item.get('targets', []), list) else []}
    deadlines = [a["due_at"] for a in state["actions"].values()
                 if a["phase"] == "executing" and (a['public'] or 'player' in a.get('targets', []))
                 and now < a["due_at"] <= now + seconds]
    for event in story.get('content_extensions', {}).get('events', []):
        marker = state['installed_events'][event['id']]
        if not marker['triggered'] and event['trigger'] == 'after_seconds':
            due = event['seconds'] + (0 if event['retroactive'] else marker['installed_at'])
            if now < due <= now + seconds:
                deadlines.append(due)
    if requested is not None and deadlines:
        seconds = min(deadlines) - now
    state["elapsed_seconds"] += seconds
    state["await_player"] = value.get("await_player") is True
    for event in story.get('content_extensions', {}).get('events', []):
        marker = state['installed_events'][event['id']]
        if marker['triggered']:
            continue
        if event['trigger'] == 'after_seconds':
            due = event['seconds'] + (0 if event['retroactive'] else marker['installed_at'])
            triggered = due <= state['elapsed_seconds']
        else:
            before = session.get('_turn_origin_scene', session['scene_id'])
            triggered = (event['scene_id'] == session['scene_id'] and (before != session['scene_id'] or event['retroactive']))
        if triggered:
            marker['triggered'] = True
            marker['triggered_at'] = state['elapsed_seconds']
            _record(state, 'dlc_event', event['text'], dlc_event_id=event['id'])
            if event.get('interrupt') is True:
                state['await_player'] = True
    for action in state["actions"].values():
        if action["phase"] == "executing" and action["due_at"] <= state["elapsed_seconds"]:
            action["phase"] = "awaiting_result"
            if action["public"]:
                state["await_player"] = True
                _record(state, "deadline", "一項已啟動事項到達處理時點：" + action["intent"], action_id=action["id"])
    for item in entries("action_results"):
        action = state["actions"].get(item.get("id")) if isinstance(item.get("id"), str) else None
        if (not action or action["phase"] != "awaiting_result" or not evidence(item)
                or item.get("result") not in ("succeeded", "partial", "failed") or not _text(item.get("text"))):
            continue
        action.update(phase="resolved", result=item["result"], result_text=_text(item["text"]), resolved_at=state["elapsed_seconds"])
        _record(state, "action_result", action["result_text"], public=action["public"], action_id=action["id"])
    for item in entries("knowledge_updates"):
        holder = item.get("holder")
        if (holder not in ids | {"player"} or item.get("certainty") not in CERTAINTIES
                or item.get("channel") not in ("witness", "report", "investigation")
                or not evidence(item) or not _text(item.get("text"))):
            continue
        # No invented remote information propagation: a recipient must be here
        # or have completed an established investigation of its own.
        if holder != "player" and holder not in present:
            own_results = [a for a in state["actions"].values() if a["actor"] == holder and a["phase"] == "resolved"]
            if item.get("channel") != "investigation" or not own_results:
                continue
        record = {"id":uuid.uuid4().hex, "text":_text(item["text"]), "certainty":item["certainty"],
            "source":evidence(item), "channel":item["channel"], "at":state["elapsed_seconds"]}
        state["knowledge"].setdefault(holder, []).append(record)
    for item in entries("relationship_changes"):
        holder, target, dim = item.get("holder"), item.get("target"), item.get("dimension")
        delta = item.get("delta")
        if (holder not in present or target not in ids | {"player"} or dim not in DIMENSIONS
                or type(delta) is not int or not -10 <= delta <= 10 or not evidence(item)):
            continue
        relation = state["relationships"].setdefault(holder, {}).setdefault(target, {d:0 for d in DIMENSIONS})
        relation[dim] = min(100, max(-100, relation[dim] + delta))
        relation.setdefault("history", []).append({"dimension":dim, "delta":delta, "evidence":evidence(item), "at":state["elapsed_seconds"]})
    for item in entries("outcomes", 5):
        cid = item.get("character_id")
        observed = cid == 'player' or cid in present
        if (cid not in ids | {"player"} or item.get("result") != "dead" or not evidence(item)
                or not _text(item.get("reason")) or not alive(session, cid)):
            continue
        if cid != "player" and cid not in present:
            related = state['actions'].get(item.get('action_id')) if isinstance(item.get('action_id'), str) else None
            if not related or related['phase'] != 'resolved' or related.get('result') not in ('succeeded','partial') or cid not in related['targets']:
                continue
            observed = related['public']
        state["life"][cid] = {"state":"dead", "at":state["elapsed_seconds"], "reason":_text(item["reason"])}
        _record(state, "death", ("玩家" if cid == "player" else next(c["name"] for c in story["characters"] if c["id"] == cid)) + "死亡。", public=observed, character_id=cid)
        state['objective_facts'].append({'id':uuid.uuid4().hex, 'type':'death', 'subject':cid,
            'at':state['elapsed_seconds'], 'evidence':evidence(item)})
        if cid == "player":
            state["run_status"] = "dead"
        else:
            session["cast"] = [c for c in session["cast"] if c != cid]
            if "world_state" in session:
                session["world_state"]["party_character_ids"] = [c for c in session["world_state"]["party_character_ids"] if c != cid]
    for item in entries("inventory_changes"):
        iid = _text(item.get("id"), 64)
        delta = item.get("delta")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", iid) or type(delta) is not int or not -1000 <= delta <= 1000 or not evidence(item):
            continue
        old = state["inventory"].get(iid)
        if old is None and (delta <= 0 or not _text(item.get("name"))):
            continue
        quantity = (old or {}).get("quantity", 0) + delta
        if quantity < 0:
            continue
        state["inventory"][iid] = {"id":iid, "name":(old or {}).get("name", _text(item.get("name"), 100)), "quantity":quantity}
    state["known_character_ids"] = list(dict.fromkeys(state["known_character_ids"] + session["cast"]))
    narration = _text(value.get("narration"), 1800)
    if narration:
        _record(state, "scene", narration)
    visible = [entry['text'] for entry in state['journal'][journal_start:] if entry['kind'] != 'scene']
    return '\n'.join(([narration] if narration else []) + visible)


def player_panel(story, session):
    state = session["sandbox"]
    known = set(state["known_character_ids"]) | set(session["cast"])
    known_deaths = {e.get('character_id') for e in state['journal'] if e['kind'] == 'death'}
    return {"rules_version":RULES_VERSION, "elapsed_seconds":state["elapsed_seconds"],
        "run_status":state["run_status"], "await_player":state["await_player"],
        "player_profile":state["player_profile"],
        "map":[{"id":s["id"], "title":s["title"], "current":s["id"] == session["scene_id"]} for s in story["scenes"]],
        "inventory":[v for v in state["inventory"].values() if v["quantity"] > 0],
        "events":[{k:v for k,v in a.items() if k in ("id", "actor", "intent", "phase", "due_at", "result_text")}
                  for a in state["actions"].values() if a["public"]],
        "people":[{"id":c["id"], "name":c["name"], "present":c["id"] in session["cast"],
                   "alive":c['id'] not in known_deaths} for c in story["characters"] if c["id"] in known],
        "knowledge":state["knowledge"].get("player", []), "journal":state["journal"][-100:]}


def player_view(story, session):
    result = copy.deepcopy(session)
    state = result.pop("sandbox")
    result.pop("definition_snapshot", None)
    result.pop('_turn_origin_scene', None)
    result["sandbox"] = {"schema_version":1, "rules_version":RULES_VERSION, "revision":state["revision"],
        "elapsed_seconds":state["elapsed_seconds"], "run_status":state["run_status"],
        "await_player":state["await_player"], "accepted_event_ids":state["accepted_event_ids"],
        "character_art":copy.deepcopy(state.get('character_art', {})),
        "dynamic_characters":[{k:v for k,v in c.items() if k in ("id", "name", "avatar", "visual_states", "default_visual_state", "kind")}
                              for c in state["dynamic_characters"]]}
    # The browser reads a player's journal, not every NPC's private thoughts.
    result["memories"] = {}
    if "world_state" in result:
        result["world_state"].pop("memory_entries", None)
    result["panels"] = player_panel(effective_story(story, session), session)
    if session.get('definition_snapshot'):
        effective = effective_story(story, session)
        result['render_definition'] = {
            'characters':[{k:v for k,v in c.items() if k in ('id','name','avatar','visual_states','default_visual_state','portrait_render_mode','kind')}
                          for c in effective['characters']],
            'scenes':copy.deepcopy(effective['scenes'])}
    return result


def bind_art(user_dir, story_id, session_id, character_id, image):
    engine = _engine()
    with engine._LOCK:
        session = engine.get_session(user_dir, story_id, session_id)
        story = effective_story(engine.get_story(user_dir, story_id), session)
        if character_id not in {c['id'] for c in story['characters']}:
            raise engine.StoryError('找不到此故事中的角色。')
        if not isinstance(image, str) or not engine._IMAGE.fullmatch(image) or not (engine._root(user_dir) / 'media' / image).is_file():
            raise engine.StoryError('請先上傳此角色的圖片。')
        session['sandbox'].setdefault('character_art', {})[character_id] = image
        engine._write(engine._session_path(user_dir, story_id, session_id), session)
        return session


def _slots_root(user_dir, story_id):
    return _engine()._root(user_dir) / "saves" / _engine()._id(story_id)


def list_slots(user_dir, story_id):
    _engine().get_story(user_dir, story_id)
    result = []
    for path in sorted(_slots_root(user_dir, story_id).glob("*.json")):
        item = _engine()._read(path)
        result.append({"slot":item["slot"], "label":item["label"], "scene_id":item["session"]["scene_id"],
                       "elapsed_seconds":item["session"]["sandbox"]["elapsed_seconds"]})
    return result


def save_slot(user_dir, story_id, session_id, slot, label=""):
    engine = _engine()
    with engine._LOCK:
        engine._id(slot)
        session = engine.get_session(user_dir, story_id, session_id)
        story = effective_story(engine.get_story(user_dir, story_id), session)
        item = {"schema_version":1, "slot":slot, "label":_text(label, 100) or slot,
                "story_id":story_id, "story":story, "session":copy.deepcopy(session)}
        engine._write(_slots_root(user_dir, story_id) / (slot + ".json"), item)
        return {"ok":True, "slot":slot, "label":item["label"]}


def load_slot(user_dir, story_id, slot):
    engine = _engine()
    with engine._LOCK:
        engine.get_story(user_dir, story_id)
        item = engine._read(_slots_root(user_dir, story_id) / (engine._id(slot) + ".json"))
        if item.get("schema_version") != 1 or item.get("story_id") != story_id:
            raise engine.StoryError("存檔版本或故事不相符。")
        session = copy.deepcopy(item["session"])
        session["restored_from"] = {"slot":slot, "session_id":session["id"]}
        session["id"] = uuid.uuid4().hex
        session["definition_snapshot"] = copy.deepcopy(item["story"])
        if "world_state" in session:
            session["world_state"]["run_id"] = session["id"]
        engine._write(engine._session_path(user_dir, story_id, session["id"]), session)
        return session
