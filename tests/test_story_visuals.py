"""State transitions, legacy saves, privacy and the mobile/PWA API surface."""
import json
import os
from io import BytesIO

import pytest

import story_engine as engine


def definition():
    return {"title": "圖片測試", "premise": "探索圖書館", "opening": "開始探索。",
            "characters": [
                {"id": "alice", "name": "小艾", "avatar": "https://images.example/alice.webp",
                 "visual_states": [
                     {"id": "happy", "name": "開心", "condition": "收到好消息", "image": "https://images.example/happy.webp"},
                     {"id": "hurt", "name": "受傷", "condition": "受傷後保持，直到治療", "image": "https://images.example/hurt.png"}]},
                {"id": "bob", "name": "阿柏", "visual_states": [
                    {"id": "surprised", "name": "驚訝", "condition": "聽到驚人消息", "image": ""}]}],
            "scenes": [
                {"id": "one", "title": "圖書館", "cast": ["alice", "bob"], "next": ["two"], "background": "https://images.example/background.webp"},
                {"id": "two", "title": "庭園", "cast": ["alice"], "next": []}], "start_scene": "one"}


@pytest.fixture
def play(tmp_path):
    story = engine.save_story(tmp_path, definition())
    session = engine.start_session(tmp_path, story["id"])
    return tmp_path, story["id"], session["id"]


def model(direction=None, answer=None, seen=None):
    def generate(system, user, label):
        if seen is not None:
            seen.append((label, json.loads(user)))
        if label == "schat_director":
            return direction or {"speaker_ids": ["alice"]}
        return {"text": "我聽到了。", "remember": ["玩家到訪"], **(answer or {})}
    return generate


@pytest.mark.parametrize("value", ["javascript:alert(1)", "data:image/png;base64,AA", "http://example.com/a.png",
                                      "file:///C:/a.png", "../../secret", "https://u:p@example.com/a.png",
                                      "https://[broken", "https://example.com/a.png\n", 12])
def test_invalid_sources_are_rejected(value):
    # Newline-containing values are trimmed at the outer boundary; embedded
    # controls, schemes and malformed URLs must not reach rendering.
    if isinstance(value, str) and value.endswith('\n'):
        value = "https://example.com/a\nb.png"
    data = definition()
    data["characters"][0]["avatar"] = value
    with pytest.raises(engine.StoryError):
        engine.validate_story(data)


def test_url_and_uploaded_image_mapping_survives_save(play):
    folder, story_id, _ = play
    data = definition()
    data["characters"][0]["visual_states"][0]["image"] = "a" * 32 + ".png"
    data["characters"][0]["default_visual_state"] = "happy"
    saved = engine.save_story(folder, data, story_id)
    assert engine.get_story(folder, story_id) == saved
    assert engine.start_session(folder, story_id)["visuals"]["alice"] == {"state_id": "happy", "locked": False}


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(default_visual_state="missing"),
    lambda c: c["visual_states"].append(c["visual_states"][0].copy()),
    lambda c: c["visual_states"][0].update(name=""),
    lambda c: c.update(visual_states={}),
])
def test_bad_state_definitions_are_rejected(mutate):
    data = definition(); mutate(data["characters"][0])
    with pytest.raises(engine.StoryError):
        engine.validate_story(data)


def test_speaker_and_silent_character_change_without_memory_leaks(play):
    folder, story_id, sid = play
    current = engine.get_session(*play)
    current["memories"]["alice"] = ["艾的私密代碼"]
    current["memories"]["bob"] = ["柏的私密地點"]
    engine._write(engine._session_path(*play), current)
    seen = []
    updated = engine.take_turn(*play, "帶來好消息", model(
        {"speaker_ids": ["alice"], "visual_states": {"bob": "surprised"}},
        {"visual_state": "happy"}, seen))
    assert updated["visuals"]["alice"]["state_id"] == "happy"
    assert updated["visuals"]["bob"]["state_id"] == "surprised"
    director, actor = seen[0][1], seen[1][1]
    assert "私密" not in json.dumps(director, ensure_ascii=False)
    assert "柏的私密地點" not in json.dumps(actor, ensure_ascii=False)
    assert actor["your_private_memory"] == ["艾的私密代碼"]
    assert "https://images.example" not in json.dumps(seen)
    assert engine.get_session(*play) == updated


def test_persistent_state_unknown_choice_and_default_reset(play):
    engine.take_turn(*play, "受傷了", model(answer={"visual_state": "hurt"}))
    for answer in ({}, {"visual_state": "nonexistent"}, {"visual_state": []}):
        result = engine.take_turn(*play, "繼續走", model(answer=answer))
        assert result["visuals"]["alice"]["state_id"] == "hurt"
    recovered = engine.take_turn(*play, "治療完成", model(answer={"visual_state": ""}))
    assert recovered["visuals"]["alice"]["state_id"] == ""


