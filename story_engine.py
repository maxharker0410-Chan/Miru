"""S. Chat story definitions, sessions, scene direction, and character memories.

Story state is private to the current authenticated user. Every character has
its own memory list; only that list and the public transcript enter its reply.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit


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
    if not isinstance(value, str) or not _IMAGE.fullmatch(value):
        raise StoryError("圖片必須由 S. Chat 上傳")
    return value


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
    if not isinstance(characters, list) or not 1 <= len(characters) <= 12:
        raise StoryError("請建立 1 至 12 名角色")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 30:
        raise StoryError("請建立 1 至 30 個場景")
    cast = []
    char_ids = set()
    for item in characters:
        if not isinstance(item, dict):
            raise StoryError("角色資料格式錯誤")
        cid = _id(item.get("id"))
        if cid in char_ids or not _short(item.get("name"), 60):
            raise StoryError("角色名稱不能空白，角色 ID 不能重複")
        char_ids.add(cid)
        cast.append({"id": cid, "name": _short(item["name"], 60),
                     "personality": _short(item.get("personality"), 3000),
                     "backstory": _short(item.get("backstory"), 3000),
                     "avatar": _asset(item.get("avatar"))})
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
        if not isinstance(members, list) or not members or any(c not in char_ids for c in members):
            raise StoryError("每個場景至少要有一名已建立的角色")
        nodes.append({"id": sid, "title": _short(item["title"], 80),
                      "description": _short(item.get("description"), 4000),
                      "background": _asset(item.get("background")),
                      "cast": list(dict.fromkeys(members)),
                      "next": item.get("next", [])})
    for scene in nodes:
        edges = scene["next"]
        if not isinstance(edges, list) or any(n not in scene_ids or n == scene["id"] for n in edges):
            raise StoryError("下一場景必須指向其他已建立的場景")
        scene["next"] = list(dict.fromkeys(edges))
    start = data.get("start_scene") or nodes[0]["id"]
    if start not in scene_ids:
        raise StoryError("開場場景不存在")
    return {"id": _id(story_id) if story_id else uuid.uuid4().hex,
            "title": _short(data.get("title"), 120) or "未命名故事",
            "premise": _short(data.get("premise"), 6000),
            "opening": _short(data.get("opening"), 3000),
            "characters": cast, "scenes": nodes, "start_scene": start}


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
            _read(path)
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


def start_session(user_dir, story_id):
    story = get_story(user_dir, story_id)
    session = {"id": uuid.uuid4().hex, "story_id": story["id"],
               "scene_id": story["start_scene"], "messages": [],
               "memories": {character["id"]: [] for character in story["characters"]}}
    if story["opening"]:
        session["messages"].append({"scene_id": session["scene_id"],
                                    "speaker": "narrator", "text": story["opening"]})
    with _LOCK:
        _write(_session_path(user_dir, story_id, session["id"]), session)
    return session


def get_session(user_dir, story_id, session_id):
    with _LOCK:
        story = get_story(user_dir, story_id)
        path = _session_path(user_dir, story_id, session_id)
        session = _read(path)
        if _reconcile(story, session):
            _write(path, session)
        return session


def _scene(story, scene_id):
    return next(item for item in story["scenes"] if item["id"] == scene_id)


def _reconcile(story, session):
    """Keep an ongoing playthrough usable after its author edits the story."""
    changed = False
    if session["scene_id"] not in {scene["id"] for scene in story["scenes"]}:
        session["scene_id"] = story["start_scene"]
        changed = True
    for character in story["characters"]:
        if character["id"] not in session["memories"]:
            session["memories"][character["id"]] = []
            changed = True
    return changed


def advance(user_dir, story_id, session_id, target):
    with _LOCK:
        story = get_story(user_dir, story_id)
        path = _session_path(user_dir, story_id, session_id)
        session = _read(path)
        _reconcile(story, session)
        scene = _scene(story, session["scene_id"])
        if target not in scene["next"]:
            raise StoryError("這個場景尚未連到指定地點")
        session["scene_id"] = target
        next_scene = _scene(story, target)
        session["messages"].append({"scene_id": target, "speaker": "narrator",
                                    "text": "場景切換：" + next_scene["title"]})
        _write(path, session)
        return session


def _model(user_dir, system, user, label):
    path = _root(user_dir) / "model.json"
    if not path.is_file():
        from prompt import _call_llm_json
        return _call_llm_json(system, user, temperature=0.8,
                              max_tokens=900, tier="chat", call_label=label)
    import ai_config
    import openai
    from prompt import _parse_llm_json
    cfg = _read(path)
    client = openai.OpenAI(api_key=cfg["api_key"],
                           base_url=ai_config._openai_base_url_from_host(cfg["host"]),
                           timeout=50)
    response = client.chat.completions.create(
        model=cfg["model"], max_tokens=900,
        messages=[{"role": "system", "content": system + "\n只輸出合法 JSON。"},
                  {"role": "user", "content": user}])
    return _parse_llm_json(response.choices[0].message.content or "", label)


def take_turn(user_dir, story_id, session_id, text, generate=None):
    """Direct a turn, then call each speaker separately with only their memory."""
    line = _short(text, 1800)
    if not line:
        raise StoryError("請先輸入內容")
    generate = generate or (lambda system, user, label: _model(user_dir, system, user, label))
    with _LOCK:
        story = get_story(user_dir, story_id)
        path = _session_path(user_dir, story_id, session_id)
        session = _read(path)
        _reconcile(story, session)
        scene = _scene(story, session["scene_id"])
        chars = {c["id"]: c for c in story["characters"]}
        new_messages = [{"scene_id": scene["id"], "speaker": "player", "text": line}]
        public = session["messages"][-20:] + new_messages
        director_system = ("你是互動故事導演。只能從目前在場角色選擇 1 至 3 名說話者。"
                           "根據對話推進故事；只有情節明確要換場時才從允許的下一場景選一個。"
                           "不要替角色說話。輸出 JSON：{\"speaker_ids\":[\"角色ID\"],\"next_scene_id\":null}。")
        direction = generate(director_system, json.dumps({
            "premise": story["premise"], "scene": scene,
            "cast": [{"id": c, "name": chars[c]["name"],
                      "personality": chars[c]["personality"]} for c in scene["cast"]],
            "history": public}, ensure_ascii=False), "schat_director")
        if not isinstance(direction, dict):
            raise StoryError("故事導演回覆格式錯誤")
        selected = direction.get("speaker_ids", [])
        if not isinstance(selected, list):
            selected = []
        selected = [cid for cid in dict.fromkeys(selected) if cid in scene["cast"]][:3]
        if not selected:
            selected = scene["cast"][:1]
        target = direction.get("next_scene_id")
        if target in scene["next"]:
            scene = _scene(story, target)
            session["scene_id"] = target
            moved = {"scene_id": target, "speaker": "narrator",
                     "text": "場景切換：" + scene["title"]}
            public.append(moved)
            new_messages.append(moved)
            selected = [cid for cid in selected if cid in scene["cast"]] or scene["cast"][:1]
        for cid in selected:
            character = chars[cid]
            character_system = ("你正在扮演這名角色。遵守其個性、背景與故事世界觀。"
                                "你只知道公開對話和『你的個人記憶』，其他角色的私有記憶不可得。"
                                "用繁體中文輸出 JSON：{\"text\":\"角色台詞與簡短動作\","
                                "\"remember\":[\"這名角色新記住的具體事實\"]}。"
                                "每次最多新增兩項事實，不要替其他角色說話。")
            answer = generate(character_system, json.dumps({
                "story": story["premise"], "scene": scene,
                "character": character, "your_private_memory": session["memories"][cid][-20:],
                "public_history": public[-20:]}, ensure_ascii=False), "schat_character")
            if not isinstance(answer, dict) or not _short(answer.get("text"), 1200):
                raise StoryError("角色回覆格式錯誤")
            spoken = {"scene_id": scene["id"], "speaker": cid,
                      "text": _short(answer["text"], 1200)}
            public.append(spoken)
            new_messages.append(spoken)
            memories = answer.get("remember", [])
            if isinstance(memories, list):
                for fact in memories[:2]:
                    value = _short(fact, 240)
                    if value and value not in session["memories"][cid]:
                        session["memories"][cid].append(value)
                session["memories"][cid] = session["memories"][cid][-40:]
        session["messages"] = (session["messages"] + new_messages)[-200:]
        _write(path, session)
        return session
