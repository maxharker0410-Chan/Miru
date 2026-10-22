"""S. Chat story definitions, sessions, scene direction, and character memories.

Story state is private to the current authenticated user. Every character has
its own memory list; only that list and the public transcript enter its reply.
"""

from __future__ import annotations

import json
import copy
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import story_tracker
import story_memory
import story_input
import sandbox


_LOCK = threading.RLock()
_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_IMAGE = re.compile(r"^[a-f0-9]{32}\.(?:png|jpg|webp)$")


class StoryError(ValueError):
    pass


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise StoryError("無效的故事、場景或角色 ID")
    return value


def _short(value, limit=2000):
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _asset(value):
    if not value:
        return ""
    if not isinstance(value, str):
        raise StoryError("請上傳圖片或填入 HTTPS 圖片網址")
    value = value.strip()
    if _IMAGE.fullmatch(value):
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise StoryError("請填入有效的 HTTPS 圖片直連網址") from None
    if (len(value) <= 2048 and parsed.scheme == "https" and parsed.hostname
            and not parsed.username and not parsed.password and not parsed.fragment
            and not any(c in value for c in '\\<>"\r\n\t')):
        return value
    raise StoryError("請上傳圖片或填入 HTTPS 圖片直連網址")


def _visual_states(character):
    states = character.get("visual_states", [])
    if not isinstance(states, list) or len(states) > 32:
        raise StoryError("每名角色最多可設定 32 個圖片狀態")
    result, seen = [], set()
    for state in states:
        if not isinstance(state, dict):
            raise StoryError("角色圖片狀態格式錯誤")
        sid = _id(state.get("id"))
        name = _short(state.get("name"), 60)
        if sid in seen or not name:
            raise StoryError("圖片狀態名稱不能空白，ID 不能重複")
        seen.add(sid)
        result.append({"id": sid, "name": name,
                       "condition": _short(state.get("condition"), 1000),
                       "image": _asset(state.get("image"))})
    default = character.get("default_visual_state") or ""
    if default and default not in seen:
        raise StoryError("預設圖片狀態不存在")
    return result, default


def _visual_options(character):
    # Images/URLs are rendering assets, not information the model needs.
    return [{"id": "", "name": "預設立繪", "condition": "一般狀態，或特殊狀態已結束"}] + [
        {key: state[key] for key in ("id", "name", "condition")}
        for state in character.get("visual_states", [])]


def _model_scene(scene, cast=None, situation=""):
    result = {key: scene[key] for key in ("id", "title", "description", "cast", "next")}
    if cast is not None:
        result["cast"] = list(cast)
    result["current_situation"] = situation
    return result


def _presence_ids(value, characters):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(cid for cid in value
                             if isinstance(cid, str) and cid in characters))


def _change_presence(session, characters, direction, scene_id):
    """Apply public arrivals/departures before choosing speakers in this turn."""
    before = session["cast"]
    present = direction.get("present_ids")
    full_presence = (isinstance(present, list)
                     and all(isinstance(cid, str) and cid in characters for cid in present))
    if full_presence:
        # A full current-location roster also handles moving away from a group
        # for a private meeting, without requiring everyone else to "leave".
        session["cast"] = list(dict.fromkeys(present))
    else:
        leaving = _presence_ids(direction.get("leave_ids"), characters)
        entering = [cid for cid in _presence_ids(direction.get("enter_ids"), characters)
                    if cid not in leaving]
        session["cast"] = [cid for cid in before if cid not in leaving]
        session["cast"].extend(cid for cid in entering if cid not in session["cast"])
    departed = [characters[cid]["name"] for cid in before if cid not in session["cast"]]
    arrived = [characters[cid]["name"] for cid in session["cast"] if cid not in before]
    events = []
    if departed:
        events.append({"scene_id": scene_id, "speaker": "narrator",
                       "text": ("不在此處：" if full_presence else "離場：") + "、".join(departed)})
    if arrived:
        events.append({"scene_id": scene_id, "speaker": "narrator",
                       "text": "登場：" + "、".join(arrived)})
    return events


def _set_visual(session, character, state_id):
    current = session["visuals"][character["id"]]
    allowed = {state["id"] for state in character.get("visual_states", [])} | {""}
    if not current["locked"] and isinstance(state_id, str) and state_id in allowed:
        current["state_id"] = state_id


