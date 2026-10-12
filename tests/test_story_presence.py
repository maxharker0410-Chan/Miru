"""Plot-driven presence is independent of the scene's initial cast and speakers."""
import copy
import json

import pytest

import story_engine as engine


@pytest.fixture
def play(tmp_path):
    data = {"title": "進出場測試", "premise": "朋友走進圖書館", "opening": "在圖書館。",
            "characters": [{"id": cid, "name": name,
                            "visual_states": [{"id": "hurt", "name": "受傷", "condition": "受傷後保持",
                                               "image": "https://images.example/hurt.png"}]}
                           for cid, name in [("alice", "小艾"), ("bob", "阿柏"), ("cat", "小晴")]],
            "scenes": [{"id": "one", "title": "圖書館", "cast": ["alice", "bob"], "next": ["two"]},
                       {"id": "two", "title": "庭園", "cast": ["cat"], "next": []}],
            "start_scene": "one"}
    story = engine.save_story(tmp_path, data)
    session = engine.start_session(tmp_path, story["id"])
    return tmp_path, story["id"], session["id"]


def model(direction, seen=None, reply=None):
    def generate(system, user, label):
        payload = json.loads(user)
        if seen is not None:
            seen.append((label, payload))
        if label == "schat_director":
            return direction
        return {"text": "我到了。", "remember": ["加入了這段旅程"], **(reply or {})}
    return generate


def test_departed_actor_disappears_and_does_not_speak_or_update_state_memory(play):
    engine.set_visual(*play, "alice", "hurt", True)
    seen = []
    result = engine.take_turn(*play, "小艾離開圖書館。", model({
        "leave_ids": ["alice"], "speaker_ids": ["alice", "bob"],
        "visual_states": {"alice": ""}}, seen))
    assert result["cast"] == ["bob"]
    assert [p["character"]["id"] for label, p in seen if label == "schat_character"] == ["bob"]
    assert result["memories"]["alice"] == []
    assert result["visuals"]["alice"] == {"state_id": "hurt", "locked": True}
    assert any(m["text"] == "離場：小艾" for m in result["messages"])
    with pytest.raises(engine.StoryError):
        engine.set_visual(*play, "alice", "", False)
    assert engine.get_session(*play)["cast"] == ["bob"]


def test_actor_outside_initial_scene_cast_can_arrive_and_speak_now(play):
    seen = []
    result = engine.take_turn(*play, "小晴推門走進來，身上帶著傷。", model({
        "enter_ids": ["cat"], "speaker_ids": ["cat"], "visual_states": {"cat": "hurt"}}, seen))
    assert result["cast"] == ["alice", "bob", "cat"]
    assert result["visuals"]["cat"]["state_id"] == "hurt"
    assert result["messages"][-1]["speaker"] == "cat"
    assert any(m["text"] == "登場：小晴" for m in result["messages"])
    assert seen[-1][1]["scene"]["cast"] == result["cast"]
    assert engine.get_story(play[0], play[1])["scenes"][0]["cast"] == ["alice", "bob"]
    engine.set_visual(*play, "cat", "hurt", True)


def test_all_actors_can_leave_and_stay_absent_until_an_explicit_arrival(play):
    seen = []
    left = engine.take_turn(*play, "兩個人都離開了。", model({
        "leave_ids": ["alice", "bob"], "speaker_ids": ["alice"]}, seen))
    assert left["cast"] == []
    assert [label for label, _ in seen] == ["schat_director"]
    assert engine.get_session(*play)["cast"] == []
    seen.clear()
    alone = engine.take_turn(*play, "我在空房間等候。", model({"speaker_ids": ["bob"]}, seen))
    assert alone["cast"] == []
    assert seen[0][1]["scene"]["cast"] == [] and seen[0][1]["cast"] == []
    assert len(seen) == 1
    returned = engine.take_turn(*play, "阿柏回來了。", model({"enter_ids": ["bob"], "speaker_ids": ["bob"]}))
    assert returned["cast"] == ["bob"]
    assert returned["messages"][-1]["speaker"] == "bob"


def test_returning_actor_keeps_own_saved_memory_and_image(play):
    saved = engine.get_session(*play)
    saved["memories"]["alice"] = ["之前受傷的原因"]
    saved["memories"]["bob"] = ["阿柏的私人秘密"]
    saved["visuals"]["alice"]["state_id"] = "hurt"
    engine._write(engine._session_path(*play), saved)
    engine.take_turn(*play, "小艾離開。", model({"leave_ids": ["alice"], "speaker_ids": ["bob"]}))
    seen = []
    returned = engine.take_turn(*play, "小艾回來。", model({"enter_ids": ["alice"], "speaker_ids": ["alice"]}, seen))
    assert returned["visuals"]["alice"]["state_id"] == "hurt"
    assert seen[-1][1]["your_private_memory"] == ["之前受傷的原因"]
    assert "私人秘密" not in json.dumps(seen, ensure_ascii=False)
    assert "https://images.example" not in json.dumps(seen)
    assert {c["id"] for c in seen[0][1]["available_characters"]} == {"alice", "bob", "cat"}