def test_manual_lock_blocks_director_and_speaker_until_unlocked(play):
    engine.set_visual(*play, "alice", "hurt", True)
    changing = model({"speaker_ids": ["alice"], "visual_states": {"alice": "happy"}}, {"visual_state": "happy"})
    assert engine.take_turn(*play, "好消息", changing)["visuals"]["alice"] == {"state_id": "hurt", "locked": True}
    engine.set_visual(*play, "alice", "hurt", False)
    assert engine.take_turn(*play, "好消息", changing)["visuals"]["alice"]["state_id"] == "happy"


def test_failed_turn_does_not_save_visual_or_partial_memory(play):
    before = engine.get_session(*play)
    with pytest.raises(engine.StoryError):
        engine.take_turn(*play, "失敗回合", model(
            {"speaker_ids": ["alice"], "visual_states": {"alice": "hurt"}}, {"text": ""}))
    assert engine.get_session(*play) == before


def test_legacy_session_and_deleted_state_are_reconciled(play):
    folder, story_id, sid = play
    old = engine.get_session(*play); old.pop("visuals")
    engine._write(engine._session_path(*play), old)
    assert engine.get_session(*play)["visuals"]["alice"] == {"state_id": "", "locked": False}
    engine.set_visual(*play, "alice", "hurt", True)
    changed = definition(); changed["characters"][0]["visual_states"] = []
    engine.save_story(folder, changed, story_id)
    assert engine.get_session(*play)["visuals"]["alice"] == {"state_id": "", "locked": False}


def test_scene_change_ignores_absent_reactions_and_preserves_own_state(play):
    result = engine.take_turn(*play, "去庭園", model(
        {"speaker_ids": ["alice"], "next_scene_id": "two", "visual_states": {"bob": "surprised"}},
        {"visual_state": "hurt"}))
    assert result["visuals"]["bob"]["state_id"] == ""
    assert result["visuals"]["alice"]["state_id"] == "hurt"
    with pytest.raises(engine.StoryError):
        engine.set_visual(*play, "bob", "surprised", True)


def test_recent_session_can_be_found_on_another_device_and_is_user_scoped(play, tmp_path):
    folder, story_id, sid = play
    second = engine.start_session(folder, story_id)
    os.utime(engine._session_path(folder, story_id, sid), (1, 1))
    assert engine.list_sessions(folder, story_id)[0]["id"] == second["id"]
    with pytest.raises(engine.StoryError):
        engine.list_sessions(tmp_path / "other_user", story_id)
    with pytest.raises(engine.StoryError):
        engine.set_visual(tmp_path / "other_user", story_id, sid, "alice", "hurt", True)


def test_visual_routes_and_pwa_files(tmp_path, monkeypatch):
    import app
    import auth
    from flask import g
    from PIL import Image

    def signed_in(req=None):
        g.user_id = "test_author"; g.user_data_dir = str(tmp_path); g.is_admin = False
    monkeypatch.setattr(auth, "check_request", signed_in)
    monkeypatch.setattr(app, "_is_client_mode", True)
    client = app.app.test_client()
    story = client.post('/api/schat/stories', json=definition()).json
    sid = client.post(f'/api/schat/stories/{story["id"]}/sessions').json['id']
    base = f'/api/schat/stories/{story["id"]}/sessions'
    assert client.get(base).json['sessions'][0]['id'] == sid
    response = client.patch(base + '/' + sid + '/visuals', json={"character_id":"alice", "state_id":"hurt", "locked":True})
    assert response.status_code == 200
    assert response.json['visuals']['alice'] == {"state_id":"hurt", "locked":True}
    assert client.patch(base + '/' + sid + '/visuals', json={"character_id":"alice", "state_id":"bad", "locked":True}).status_code == 400
    assert client.get('/api/schat/account').json == {"user_id":"test_author"}
    assert client.get('/s-chat/manifest.json').json['start_url'] == '/s-chat'
    assert client.get('/s-chat/service-worker.js').headers['Service-Worker-Allowed'] == '/s-chat'
    assert client.get('/assets/js/schat.js').status_code == 200
    for size in (192, 512):
        icon = client.get(f'/assets/brand/schat-pwa-{size}.png')
        assert icon.status_code == 200
        assert Image.open(BytesIO(icon.data)).size == (size, size)
    raw = BytesIO(); Image.new('RGBA', (4, 4)).save(raw, 'PNG'); raw.seek(0)
    uploaded = client.post('/api/schat/assets', data={'image':(raw, 'state.png')}).json
    assert client.get(uploaded['url']).headers['Cache-Control'] == 'private, max-age=86400'
    assert 'no-store' in client.get(base).headers['Cache-Control']


def test_public_pwa_shell_does_not_bypass_story_auth(monkeypatch):
    import app
    import auth
    monkeypatch.setattr(auth, "get_user_by_token", lambda token: (None, None))
    monkeypatch.setattr(app, "_client_mode_config", None)
    client = app.app.test_client()
    assert client.get('/s-chat/manifest.json').status_code == 200
    assert client.get('/s-chat/service-worker.js').status_code == 200
    assert client.get('/api/schat/account').status_code == 401
    assert client.get('/api/schat/stories').status_code == 401
