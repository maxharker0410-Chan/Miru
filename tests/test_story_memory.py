"""Recall old experiences without sharing absent characters' conversations."""
import json

import pytest

import story_engine as engine
import story_memory
from test_story_engine import definition


def test_old_personal_experience_is_recalled_with_bounded_recent_context():
    memories = ["我在星輝圖書館答應保管銀色鑰匙。"] + [f"旅行記錄第{i}天" for i in range(65)]
    session = {"memories": {"alice": memories, "bob": ["別人的銀色鑰匙秘密"]}}
    recalled = story_memory.recall(session, "alice", "你記得那把銀色鑰匙嗎？")
    assert len(recalled) == 20
    assert recalled[0] == memories[0]
    assert recalled[-12:] == memories[-12:]
    assert "別人的銀色鑰匙秘密" not in recalled
    assert session["memories"]["alice"] == memories


def test_irrelevant_query_uses_recent_memories_and_preserves_all_saved_facts():
    session = {"memories": {"alice": [f"event {i}" for i in range(60)]}}
    assert story_memory.recall(session, "alice", "天氣如何") == session["memories"]["alice"][-20:]
    story_memory.remember(session, "alice", ["new experience", "new experience"])
    assert len(session["memories"]["alice"]) == 61
    assert session["memories"]["alice"][0] == "event 0"
    story_memory.remember(session, "alice", "not a list")
    assert len(session["memories"]["alice"]) == 61


@pytest.fixture
def play(tmp_path):
    story = engine.save_story(tmp_path, definition())
    session = engine.start_session(tmp_path, story["id"])
    return tmp_path, story["id"], session["id"]


def turn(play, text, present, seen=None, *, remember=None, fail=False):
    def generate(system, user, label):
        payload = json.loads(user)
        if label == "schat_director":
            return {"present_ids": present, "speaker_ids": present}
        if seen is not None:
            seen.append(payload)
        if fail:
            raise RuntimeError("model unavailable")
        return {"text": "我在聽。", "remember": remember or []}
    return engine.take_turn(*play, text, generate)


def test_returning_character_cannot_read_private_conversation(play):
    turn(play, "阿柏離開，我單獨和小艾說話。", ["alice"])
    turn(play, "密語是紫色流星，不要告訴阿柏。", ["alice"])
    seen = []
    result = turn(play, "阿柏回來了。", ["alice", "bob"], seen)
    bob = next(p for p in seen if p["character"]["id"] == "bob")
    alice = next(p for p in seen if p["character"]["id"] == "alice")
    assert "紫色流星" not in json.dumps(bob["public_history"], ensure_ascii=False)
    assert "紫色流星" in json.dumps(alice["public_history"], ensure_ascii=False)
    assert all("witness_ids" in m for m in result["messages"])


def test_legacy_untagged_conversation_does_not_invent_witnesses(play):
    saved = engine.get_session(*play)
    saved["messages"].append({"speaker": "alice", "scene_id": "library", "text": "舊版私人對話"})
    engine._write(engine._session_path(*play), saved)
    seen = []
    turn(play, "大家好", ["alice", "bob"], seen)
    histories = {p["character"]["id"]: p["public_history"] for p in seen}
    assert "舊版私人對話" in json.dumps(histories["alice"], ensure_ascii=False)
    assert "舊版私人對話" not in json.dumps(histories["bob"], ensure_ascii=False)


def test_old_memory_survives_new_turn_and_resume(play):
    saved = engine.get_session(*play)
    saved["memories"]["alice"] = ["我答應歸還銀色鑰匙。"] + [f"日常見聞{i}" for i in range(50)]
    engine._write(engine._session_path(*play), saved)
    seen = []
    result = turn(play, "你還記得銀色鑰匙嗎？", ["alice"], seen, remember=["又見到了玩家。"])
    assert seen[0]["your_private_memory"][0] == saved["memories"]["alice"][0]
    assert len(result["memories"]["alice"]) == 52
    assert engine.get_session(*play)["memories"] == result["memories"]


def test_failure_does_not_commit_witnesses_or_memory(play):
    path = engine._session_path(*play)
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        turn(play, "這次尚未完成", ["alice"], fail=True)
    assert path.read_bytes() == before