def _set_public_status(session, character_id, value):
    status = _short(value, 240)
    if status:
        session["statuses"][character_id] = status


def _root(user_dir):
    if not user_dir:
        raise StoryError("請先登入")
    root = Path(user_dir) / "s_chat"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".story-", delete=False) as tmp:
        json.dump(value, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        name = tmp.name
    os.replace(name, path)


def _read(path):
    if not path.is_file():
        raise StoryError("找不到這個故事或遊玩紀錄")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _story_path(user_dir, story_id):
    return _root(user_dir) / "stories" / (_id(story_id) + ".json")


def _session_path(user_dir, story_id, session_id):
    return _root(user_dir) / "sessions" / _id(story_id) / (_id(session_id) + ".json")


def validate_story(data, story_id=None):
    if not isinstance(data, dict):
        raise StoryError("故事資料格式錯誤")
    characters = data.get("characters")
    scenes = data.get("scenes")
    world = data.get("world")
    character_limit, scene_limit = (500, 150)
    if not isinstance(characters, list) or not 1 <= len(characters) <= character_limit:
        raise StoryError(f"請建立 1 至 {character_limit} 名角色")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= scene_limit:
        raise StoryError(f"請建立 1 至 {scene_limit} 個場景")
    cast = []
    char_ids = set()
    for item in characters:
        if not isinstance(item, dict):
            raise StoryError("角色資料格式錯誤")
        cid = _id(item.get("id"))
        if cid in char_ids or not _short(item.get("name"), 60):
            raise StoryError("角色名稱不能空白，角色 ID 不能重複")
        char_ids.add(cid)
        visual_states, default_visual_state = _visual_states(item)
        cast.append({"id": cid, "name": _short(item["name"], 60),
                     "personality": _short(item.get("personality"), 3000),
                     "backstory": _short(item.get("backstory"), 3000),
                     "avatar": _asset(item.get("avatar")),
                     "visual_states": visual_states,
                     "default_visual_state": default_visual_state})
        if world:
            for key in ("identity", "kind", "region_id", "search_label", "portrait_render_mode"):
                cast[-1][key] = copy.deepcopy(item.get(key))
    nodes = []
    scene_ids = set()
    for item in scenes:
        if not isinstance(item, dict):
            raise StoryError("場景資料格式錯誤")
        sid = _id(item.get("id"))
        if sid in scene_ids or not _short(item.get("title"), 80):
            raise StoryError("場景名稱不能空白，場景 ID 不能重複")
        scene_ids.add(sid)
        members = item.get("cast", [])
        if not isinstance(members, list) or (not members and not world) or any(c not in char_ids for c in members):
            raise StoryError("每個場景至少要有一名已建立的角色")
        nodes.append({"id": sid, "title": _short(item["title"], 80),
                      "description": _short(item.get("description"), 4000),
                      "background": _asset(item.get("background")),
                      "cast": list(dict.fromkeys(members)),
                      "next": item.get("next", [])})
        if world:
            nodes[-1]["region_id"] = item.get("region_id", "")
    for scene in nodes:
        edges = scene["next"]
        if not isinstance(edges, list) or any(n not in scene_ids or n == scene["id"] for n in edges):
            raise StoryError("下一場景必須指向其他已建立的場景")
        scene["next"] = list(dict.fromkeys(edges))
    start = data.get("start_scene") or nodes[0]["id"]
    if start not in scene_ids:
        raise StoryError("開場場景不存在")
    result = {"id": _id(story_id) if story_id else uuid.uuid4().hex,
            "title": _short(data.get("title"), 120) or "未命名故事",
            "premise": _short(data.get("premise"), 6000),
            "opening": _short(data.get("opening"), 3000),
            "characters": cast, "scenes": nodes, "start_scene": start}
    if "state_tracker" in data:
        try:
            result["state_tracker"] = story_tracker.validate(data["state_tracker"], cast)
        except ValueError as exc:
            raise StoryError(str(exc)) from None
    if world:
        from world_import import validate_world
        validate_world(world.get("definition"), world.get("knowledge"))
        extension_ids = set(data.get('content_extensions', {}).get('character_ids', []))
        original_cast = [c for c in cast if c['id'] not in extension_ids]
        if len(original_cast) != 153 or len({c["id"] for c in original_cast if c.get("kind") == "important_character"}) != 54:
            raise StoryError("匯入世界的角色名冊不可刪除或新增 ID，請使用版本遷移。")
        result["world"] = copy.deepcopy(world)
        result["import_info"] = copy.deepcopy(data.get("import_info", {}))
    for key in ('content_extensions', 'packages'):
        if key in data:
            result[key] = copy.deepcopy(data[key])
    return result


def list_stories(user_dir):
    folder = _root(user_dir) / "stories"
    if not folder.exists():
        return []
    with _LOCK:
        return [{"id": item["id"], "title": item["title"],
                 "premise": item.get("premise", ""), "scene_count": len(item["scenes"])}
                for path in sorted(folder.glob("*.json"))
                for item in [_read(path)]]


def save_story(user_dir, data, story_id=None):
    story = validate_story(data, story_id)
    path = _story_path(user_dir, story["id"])
    with _LOCK:
        if story_id:
            existing = _read(path)
            if existing.get("world"):
                if (story.get("world") != existing["world"] or
                        {c["id"] for c in story["characters"]} != {c["id"] for c in existing["characters"]} or
                        {s["id"] for s in story["scenes"]} != {s["id"] for s in existing["scenes"]}):
                    raise StoryError("世界原始資料與穩定 ID 不可直接覆寫，請使用版本遷移。")
        _write(path, story)
    return story


def get_story(user_dir, story_id):
    with _LOCK:
        return _read(_story_path(user_dir, story_id))


def delete_story(user_dir, story_id):
    with _LOCK:
        path = _story_path(user_dir, story_id)
        _read(path)
        path.unlink()


def model_status(user_dir):
    path = _root(user_dir) / "model.json"
    if path.is_file():
        cfg = _read(path)
        return {"host": cfg["host"], "model": cfg["model"],
                "configured": bool(cfg.get("api_key")), "source": "story"}
    import ai_config
    cfg = ai_config.get_tier_config("chat")
    return {"host": cfg.get("host", ""), "model": cfg.get("model", ""),
            "configured": all(cfg.get(key) for key in ("host", "model", "api_key")),
            "source": "existing"}


def save_model(user_dir, data):
    if not isinstance(data, dict):
        raise StoryError("聊天模型設定格式錯誤")
    host = _short(data.get("host"), 400).rstrip("/")
    model = _short(data.get("model"), 160)
    parsed = urlsplit(host)
    if (parsed.scheme not in ("http", "https") or not parsed.netloc
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"))):
        raise StoryError("請填入 HTTPS 模型服務地址；本機服務可使用 HTTP")
    path = _root(user_dir) / "model.json"
    old = _read(path) if path.is_file() else {}
    key = _short(data.get("api_key"), 1000) or old.get("api_key", "")
    if not model or not key:
        raise StoryError("請填入模型 ID 與 API Key")
    with _LOCK:
        _write(path, {"host": host, "model": model, "api_key": key})
    return model_status(user_dir)


def start_session(user_dir, story_id, *, test_run=False, player_profile=None):
    story = get_story(user_dir, story_id)
    session = {"id": uuid.uuid4().hex, "story_id": story["id"],
               "scene_id": story["start_scene"], "messages": [],
               "situation": "",
               "statuses": {},
               "cast": list(_scene(story, story["start_scene"])["cast"]),
               "memories": {character["id"]: [] for character in story["characters"]},
               "visuals": {c["id"]: {"state_id": c.get("default_visual_state", ""),
                                     "locked": False} for c in story["characters"]}}
    if test_run is True:
        session["test_run"] = True
    if story["opening"]:
        session["messages"].append({"scene_id": session["scene_id"],
                                    "speaker": "narrator", "text": story["opening"],
                                    "witness_ids": list(session["cast"])})
    sandbox.initialize(story, session, player_profile)
    story_tracker.reconcile(story, session)
    if story.get("world"):
        import world_runtime
        world_runtime.initialize(story, session)
    with _LOCK:
        _write(_session_path(user_dir, story_id, session["id"]), session)
    return session


def get_session(user_dir, story_id, session_id):
    with _LOCK:
        story = get_story(user_dir, story_id)
        path = _session_path(user_dir, story_id, session_id)
        session = _read(path)
        if _reconcile(sandbox.effective_story(story, session), session):
            _write(path, session)
        return session


def list_sessions(user_dir, story_id):
    """Newest saved playthrough first, also usable from a second device."""
    with _LOCK:
        get_story(user_dir, story_id)
        folder = _root(user_dir) / "sessions" / _id(story_id)
        paths = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime_ns,
                       reverse=True)
        return [{"id": item["id"], "scene_id": item["scene_id"],
                 "message_count": len(item["messages"])}
                for path in paths for item in [_read(path)] if item.get("test_run") is not True]


def set_visual(user_dir, story_id, session_id, character_id, state_id, locked):
    if not isinstance(locked, bool):
        raise StoryError("請指定是否鎖定角色圖片")
    with _LOCK:
        story = get_story(user_dir, story_id)
        session = get_session(user_dir, story_id, session_id)
        story = sandbox.effective_story(story, session)
        character = next((c for c in story["characters"] if c["id"] == character_id), None)
        if not character or character_id not in session["cast"]:
            raise StoryError("請選擇目前在場的角色")
        if state_id != "" and state_id not in {s["id"] for s in character.get("visual_states", [])}:
            raise StoryError("找不到這個角色圖片狀態")
        session["visuals"][character_id] = {"state_id": state_id, "locked": locked}
        _write(_session_path(user_dir, story_id, session_id), session)
        return session


def _scene(story, scene_id):
    return next(item for item in story["scenes"] if item["id"] == scene_id)


def _reconcile(story, session):
    """Keep an ongoing playthrough usable after its author edits the story."""
    changed = sandbox.initialize(story, session)
    if not isinstance(session.get("situation"), str):
        session["situation"] = ""
        changed = True
    if not isinstance(session.get("visuals"), dict):
        session["visuals"] = {}
        changed = True
    if session["scene_id"] not in {scene["id"] for scene in story["scenes"]}:
        session["scene_id"] = story["start_scene"]
        session["situation"] = ""
        session["cast"] = list(_scene(story, session["scene_id"])["cast"])
        changed = True
    if not isinstance(session.get("cast"), list):
        session["cast"] = list(_scene(story, session["scene_id"])["cast"])
        session["situation"] = ""
        changed = True
    known = {c["id"] for c in story["characters"]}
    old_statuses = session.get("statuses")
    statuses = ({cid: _short(value, 240) for cid, value in old_statuses.items()
                 if cid in known and _short(value, 240)} if isinstance(old_statuses, dict) else {})
    if old_statuses != statuses:
        session["statuses"] = statuses
        changed = True
    current_cast = [cid for cid in _presence_ids(session["cast"], known) if sandbox.alive(session, cid)]
    if current_cast != session["cast"]:
        session["cast"] = current_cast
        session["situation"] = ""
        changed = True
    for character in story["characters"]:
        if character["id"] not in session["memories"]:
            session["memories"][character["id"]] = []
            changed = True
        cid = character["id"]
        current = session["visuals"].get(cid)
        allowed = {s["id"] for s in character.get("visual_states", [])} | {""}
        if (not isinstance(current, dict) or current.get("state_id") not in allowed
                or not isinstance(current.get("locked"), bool)):
            session["visuals"][cid] = {"state_id": character.get("default_visual_state", ""),
                                      "locked": False}
            changed = True
    removed = set(session["visuals"]) - {c["id"] for c in story["characters"]}
    for cid in removed:
        del session["visuals"][cid]
        changed = True
    if story.get("world"):
        import world_runtime
        changed = world_runtime.initialize(story, session) or changed
    return story_tracker.reconcile(story, session) or changed


def advance(user_dir, story_id, session_id, target, event_id=None, base_revision=None):
    with _LOCK:
        story = get_story(user_dir, story_id)
        if story.get("world"):
            import world_runtime
            return world_runtime.action(user_dir, story_id, session_id,
                {"action":"travel", "location_id":target, "event_id":event_id, "base_revision":base_revision})
        path = _session_path(user_dir, story_id, session_id)
        session = _read(path)
        story = sandbox.effective_story(story, session)
        _reconcile(story, session)
        sandbox.require_playing(session)
        if not sandbox.check_event(session, event_id, base_revision):
            return session
        scene = _scene(story, session["scene_id"])
        if target not in scene["next"]:
            raise StoryError("這個場景尚未連到指定地點")
        session["scene_id"] = target
        session["situation"] = ""
        next_scene = _scene(story, target)
        session["cast"] = [cid for cid in next_scene["cast"] if sandbox.alive(session,cid)]
        session["messages"].append({"scene_id": target, "speaker": "narrator",
                                    "text": "場景切換：" + next_scene["title"],
                                    "witness_ids": list(session["cast"])})
        sandbox.finish(session, event_id)
        _write(path, session)
        return session


def _model(user_dir, system, user, label):
    import ai_config
    from story_model import generate
    path = _root(user_dir) / "model.json"
    config = _read(path) if path.is_file() else ai_config.get_tier_config("chat")
    return generate(config, system, user, label)


def take_turn(user_dir, story_id, session_id, text, generate=None, event_id=None, base_revision=None):
    """Direct a turn, then call each speaker separately with only their memory."""
    line = _short(text, 1800)
    if not line:
        raise StoryError("請先輸入內容")
    generate = generate or (lambda system, user, label: _model(user_dir, system, user, label))
    with _LOCK:
        story = get_story(user_dir, story_id)
        path = _session_path(user_dir, story_id, session_id)
        session = _read(path)
        sandbox.initialize(story, session)
        story = sandbox.effective_story(story, session)
        _reconcile(story, session)
        if not story.get("world") and not sandbox.check_event(session, event_id, base_revision):
            return session
        if story.get('world'):
            import world_runtime
            if not world_runtime.check_event(session, event_id, base_revision):
                return session
        control = sandbox.command(line)
        if control:
            if story.get('world'):
                import world_runtime
                if not world_runtime.check_event(session, event_id, base_revision):
                    return session
            if session["sandbox"]["run_status"] == "dead":
                sandbox.require_playing(session)
            session["sandbox"]["run_status"] = "paused" if control == "pause" else "playing"
            sandbox.finish(session, event_id)
            if story.get('world'):
                world_runtime.commit(session, event_id, 'control', {'command':control})
            _write(path, session)
            return session
        if line.startswith(("/load", "/save", "/settings")):
            raise StoryError("請用故事工具內的存讀檔或編輯功能；此指令不作劇中發言。")
        sandbox.require_playing(session)
        session['_turn_origin_scene'] = session['scene_id']
        if story.get("world"):
            import world_runtime
            return world_runtime.take_turn(user_dir, story, session, text, generate, event_id, base_revision)
        scene = _scene(story, session["scene_id"])
        chars = {c["id"]: c for c in story["characters"]}
        parts = story_input.input_parts(line)
        new_messages = [{"scene_id": scene["id"], "speaker": "player", "text": line, "input_parts": parts}]
        public = session["messages"][-20:] + new_messages
        director_system = ("你是互動故事導演。根據公開劇情安排角色登場或離場。"
                           "state_tracker 是持續保存的數值追蹤；僅在本回合公開劇情有具體依據時更新。"
                           "tracker_updates 格式為 {欄位key:{value:新值,reason:本回合劇情依據}}；沒有變化就省略。"
                           "只能用已定義的 key，數值需在 min/max 內；缺乏依據時保留原值，勿每回合自動增加好感。"
                           "每日消耗僅在故事明確跨日且指定消耗量時發生；不要自行發明消耗量或未設定的健康值。"
                           "心理數值只更新當下在場、確實參與情節的角色；不在場者保留數值。"
                           "enter_ids 與 leave_ids 只能選 available_characters 的 ID，沒有變化時省略。"
                           "每回合都依玩家當下的位置、互動對象與最新情節，輸出目前同一現場的完整 present_ids。"
                           "初始場景 cast 不是永久在場名單；history 也可能包含先前不在此處的人。"
                           "玩家單獨去找某人、私下談話、獨處或走離群體時，應重算目前現場，只留下當下同處的角色。"
                           "例如原先四人同場，玩家說『我單獨去找葳葳安』，present_ids 應只含葳葳安的 ID，"
                           "其他人仍可在別處，不必逐一寫出他們離開。若情節說其他人也跟來，才保留跟來的人。"
                           "玩家明確提出的單獨會面意圖優先，先前角色自行把旁人寫進回覆不代表旁人已跟來。"
                           "present_ids 可以空陣列表示玩家獨處；不能因只選了一名說話者就判定其餘人不在場。"
                           "situation 用簡短繁體中文描述目前位置與互動情況，只描述當下在場的人，不寫台詞。"
                           "situation 與 character_statuses 只含當下公開可觀察資訊，不得轉述離場期間的私下對話或私人記憶。"
                           "character_statuses 只摘要目前在場角色可觀察的身體、情緒與行動狀態，"
                           "例如受傷、疲倦、安心、正在休息；不要寫台詞、私密記憶或不在場者的新狀態。"
                           "不要因角色未發言就讓其離場，也不要為了湊說話人數讓遠處角色突然登場。"
                           "只能從進出場完成後的在場角色選擇 1 至 3 名說話者；無人在場時 speaker_ids 用空陣列。"
                           "根據對話推進故事；只有情節明確要換場時才從允許的下一場景選一個。"
                           "換場後先以目的場景的 cast 為在場角色，再套用該場景的進出安排。"
                           "只根據公開情節更新在場角色的圖片狀態，包含未發言角色的反應。"
                           "只能選 available_visual_states 中的 ID；沒有變化時省略。"
                           "受傷、服裝等持續狀態應保留，直到情節明確結束；不要改動鎖定圖片。"
                           "不要替角色說話。輸出 JSON：{\"speaker_ids\":[\"角色ID\"],"
                           "\"next_scene_id\":null,\"present_ids\":[\"目前在場角色ID\"],"
                           "\"situation\":\"目前位置與互動情況\",\"enter_ids\":[],\"leave_ids\":[],"
                           "\"character_statuses\":{\"角色ID\":\"目前可觀察的狀態\"},"
                           "\"visual_states\":{\"角色ID\":\"狀態ID\"},\"tracker_updates\":{}}。")
        direction = generate(director_system + story_input.PLAYER_INPUT_RULES + sandbox.DIRECTOR_RULES, json.dumps({
            "sandbox_context": sandbox.director_context(session),
            "premise": story["premise"], "scene": _model_scene(scene, session["cast"], session["situation"]),
            "available_characters": [{**{key: c[key] for key in ("id", "name", "personality", "backstory")},
                                      "current_visual": session["visuals"][c["id"]],
                                      "current_public_status": session["statuses"].get(c["id"], ""),
                                      "available_visual_states": _visual_options(c)}
                                     for c in story["characters"]],
            "next_scenes": [_model_scene(_scene(story, sid)) for sid in scene["next"]],
            "cast": [{"id": c, "name": chars[c]["name"],
                      "personality": chars[c]["personality"],
                      "current_visual": session["visuals"][c],
                      "available_visual_states": _visual_options(chars[c])} for c in session["cast"]],
            "state_tracker": story_tracker.model_values(story, session),
            "player_input": line, "player_input_parts": parts, "history": public}, ensure_ascii=False), "schat_director")
        if not isinstance(direction, dict):
            raise StoryError("故事導演回覆格式錯誤")
        selected = direction.get("speaker_ids", [])
        if not isinstance(selected, list):
            selected = []
        target = direction.get("next_scene_id")
        if target in scene["next"]:
            scene = _scene(story, target)
            session["scene_id"] = target
            session["situation"] = ""
            session["cast"] = list(scene["cast"])
            moved = {"scene_id": target, "speaker": "narrator",
                     "text": "場景切換：" + scene["title"]}
            public.append(moved)
            new_messages.append(moved)
        events = _change_presence(session, chars, direction, scene["id"])
        narration = sandbox.apply_direction(story, session, direction, line, public)
        chars = {c["id"]:c for c in story["characters"]}
        if narration:
            events.append({"scene_id":scene["id"], "speaker":"narrator", "text":narration})
        session["cast"] = [cid for cid in session["cast"] if sandbox.alive(session, cid)]
        public.extend(events)
        new_messages.extend(events)
        for message in new_messages:
            message["witness_ids"] = list(session["cast"])
        story_tracker.apply_updates(story, session, direction.get("tracker_updates"))
        situation = _short(direction.get("situation"), 600)
        proposed_cast = direction.get("present_ids")
        valid_presence = ("present_ids" not in direction or (
            isinstance(proposed_cast, list) and all(isinstance(cid, str) and cid in chars for cid in proposed_cast)))
        if situation and valid_presence:
            session["situation"] = situation
        elif events:
            session["situation"] = ""
        status_updates = direction.get("character_statuses", {})
        if isinstance(status_updates, dict):
            for cid, value in status_updates.items():
                if cid in session["cast"]:
                    _set_public_status(session, cid, value)
        selected = [cid for cid in _presence_ids(direction.get('speaker_ids', selected), chars) if cid in session["cast"]][:3]
        if not selected and direction.get('speaker_ids') != []:
            selected = session["cast"][:1]
        if session["sandbox"]["run_status"] == "dead":
            selected = []
        visual_updates = direction.get("visual_states", {})
        if isinstance(visual_updates, dict):
            for cid, state_id in visual_updates.items():
                if cid in session["cast"]:
                    _set_visual(session, chars[cid], state_id)
        for cid in selected:
            character = chars[cid]
            character_system = ("你正在扮演這名角色。遵守其個性、背景與故事世界觀。"
                                "player_input 是玩家說的話或做的事，絕不是你的台詞；你需要用自己的身分回應玩家。"
                                "text 必須包含你的完整回覆與自己的動作，不能把玩家的原話冒充自己的回答。"
                                "speaker_names 對應歷史說話者；player 表示玩家，character.id 才是你。"
                                "state_tracker 只包含公開資源與你自己的心理数值；回應需符合當下值。"
                                "你只知道親自在場聽到的對話和『你的個人記憶』，離場期間的談話與其他角色私有記憶不可得。"
                                "個人記憶按經歷順序排列，舊經歷供回憶；目前位置、在場者和最新狀態以 scene 為準。"
                                "scene.cast 是當下同一現場的完整角色名單，current_situation 是最新情況。"
                                "scene.description 是初始背景，public_history 可包含先前群體互動；兩者不能把不在場的人帶回現場。"
                                "只能描述你自己的台詞與動作，不要描寫不在 scene.cast 的角色正在旁邊活動，"
                                "也不要替其他角色安排登場。私下獨處情節須尊重目前在場名單。"
                                "text 同時包含你的完整台詞、動作與敘述。另可輸出 dialogue，"
                                "作為 text 內你實際說出台詞的摘要；不可填入玩家說的話，也不可把台詞從 text 刪除。"
                                "public_status 用一句短句摘要你回覆之後可觀察的身體、情緒與行動狀態，"
                                "不要含台詞、私密記憶或其他角色的狀態。"
                                "用繁體中文輸出 JSON：{\"text\":\"角色台詞與簡短動作\","
                                "\"dialogue\":\"只有說出口的台詞\",\"public_status\":\"當下可觀察的狀態\","
                                "\"remember\":[\"這名角色新記住的具體事實\"]}。"
                                "另可輸出 visual_state，從 available_visual_states 選擇符合當下狀況的 ID。"
                                "沒有變化就省略；受傷或換裝等持續狀態保留到劇情明確結束。"
                                "鎖定圖片時不要改動狀態。每次最多新增兩項事實，不要替其他角色說話。")
            answer = generate(character_system + story_input.PLAYER_INPUT_RULES + sandbox.ACTOR_RULES, json.dumps({
                "personal_context": sandbox.actor_context(session, cid),
                "story": story["premise"], "scene": _model_scene(scene, session["cast"], session["situation"]),
                "character": {key: character[key] for key in ("id", "name", "personality", "backstory")},
                "current_visual": session["visuals"][cid],
                "current_public_status": session["statuses"].get(cid, ""),
                "available_visual_states": _visual_options(character),
                "player_input": line, "player_input_parts": parts,
                "speaker_names": {"player": "玩家", "narrator": "旁白", **{key: c["name"] for key, c in chars.items()}},
                "state_tracker": story_tracker.model_values(story, session, cid),
                "your_private_memory": story_memory.recall(session, cid, line),
                "public_history": story_memory.witnessed_history(session["messages"] + new_messages, cid)}, ensure_ascii=False), "schat_character")
            if not isinstance(answer, dict) or not _short(answer.get("text"), 1200):
                raise StoryError("角色回覆格式錯誤")
            _set_visual(session, character, answer.get("visual_state"))
            _set_public_status(session, cid, answer.get("public_status"))
            spoken = {"scene_id": scene["id"], "speaker": cid,
                      "text": _short(answer["text"], 1200),
                      "witness_ids": list(session["cast"])}
            dialogue = _short(answer.get("dialogue"), 1000)
            if dialogue:
                spoken["dialogue"] = dialogue
            public.append(spoken)
            new_messages.append(spoken)
            story_memory.remember(session, cid, answer.get("remember", []))
        session["messages"] = (session["messages"] + new_messages)[-200:]
        sandbox.finish(session, event_id)
        session.pop('_turn_origin_scene', None)
        _write(path, session)
        return session
