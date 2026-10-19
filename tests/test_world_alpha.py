import copy
from io import BytesIO
import json

import pytest

import story_engine as engine
import world_import
import world_memory
import world_release
import world_runtime
from test_world_import import packages, imported, apply, archive


def release(story):
    return {'schema_version':'1.0.0', 'world_id':'world_magic_isekai',
        'content_version':'1.3.0-alpha.1', 'runtime_rules':{
            'party_limit':4, 'memory_interval':8, 'memory_min':5, 'memory_max':10,
            'large_active_portrait':True},
        'character_directions':{c['id']:{'role':'測試職業', 'skills':['自己的技能'],
            'limits':'無法無限施法', 'status':'blueprint'} for c in story['characters']
            if c['kind'] == 'important_character'},
        'quests':[], 'enemies':[], 'items':[]}


def test_fifth_follower_is_rejected_without_eviction_or_save_change(imported):
    root, story, session = imported
    ids = [c['id'] for c in story['characters'][:5]]
    for cid in ids:
        apply(imported, 'arrive', character_id=cid)
    for cid in ids[:4]:
        apply(imported, 'join', character_id=cid)
    path = engine._session_path(root, story['id'], session['id'])
    before = path.read_bytes()
    with pytest.raises(engine.StoryError, match='最多同行 4 人'):
        apply(imported, 'join', character_id=ids[4])
    assert path.read_bytes() == before
    assert engine.get_session(root, story['id'], session['id'])['world_state']['party_character_ids'] == ids[:4]


def test_travel_cannot_sneak_in_a_fifth_companion(imported):
    root, story, session = imported
    ids = [c['id'] for c in story['characters'][:5]]
    session['cast'] = ids
    session['world_state']['party_character_ids'] = ids[:4]
    original = copy.deepcopy(session)
    with pytest.raises(engine.StoryError):
        world_runtime.move(story, session, 'loc_02_library', [ids[4]])
    assert session == original


def test_director_cannot_evict_a_member_to_free_a_slot(imported):
    root, story, session = imported
    ids = [c['id'] for c in story['characters'][:5]]
    session['cast'] = ids
    session['world_state']['party_character_ids'] = ids[:4]
    engine._write(engine._session_path(root,story['id'],session['id']), session)
    before = engine._session_path(root,story['id'],session['id']).read_bytes()
    def generate(system,user,label):
        return {'next_scene_id':'loc_02_library', 'travel_status':'arrived',
            'traveling_ids':ids, 'present_ids':ids, 'leave_ids':[ids[0]]}
    with pytest.raises(engine.StoryError, match='明確安排'):
        engine.take_turn(root,story['id'],session['id'],'大家一起走到星輝圖書館。',generate,
            event_id='no_silent_eviction',base_revision=0)
    assert engine._session_path(root,story['id'],session['id']).read_bytes()==before


def test_existing_overfull_party_is_preserved_until_user_arranges_leave(imported):
    root, story, session = imported
    ids = [c['id'] for c in story['characters'][:5]]
    session['cast'] = ids
    session['world_state']['party_character_ids'] = ids
    engine._write(engine._session_path(root, story['id'], session['id']), session)
    assert engine.get_session(root, story['id'], session['id'])['world_state']['party_character_ids'] == ids
    result = apply(imported, 'leave', character_id=ids[-1])
    assert result['world_state']['party_character_ids'] == ids[:4]
    assert result['world_state']['characters'][ids[-1]]['last_departure']['location_id'] == session['scene_id']


def test_eight_interactions_summarize_only_witnesses_and_archive_raw_text(imported):
    root, story, session = imported
    a, b, absent = [c['id'] for c in story['characters'][:3]]
    session['cast'] = [a, b]
    session['memories'][absent] = ['ABSENT_PRIVATE_SECRET']
    engine._write(engine._session_path(root, story['id'], session['id']), session)
    summaries = []
    def generate(system, user, label):
        value = json.loads(user)
        if label == 'schat_director':
            return {'present_ids':[a, b], 'speaker_ids':[a], 'situation':'在此交談'}
        if label == 'schat_character':
            assert 'ABSENT_PRIVATE_SECRET' not in user
            return {'text':'我記得這次一起採樣。', 'remember':['我的採樣觀察']}
        summaries.append((label, value))
        assert 'ABSENT_PRIVATE_SECRET' not in user
        return {'summary':'我們在這裡共同採樣，原因尚待確認。'}
    for n in range(8):
        session = engine.take_turn(root, story['id'], session['id'], '一起看水樣', generate,
            event_id=f'count_{n}', base_revision=session['world_state']['revision'])
        if n < 7:
            assert summaries == []
    memory = session['world_state']['memory_system']
    assert len(memory['characters'][a]['summaries']) == 1
    assert len(memory['characters'][b]['summaries']) == 1
    assert absent not in memory['characters']
    assert len(memory['journal']['summaries']) == 1
    assert len(summaries) == 3
    archive_dir = engine._root(root) / 'archives' / story['id'] / session['id']
    assert len(list(archive_dir.glob('*.json'))) == 8
    assert json.loads((archive_dir/'count_0.json').read_text())['messages'][0]['text'] == '一起看水樣'
    def no_call(*args):
        raise AssertionError('accepted event must not regenerate')
    assert engine.take_turn(root, story['id'], session['id'], '一起看水樣', no_call,
        event_id='count_7', base_revision=0) == session


