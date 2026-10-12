import copy
import json

import pytest

import story_engine as engine
import story_tracker as tracker


def definition():
    names = ['艾蓮娜・凡・奧斯汀', '瑟莉亞・星月', '莉莉安・莫雷蒂', '薇薇安・奈特羅德', '塔爾婭（Talya）']
    chars = [dict(id=f'c{i}', name=name) for i, name in enumerate(names)]
    return dict(title='營地', premise='資源有限', opening='沙灘', characters=chars,
                scenes=[dict(id='beach', title='海灘', cast=['c0', 'c1'], next=['forest']),
                        dict(id='forest', title='森林', cast=['c4'], next=[])],
                state_tracker=tracker.camp_tracker(chars))


def setup(tmp_path):
    story = engine.save_story(tmp_path, definition())
    session = engine.start_session(tmp_path, story['id'])
    return story, session


def test_exact_author_initial_values_and_binding(tmp_path):
    story, session = setup(tmp_path)
    assert session['tracker'] == {
        'camp.water': 5, 'camp.wood': 0, 'camp.food': 2, 'camp.safety': 10,
        'relations.reputation': 0, 'relations.attitude': '敵對', 'relations.seal': 100,
        'elena.affinity': 5, 'elena.dependency': 10, 'elena.state': '企圖發號施令',
        'celia.affinity': 10, 'celia.dependency': 5, 'celia.state': '茫然挫敗、難以提劍',
        'lilian.affinity': 15, 'lilian.dependency': 20, 'lilian.state': '極度恐懼、眼角泛淚',
        'vivian.affinity': 5, 'vivian.dependency': 15, 'vivian.state': '暗中防備',
        'talya.affinity': 0, 'talya.submission': 0, 'talya.state': '潛伏在叢林邊緣，觀察中'}
    assert [g.get('character_id') for g in story['state_tracker'][2:]] == [f'c{i}' for i in range(5)]


def test_changes_persist_and_actor_only_receives_own_psychology(tmp_path):
    story, session = setup(tmp_path)
    seen = []
    def model(system, user, label):
        data = json.loads(user)
        if label == 'schat_director':
            assert data['state_tracker'][0]['fields'][0]['value'] == 5
            return dict(present_ids=['c0'], speaker_ids=['c0'], tracker_updates={
                'camp.water': {'value': 30, 'reason': '玩家帶回 25 單位淡水'},
                'elena.affinity': {'value': 8, 'reason': '感謝玩家送水'},
                'vivian.affinity': {'value': 90, 'reason': '不在現場'},
                'unknown.key': {'value': 1, 'reason': '無效欄位'}})
        seen.append(data)
        assert '玩家原話' == data['player_input']
        assert data['speaker_names']['player'] == '玩家'
        assert '不能把玩家的原話' in system
        return {'text': '艾蓮娜放下水囊：「謝謝你帶回水。」', 'dialogue': '玩家原話'}
    result = engine.take_turn(tmp_path, story['id'], session['id'], '玩家原話', model)
    assert result['tracker']['camp.water'] == 30
    assert result['tracker']['elena.affinity'] == 8
    assert result['tracker']['vivian.affinity'] == 5
    assert len(result['tracker_events']) == 2
    assert len(seen[0]['state_tracker']) == 3
    assert seen[0]['state_tracker'][-1]['character_id'] == 'c0'
    assert engine.get_session(tmp_path, story['id'], session['id']) == result
    moved = engine.advance(tmp_path, story['id'], session['id'], 'forest')
    assert moved['tracker'] == result['tracker']


@pytest.mark.parametrize('value', [-1, 101, True, '25', None, float('nan'), float('inf'), {}, []])
def test_invalid_updates_never_corrupt_saved_values(tmp_path, value):
    story, session = setup(tmp_path)
    tracker.apply_updates(story, session, {'camp.water': {'value': value, 'reason': '測試'}})
    assert session['tracker']['camp.water'] == 5
    assert 'tracker_events' not in session


@pytest.mark.parametrize('update', [25, {'value': 25}, {'value': 25, 'reason': ''}, {'value': 25, 'reason': 5}])
def test_updates_require_narrative_reason(tmp_path, update):
    story, session = setup(tmp_path)
    tracker.apply_updates(story, session, {'camp.water': update})
    assert session['tracker']['camp.water'] == 5


def test_unbound_role_is_visible_as_tracker_only_never_enters_scene(tmp_path):
    data = definition()
    data['characters'].pop()
    data['scenes'][1]['cast'] = ['c0']
    story = engine.save_story(tmp_path, data)
    session = engine.start_session(tmp_path, story['id'])
    assert story['state_tracker'][-1]['character_id'] == ''
    tracker.apply_updates(story, session, {'talya.affinity': {'value': 50, 'reason': '未登場'}})
    assert session['tracker']['talya.affinity'] == 0
    assert session['cast'] == ['c0', 'c1']


def test_legacy_save_migration_preserves_all_history_and_progress(tmp_path):
    story, session = setup(tmp_path)
    session.pop('tracker')
    path = engine._session_path(tmp_path, story['id'], session['id'])
    engine._write(path, session)
    migrated = engine.get_session(tmp_path, story['id'], session['id'])
    assert {k: v for k, v in migrated.items() if k != 'tracker'} == session
    migrated['tracker']['camp.water'] = 40
    engine._write(path, migrated)
    story['state_tracker'][0]['fields'][0]['initial'] = 20
    engine.save_story(tmp_path, story, story['id'])
    assert engine.get_session(tmp_path, story['id'], session['id'])['tracker']['camp.water'] == 40
    assert engine.start_session(tmp_path, story['id'])['tracker']['camp.water'] == 20


def test_actor_failure_rolls_back_tracker_and_every_other_change(tmp_path):
    story, session = setup(tmp_path)
    path = engine._session_path(tmp_path, story['id'], session['id'])
    before = path.read_bytes()
    def model(system, user, label):
        if label == 'schat_director':
            return {'speaker_ids': ['c0'], 'tracker_updates': {'camp.water': {'value': 80, 'reason': '送水'}}}
        raise RuntimeError('模型無法回覆')
    with pytest.raises(RuntimeError):
        engine.take_turn(tmp_path, story['id'], session['id'], '送水', model)
    assert path.read_bytes() == before


@pytest.mark.parametrize('field,value', [('initial', -1), ('initial', True), ('max', float('inf')), ('min', 100), ('kind', 'script')])
def test_invalid_author_config_is_rejected(field, value):
    data = definition()
    data['state_tracker'][0]['fields'][0][field] = value
    with pytest.raises(engine.StoryError):
        engine.validate_story(data)


def test_no_updates_or_unknown_attitude_preserve_values(tmp_path):
    story, session = setup(tmp_path)
    before = copy.deepcopy(session)
    tracker.apply_updates(story, session, None)
    tracker.apply_updates(story, session, {'relations.attitude': {'value': '不明', 'reason': '無效'}})
    assert session == before