@pytest.mark.parametrize("direction, expected", [
    ({"enter_ids": ["cat", "cat", "ghost", {}, None], "leave_ids": ["alice", "ghost", []]}, ["bob", "cat"]),
    ({"enter_ids": "cat", "leave_ids": {"alice": True}}, ["alice", "bob"]),
    ({"enter_ids": ["cat"], "leave_ids": ["cat"]}, ["alice", "bob"]),
])
def test_unknown_and_malformed_presence_choices_are_ignored(play, direction, expected):
    result = engine.take_turn(*play, "繼續。", model(direction))
    assert result["cast"] == expected


def test_scene_transition_uses_destination_cast_then_applies_arrivals_departures(play):
    seen = []
    result = engine.take_turn(*play, "到庭園，小晴離開，小艾跟過來。", model({
        "next_scene_id": "two", "leave_ids": ["cat"], "enter_ids": ["alice"],
        "speaker_ids": ["cat", "alice"]}, seen))
    assert result["scene_id"] == "two" and result["cast"] == ["alice"]
    assert seen[-1][1]["character"]["id"] == "alice"
    assert seen[-1][1]["scene"]["cast"] == ["alice"]
    assert seen[0][1]["next_scenes"][0]["cast"] == ["cat"]


def test_manual_scene_change_and_legacy_saves_start_with_configured_cast(play):
    saved = engine.get_session(*play)
    saved.pop("cast")
    engine._write(engine._session_path(*play), saved)
    assert engine.get_session(*play)["cast"] == ["alice", "bob"]
    engine.take_turn(*play, "小艾離開。", model({"leave_ids": ["alice"]}))
    assert engine.advance(*play, "two")["cast"] == ["cat"]


def test_presence_changes_rollback_if_a_character_reply_fails(play):
    before = copy.deepcopy(engine.get_session(*play))
    with pytest.raises(engine.StoryError):
        engine.take_turn(*play, "小艾離开，小晴到來。", model({
            "leave_ids": ["alice"], "enter_ids": ["cat"], "speaker_ids": ["cat"]}, reply={"text": ""}))
    assert engine.get_session(*play) == before


def test_removing_a_character_from_story_removes_them_from_saved_presence(play):
    story = engine.get_story(play[0], play[1])
    story["characters"] = [c for c in story["characters"] if c["id"] != "bob"]
    story["scenes"][0]["cast"] = ["alice"]
    engine.save_story(play[0], story, play[1])
    assert engine.get_session(*play)["cast"] == ["alice"]


def test_private_visit_replaces_group_without_requiring_each_person_to_leave(play):
    story = engine.get_story(play[0], play[1])
    story["characters"][1]["name"] = "葳葳安"
    story["scenes"][0]["description"] = "初始情節：大家一起聚在海邊。"
    engine.save_story(play[0], story, play[1])
    before = engine.get_session(*play)
    before["cast"] = ["alice", "bob", "cat"]
    before["memories"]["alice"] = ["小艾的秘密"]
    before["visuals"]["alice"] = {"state_id": "hurt", "locked": True}
    engine._write(engine._session_path(*play), before)
    seen = []
    direction = {"present_ids": ["bob"], "speaker_ids": ["alice", "bob", "cat"],
                 "situation": "你走到葳葳安附近，與她單獨談話；其他人不在此處。"}
    result = engine.take_turn(*play, "我單獨去找葳葳安。", model(direction, seen))
    assert result["cast"] == ["bob"]
    assert result["situation"] == direction["situation"]
    assert result["memories"]["alice"] == before["memories"]["alice"]
    assert result["memories"]["cat"] == []
    assert result["visuals"]["alice"] == before["visuals"]["alice"]
    replies = [p for label, p in seen if label == "schat_character"]
    assert len(replies) == 1 and replies[0]["character"]["id"] == "bob"
    assert replies[0]["scene"]["cast"] == ["bob"]
    assert replies[0]["scene"]["current_situation"] == direction["situation"]
    assert engine.get_session(*play)["cast"] == ["bob"]
    assert engine.get_story(play[0], play[1])["scenes"][0]["cast"] == ["alice", "bob"]


def test_one_speaker_does_not_hide_other_people_in_the_same_location(play):
    result = engine.take_turn(*play, "阿柏，你覺得呢？", model({
        "present_ids": ["alice", "bob"], "speaker_ids": ["bob"],
        "situation": "你與兩位朋友都在圖書館，阿柏回答你的問題。"}))
    assert result["cast"] == ["alice", "bob"]
    assert result["messages"][-1]["speaker"] == "bob"


@pytest.mark.parametrize("present", [None, "bob", {}, ["ghost"], ["bob", "ghost"], [["bob"]]])
def test_invalid_full_roster_cannot_hide_people_or_replace_situation(play, present):
    before = engine.get_session(*play)
    result = engine.take_turn(*play, "繼續。", model({
        "present_ids": present, "speaker_ids": ["bob"], "situation": "錯誤名單的情況"}))
    assert result["cast"] == before["cast"]
    assert result["situation"] == before["situation"]


