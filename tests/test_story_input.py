import json
import story_engine as engine
from story_input import input_parts
from test_story_engine import definition


def test_actions_and_speech_keep_their_order():
    assert input_parts('你好，**我向她揮手**請過來。**後退一步**') == [
        {'kind':'speech','text':'你好，'}, {'kind':'action','text':'我向她揮手'},
        {'kind':'speech','text':'請過來。'}, {'kind':'action','text':'後退一步'}]


def test_unclosed_and_empty_markers_remain_literal():
    assert input_parts('**未結束') == [{'kind':'speech','text':'**未結束'}]
    assert input_parts('**  **') == [{'kind':'speech','text':'**  **'}]
    assert input_parts('') == []


def test_multiline_action_is_not_spoken():
    assert input_parts('**抬頭\n觀察天空**') == [{'kind':'action','text':'抬頭\n觀察天空'}]


def test_director_actor_and_saved_message_receive_explicit_actions(tmp_path):
    story = engine.save_story(tmp_path, definition())
    session = engine.start_session(tmp_path, story['id'])
    seen = []
    def generate(system, user, label):
        payload = json.loads(user)
        seen.append((system,payload))
        return {'present_ids':['alice'],'speaker_ids':['alice']} if label == 'schat_director' else {'text':'我看到了。'}
    raw = '**我輕輕揮手**你好。'
    result = engine.take_turn(tmp_path, story['id'], session['id'], raw, generate)
    assert all(payload['player_input_parts'] == input_parts(raw) for _,payload in seen)
    assert all('不是說出口的台詞' in system for system,_ in seen)
    saved = next(m for m in result['messages'] if m['speaker'] == 'player')
    assert saved['text'] == raw and saved['input_parts'] == input_parts(raw)
