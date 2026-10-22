import json
from io import BytesIO

import pytest

import story_engine


def definition():
    return {
        "title": "雨夜圖書館", "premise": "兩個朋友尋找失落的書。", "opening": "窗外開始下雨。",
        "characters": [
            {"id": "alice", "name": "小艾", "personality": "謹慎", "backstory": "圖書管理員"},
            {"id": "bob", "name": "阿柏", "personality": "開朗", "backstory": "旅行者"},
        ],
        "scenes": [
            {"id": "library", "title": "圖書館", "description": "找到門", "cast": ["alice", "bob"], "next": ["garden"]},
            {"id": "garden", "title": "庭園", "description": "找到書", "cast": ["alice", "bob"], "next": []},
        ],
        "start_scene": "library",
    }


def test_story_session_scene_and_separate_memories(tmp_path):
    story = story_engine.save_story(tmp_path, definition())
    session = story_engine.start_session(tmp_path, story["id"])
    session["memories"]["alice"] = ["艾的秘密代碼"]
    session["memories"]["bob"] = ["柏的秘密地點"]
    path = story_engine._session_path(tmp_path, story["id"], session["id"])
    story_engine._write(path, session)
    seen = []

    def model(system, user, label):
        payload = json.loads(user)
        if label == "schat_director":
            return {"speaker_ids": ["alice", "bob"], "next_scene_id": "garden"}
        seen.append(payload)
        return {"text": payload["character"]["name"] + "說話了", "remember": ["新記憶"]}

    result = story_engine.take_turn(tmp_path, story["id"], session["id"], "去庭園吧", model)
    assert result["scene_id"] == "garden"
    assert [message["speaker"] for message in result["messages"]] == [
        "narrator", "player", "narrator", "alice", "bob"]
    assert {"alice", "bob"} == {payload["character"]["id"] for payload in seen}
    for payload in seen:
        own, other = ("alice", "bob") if payload["character"]["id"] == "alice" else ("bob", "alice")
        assert session["memories"][own][0] in payload["your_private_memory"]
        assert session["memories"][other][0] not in json.dumps(payload, ensure_ascii=False)
    assert result["memories"]["alice"] == ["艾的秘密代碼", "新記憶"]
    assert result["memories"]["bob"] == ["柏的秘密地點", "新記憶"]
    assert story_engine.get_session(tmp_path, story["id"], session["id"]) == result


def test_invalid_graph_or_cross_user_session_is_rejected(tmp_path):
    data = definition()
    data["scenes"][0]["next"] = ["missing"]
    with pytest.raises(story_engine.StoryError):
        story_engine.save_story(tmp_path, data)
    story = story_engine.save_story(tmp_path / "one", definition())
    session = story_engine.start_session(tmp_path / "one", story["id"])
    with pytest.raises(story_engine.StoryError):
        story_engine.advance(tmp_path / "one", story["id"], session["id"], "missing")
    with pytest.raises(story_engine.StoryError):
        story_engine.get_session(tmp_path / "two", story["id"], session["id"])


def test_editing_characters_reconciles_existing_session(tmp_path):
    story = story_engine.save_story(tmp_path, definition())
    session = story_engine.start_session(tmp_path, story["id"])
    edited = definition()
    edited["characters"].append({"id": "cat", "name": "貓", "personality": "安靜"})
    edited["scenes"][0]["cast"].append("cat")
    story_engine.save_story(tmp_path, edited, story["id"])
    resumed = story_engine.get_session(tmp_path, story["id"], session["id"])
    assert resumed["memories"]["cat"] == []


def test_user_model_config_is_private_and_keeps_key_on_edit(tmp_path):
    with pytest.raises(story_engine.StoryError):
        story_engine.save_model(tmp_path, {"host": "http://example.com/v1", "model": "m", "api_key": "key"})
    public = story_engine.save_model(tmp_path, {"host": "https://example.com/v1", "model": "m", "api_key": "key"})
    assert public == {"host": "https://example.com/v1", "model": "m", "configured": True, "source": "story"}
    edited = story_engine.save_model(tmp_path, {"host": "https://example.com/v1", "model": "m2", "api_key": ""})
    assert edited["model"] == "m2"
    assert "key" not in json.dumps(edited)
    assert story_engine._read(tmp_path / "s_chat" / "model.json")["api_key"] == "key"


def test_story_routes_media_and_turn(tmp_path, monkeypatch):
    import app
    import auth
    from flask import g
    from PIL import Image

    def signed_in(req=None):
        g.user_id = "test_author"
        g.user_data_dir = str(tmp_path)
        g.is_admin = False

    monkeypatch.setattr(auth, "check_request", signed_in)
    monkeypatch.setattr(story_engine, "_model", lambda user_dir, sys, user, label: (
        {"speaker_ids": ["alice"], "next_scene_id": None} if label == "schat_director"
        else {"text": "我記得你。", "remember": ["玩家到訪"]}))
    client = app.app.test_client()
    shell = client.get("/s-chat")
    assert shell.status_code == 200 and b"S. Chat" in shell.data
    stage_css = client.get("/assets/css/schat-stage.css")
    assert stage_css.status_code == 200 and stage_css.mimetype == "text/css"
    created = client.post("/api/schat/stories", json=definition())
    assert created.status_code == 201
    story_id = created.json["id"]
    started = client.post(f"/api/schat/stories/{story_id}/sessions")
    assert started.status_code == 201
    sid = started.json["id"]
    response = client.post(f"/api/schat/stories/{story_id}/sessions/{sid}/turn", json={"text": "你好"})
    assert response.status_code == 200
    assert response.json["memories"] == {}  # Player panels do not reveal NPC private memories.
    assert story_engine.get_session(tmp_path, story_id, sid)["memories"]["alice"] == ["玩家到訪"]
    image = Image.new("RGBA", (4, 4), (255, 0, 0, 0))
    data = BytesIO()
    image.save(data, "PNG")
    data.seek(0)
    uploaded = client.post("/api/schat/assets", data={"image": (data, "avatar.png")})
    assert uploaded.status_code == 201
    served = client.get(uploaded.json["url"])
    assert served.status_code == 200 and served.mimetype == "image/png"
    model = client.put("/api/schat/model", json={"host": "https://example.com/v1", "model": "m", "api_key": "secret"})
    assert model.status_code == 200 and "secret" not in model.get_data(as_text=True)
    assert client.get("/api/schat/model").json["configured"] is True
    assert client.post("/api/schat/model/test").json == {"ok": True}
    assert client.get("/api/schat/assets/../../auth.json").status_code in (400, 404)
    automated = client.post(f"/api/schat/stories/{story_id}/sessions", json={"test_run":True})
    assert automated.status_code == 201 and automated.json["test_run"] is True
    listed = client.get(f"/api/schat/stories/{story_id}/sessions").json["sessions"]
    assert [run["id"] for run in listed] == [sid]
    assert client.get(f"/api/schat/stories/{story_id}/sessions/{automated.json['id']}").status_code == 200