def test_full_roster_can_be_empty_and_can_return_to_the_group(play):
    alone = engine.take_turn(*play, "我離開所有人，獨自散步。", model({
        "present_ids": [], "speaker_ids": ["alice"], "situation": "你獨自在附近散步。"}))
    assert alone["cast"] == [] and alone["memories"]["alice"] == []
    back = engine.take_turn(*play, "我走回大家身邊。", model({
        "present_ids": ["alice", "bob", "cat", "bob"], "speaker_ids": ["alice"]}))
    assert back["cast"] == ["alice", "bob", "cat"]
    assert back["situation"] == ""


def test_full_roster_takes_priority_over_incremental_legacy_fields(play):
    result = engine.take_turn(*play, "我去私下找阿柏。", model({
        "present_ids": ["bob"], "enter_ids": ["cat"], "leave_ids": ["bob"], "speaker_ids": ["bob"]}))
    assert result["cast"] == ["bob"]


def test_private_visit_and_situation_roll_back_when_reply_fails(play):
    before = copy.deepcopy(engine.get_session(*play))
    with pytest.raises(engine.StoryError):
        engine.take_turn(*play, "我單獨找阿柏。", model({
            "present_ids": ["bob"], "situation": "你和阿柏獨處。", "speaker_ids": ["bob"]}, reply={"text": ""}))
    assert engine.get_session(*play) == before


def test_situation_is_reset_on_scene_change(play):
    engine.take_turn(*play, "我私下找阿柏。", model({
        "present_ids": ["bob"], "situation": "你與阿柏私下談話。", "speaker_ids": ["bob"]}))
    assert engine.advance(*play, "two")["situation"] == ""


def test_public_status_updates_silent_present_actor_but_ignores_absent_actor(play):
    result = engine.take_turn(*play, "阿柏緊張地等候，小艾回答。", model({
        "speaker_ids": ["alice"], "character_statuses": {
            "bob": "緊張地等候。", "cat": "不在現場的新狀態", "ghost": "不存在"}},
        reply={"public_status": "微笑回應。"}))
    assert result["statuses"] == {"alice": "微笑回應。", "bob": "緊張地等候。"}
    assert engine.get_session(*play)["statuses"] == result["statuses"]
    assert result["memories"]["bob"] == []


def test_dialogue_keeps_full_actions_in_history_and_round_trips(play):
    result = engine.take_turn(*play, "你好。", model({"speaker_ids": ["alice"]}, reply={
        "text": "小艾抬起頭，微笑著說：你好。", "dialogue": "你好。", "public_status": "微笑。"}))
    assert result["messages"][-1]["text"] == "小艾抬起頭，微笑著說：你好。"
    assert result["messages"][-1]["dialogue"] == "你好。"
    assert engine.get_session(*play)["messages"][-1] == result["messages"][-1]
    seen = []
    engine.take_turn(*play, "繼續。", model({"speaker_ids": ["alice"]}, seen))
    assert seen[-1][1]["current_public_status"] == "微笑。"
    assert any(m["text"] == "小艾抬起頭，微笑著說：你好。" for m in seen[-1][1]["public_history"])


@pytest.mark.parametrize("value", [None, [], {}, 123])
def test_invalid_status_and_dialogue_fields_do_not_break_legacy_reply(play, value):
    result = engine.take_turn(*play, "繼續。", model({"speaker_ids": ["alice"],
        "character_statuses": {"bob": value}}, reply={"public_status": value, "dialogue": value}))
    assert result["statuses"] == {}
    assert "dialogue" not in result["messages"][-1]
    assert result["messages"][-1]["text"] == "我到了。"


def test_statuses_upgrade_old_save_and_remove_deleted_characters(play):
    saved = engine.get_session(*play)
    saved.pop("statuses")
    engine._write(engine._session_path(*play), saved)
    assert engine.get_session(*play)["statuses"] == {}
    saved["statuses"] = {"alice": "觀察四周。", "bob": "疲倦。", "cat": [], "ghost": "不存在"}
    engine._write(engine._session_path(*play), saved)
    story = engine.get_story(play[0], play[1])
    story["characters"] = [c for c in story["characters"] if c["id"] != "bob"]
    story["scenes"][0]["cast"] = ["alice"]
    engine.save_story(play[0], story, play[1])
    assert engine.get_session(*play)["statuses"] == {"alice": "觀察四周。"}


def test_failed_reply_does_not_save_public_status_update(play):
    before = copy.deepcopy(engine.get_session(*play))
    with pytest.raises(engine.StoryError):
        engine.take_turn(*play, "小艾變得紧張。", model({"speaker_ids": ["alice"],
            "character_statuses": {"alice": "緊張。"}}, reply={"text": "", "public_status": "放鬆。"}))
    assert engine.get_session(*play) == before