def test_summary_failure_keeps_pending_sources_and_gameplay(imported):
    root, story, session = imported
    cid = story['characters'][0]['id']
    session['cast'] = [cid]
    engine._write(engine._session_path(root, story['id'], session['id']), session)
    def generate(system, user, label):
        if label == 'schat_director':
            return {'present_ids':[cid], 'speaker_ids':[cid]}
        if label == 'schat_character':
            return {'text':'我看見了。'}
        raise RuntimeError('temporary provider failure')
    for n in range(8):
        session = engine.take_turn(root, story['id'], session['id'], '觀察', generate,
            event_id=f'fail_{n}', base_revision=session['world_state']['revision'])
    ledger = session['world_state']['memory_system']['characters'][cid]
    assert len(ledger['pending']) == 8 and ledger['summary_pending'] is True
    assert 'fail_7' in session['world_state']['accepted_event_ids']


def test_memory_lookup_is_scoped_and_bounded(imported):
    _, story, session = imported
    a, b = [c['id'] for c in story['characters'][:2]]
    session['memories'][a] = ['果園採樣'] + [f'記錄 {n}' for n in range(30)]
    session['memories'][b] = ['OTHER_PRIVATE_SECRET']
    selected = world_memory.select(session, a, '再次調查果園')
    assert '果園採樣' in selected and len(selected) <= 6
    assert 'OTHER_PRIVATE_SECRET' not in selected
    assert len(session['memories'][a]) == 31


def test_private_short_term_notes_survive_until_compaction(imported):
    _, story, session = imported
    a, b = [c['id'] for c in story['characters'][:2]]
    memory = world_memory.initialize(session)
    memory['characters'][a] = {'pending':[{'own_notes':['OWN_UNSPOKEN_IMPRESSION']}], 'summaries':[]}
    memory['characters'][b] = {'pending':[{'own_notes':['OTHER_UNSPOKEN_SECRET']}], 'summaries':[]}
    assert world_memory.select(session, a) == ['OWN_UNSPOKEN_IMPRESSION']


@pytest.mark.parametrize('damage', ['party', 'character', 'duplicate', 'version'])
def test_release_validation_rejects_conflicting_or_incomplete_settings(imported, damage):
    _, story, _ = imported
    content = release(story)
    if damage == 'party': content['runtime_rules']['party_limit'] = 5
    if damage == 'character': content['character_directions'].pop(next(iter(content['character_directions'])))
    if damage == 'duplicate': content['quests'] = [{'id':'Q01-01','text':'x'}]*2
    if damage == 'version': content['content_version'] = '../../unsafe'
    with pytest.raises(engine.StoryError):
        world_release.validate(content, content['character_directions'] if damage != 'character'
            else [c['id'] for c in story['characters'] if c['kind']=='important_character'])


def test_release_upgrade_preserves_save_model_and_legacy_cards(imported):
    root, story, session = imported
    path = engine._session_path(root, story['id'], session['id'])
    before = path.read_bytes()
    model = engine._root(root) / 'model.json'
    model.write_text('PRIVATE_MODEL_SETTINGS')
    content = release(story)
    data = archive({'bundle/release/content.json':content})
    result = world_release.install(root, story['id'], BytesIO(data), '')
    assert result['story']['world']['content_release']['content_version'] == '1.3.0-alpha.1'
    assert path.read_bytes() == before and model.read_text() == 'PRIVATE_MODEL_SETTINGS'
    assert result['story']['characters'] == story['characters']
    assert world_release.install(root, story['id'], BytesIO(data), '')['already_installed'] is True
    content['content_version'] = '1.3.0-alpha.2'
    with pytest.raises(engine.StoryError, match='重新載入'):
        world_release.install(root, story['id'], BytesIO(archive({'release/content.json':content})), '')


def test_initial_import_can_include_new_content(packages, tmp_path):
    base, images = copy.deepcopy(packages)
    # Derive IDs from the real converter-shaped fixture without user materials.
    original = world_import.import_packages(tmp_path/'seed', BytesIO(archive(base)), BytesIO(archive(images)))['story']
    base['world/release/content.json'] = release(original)
    result = world_import.import_packages(tmp_path/'new', BytesIO(archive(base)), BytesIO(archive(images)))
    assert result['story']['world']['content_release']['runtime_rules']['party_limit'] == 4
