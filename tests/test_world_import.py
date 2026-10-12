"""Synthetic public fixtures; user ZIPs and credentials never enter Git."""
import copy
import hashlib
from io import BytesIO
import json
import zipfile

from PIL import Image
import pytest

import story_engine as engine
import world_import
import world_runtime


def archive(files):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for name, value in files.items():
            zipped.writestr(name, json.dumps(value).encode() if isinstance(value, dict) else value)
    return stream.getvalue()


@pytest.fixture(scope='module')
def packages():
    specials = ['char_01_f03','char_01_f02','char_03_guild_head','char_06_rune','char_03_adventurer_m','char_03_adventurer_f','char_02_head']
    ids = specials + [f'char_test_{i:02}' for i in range(54 - len(specials))]
    regions = [{'id':'region_01','name':'王國'}, {'id':'region_02','name':'學院'}]
    characters = [{'id':cid, 'name':None if cid == 'char_02_head' else '角色' + str(i),
        'display_label':'學院長' if cid == 'char_02_head' else '職位' + str(i),
        'home_region_id':'region_02', 'follower_candidate':True, 'fixed_identity':True} for i,cid in enumerate(ids)]
    locations = [{'id':'loc_03_guild','name':'公會','region_id':'region_02','parent_location_id':None},
                 {'id':'loc_02_library','name':'星輝圖書館','region_id':'region_02','parent_location_id':None}]
    world = {'schema_version':'1.0.0','world_id':'world_magic_isekai','world_version':'1.0.0','title':'測試世界',
        'regions':regions, 'characters':characters, 'locations':locations,
        'facts':[{'id':'public_id','text':'公開身分','scope':'public','evidence_status':'confirmed'},
                 {'id':'hidden','text':'SECRET_AUTHOR_FACT','scope':'author_only','evidence_status':'confirmed'}],
        'canon_rules':[], 'event_seeds':[{'id':'seed_pending','initial_state':'seed'}]}
    knowledge = {'schema_version':'1.0.0','grants':[{'audience':'important_characters','fact_ids':['public_id']}],
        'relationships':[{'id':'private_friend','holders':['char_01_f03','char_01_f02'], 'description':'SECRET_PRIVATE_FRIEND'}]}
    bindings = {'schema_version':'1.0.0','characters':{},'npcs':{},'locations':{},'portrait_usage_overrides':{}}
    manifest = {'schema_version':'1.0.0','world_id':world['world_id'],'world_version':'1.0.0','assets':[]}
    files = {}
    for i in range(195):
        category = 'important_character' if i < 54 else 'npc' if i < 153 else 'background'
        cid = ids[i] if i < 54 else f'npc_02_n{i-53:02}' if i < 153 else 'loc_02_library' if i == 153 else f'loc_area_{i-153:02}'
        path = 'assets/' + cid + '.webp'
        raw = BytesIO()
        Image.new('RGBA',(4,5),(i,20,40,255 if i < 12 else 90)).save(raw,'WEBP',lossless=True)
        content = raw.getvalue()
        files[path] = content
        field = 'background_asset_key' if category == 'background' else 'portrait_asset_key'
        section = 'locations' if category == 'background' else 'npcs' if category == 'npc' else 'characters'
        key = 'asset:' + cid
        bindings[section][cid] = {field:key}
        if i < 12:
            bindings['portrait_usage_overrides'][cid] = {'render_mode':'image_with_original_background','cutout_required':False}
        manifest['assets'].append({'category':category,'entity_id':cid,'asset_key':key,'path':path,'label':'素材' + str(i),
            'region_id':'region_02','webp_bytes':len(content),'webp_sha256':hashlib.sha256(content).hexdigest(), 'width':4,'height':5})
    world_files = {'world/data/world.json':world,'world/data/knowledge.json':knowledge,
                   'world/checks/validate.py':b'raise RuntimeError("MUST NEVER EXECUTE")'}
    files['asset_manifest.json'] = manifest
    files['asset_bindings.json'] = bindings
    return world_files, files


def import_world(tmp_path, packages):
    return world_import.import_packages(tmp_path, BytesIO(archive(packages[0])), BytesIO(archive(packages[1])))


@pytest.fixture
def imported(tmp_path, packages):
    story = import_world(tmp_path, packages)['story']
    session = engine.start_session(tmp_path, story['id'])
    return tmp_path, story, session


def apply(imported, action, **values):
    root, story, session = imported
    current = engine.get_session(root, story['id'], session['id'])
    return world_runtime.action(root, story['id'], session['id'], {'action':action,
        'event_id':'event_' + str(current['world_state']['revision']), 'base_revision':current['world_state']['revision'], **values})


def test_full_import_keeps_ids_images_and_existing_model(tmp_path, packages):
    engine._root(tmp_path).joinpath('model.json').write_bytes(b'EXISTING_MODEL_CREDENTIAL')
    result = import_world(tmp_path, packages)
    story = result['story']
    assert len(story['characters']) == 153
    assert result['report']['images'] == 195
    assert {c['id'] for c in story['characters'] if c['kind'] == 'important_character'} == {c['id'] for c in packages[0]['world/data/world.json']['characters']}
    assert len({c['id'] for c in story['characters'] if c['kind'] == 'npc'}) == 99
    assert next(c for c in story['characters'] if c['id'] == 'char_02_head')['name'] == '學院長'
    assert engine._root(tmp_path).joinpath('model.json').read_bytes() == b'EXISTING_MODEL_CREDENTIAL'
    for c in story['characters'][:12]:
        assert c['portrait_render_mode'] == 'image_with_original_background'
        assert engine._root(tmp_path).joinpath('media',c['avatar']).read_bytes() == packages[1]['assets/' + c['id'] + '.webp']
    library = engine._scene(story, 'loc_02_library')
    assert engine._root(tmp_path).joinpath('media',library['background']).read_bytes() == packages[1]['assets/loc_02_library.webp']


@pytest.mark.parametrize('damage',['hash','dimension','missing','wrong_binding','count','duplicate_id','cycle','version'])
def test_invalid_packages_leave_no_story_or_images(tmp_path, packages, damage):
    world, images = copy.deepcopy(packages)
    manifest = images['asset_manifest.json']
    if damage == 'hash': manifest['assets'][-1]['webp_sha256'] = 'bad'
    if damage == 'dimension': manifest['assets'][0]['width'] = 999
    if damage == 'missing': images.pop(manifest['assets'][0]['path'])
    if damage == 'wrong_binding': images['asset_bindings.json']['characters']['char_01_f03']['portrait_asset_key'] = 'wrong'
    if damage == 'count': manifest['assets'].pop()
    if damage == 'duplicate_id': world['world/data/world.json']['characters'][1]['id'] = 'char_01_f03'
    if damage == 'cycle': world['world/data/world.json']['locations'][0]['parent_location_id'] = 'loc_03_guild'
    if damage == 'version': world['world/data/world.json']['world_version'] = '2.0'
    with pytest.raises(engine.StoryError):
        import_world(tmp_path,(world,images))
    assert not list(tmp_path.rglob('*.webp'))
    assert not list((tmp_path / 's_chat/stories').glob('*.json'))
    assert not list((tmp_path / 's_chat').glob('.world-import-*'))


@pytest.mark.parametrize('path',['../escape.py','/absolute.webp','C:/outside.webp','assets\\bad.webp'])
def test_zip_paths_are_rejected_without_executing_code(tmp_path, packages, path):
    world, images = copy.deepcopy(packages)
    images[path] = b'UNTRUSTED'
    with pytest.raises(engine.StoryError): import_world(tmp_path,(world,images))
    assert not list(tmp_path.rglob('*.webp'))


def test_zip_capacity_guard(tmp_path, packages, monkeypatch):
    monkeypatch.setattr(world_import,'MAX_EXPANDED',30)
    with pytest.raises(engine.StoryError): import_world(tmp_path,packages)


def test_commit_failure_rolls_back_new_images(tmp_path, packages, monkeypatch):
    def fail(*args): raise OSError('disk unavailable')
    monkeypatch.setattr(engine,'_write',fail)
    with pytest.raises(OSError): import_world(tmp_path,packages)
    assert not list(tmp_path.rglob('*.webp'))


def test_reimport_is_idempotent_and_version_drift_preserves_save(imported, packages):
    root, story, session = imported
    path = engine._session_path(root,story['id'],session['id'])
    before = path.read_bytes()
    result = import_world(root,packages)
    assert result['already_imported'] is True and before == path.read_bytes()
    world, art = copy.deepcopy(packages)
    world['world/data/world.json']['title'] = 'Changed'
    with pytest.raises(engine.StoryError): import_world(root,(world,art))
    assert before == path.read_bytes()


def test_follow_leave_travel_and_resume_keep_identity_and_memory(imported):
    root, story, original = imported
    apply(imported,'arrive',character_id='char_06_rune')
    apply(imported,'arrive',character_id='char_03_guild_head')
    current = apply(imported,'join',character_id='char_06_rune')
    path = engine._session_path(root,story['id'],original['id'])
    current['memories']['char_06_rune'].append('個人記憶')
    engine._write(path,current)
    moved = apply(imported,'travel',location_id='loc_02_library')
    assert moved['cast'] == ['char_06_rune']
    assert moved['world_state']['characters']['char_03_guild_head']['location_id'] == 'loc_03_guild'
    assert moved['memories']['char_06_rune'] == ['個人記憶']
    left = apply(imported,'leave',character_id='char_06_rune')
    assert left['world_state']['party_character_ids'] == [] and left['cast'] == ['char_06_rune']
    moved = apply(imported,'travel',location_id='loc_03_guild')
    assert 'char_06_rune' not in moved['cast']
    assert engine.get_session(root,story['id'],original['id']) == moved
    fresh = engine.start_session(root,story['id'])
    assert fresh['world_state']['party_character_ids'] == [] and fresh['memories']['char_06_rune'] == []


def test_turn_uses_only_own_memory_and_granted_facts_and_retries_once(imported):
    root, story, initial = imported
    apply(imported,'arrive',character_id='char_03_guild_head')
    current = apply(imported,'arrive',character_id='char_01_f03')
    current['memories']['char_01_f03'] = ['OTHER_PRIVATE_MEMORY']
    engine._write(engine._session_path(root,story['id'],initial['id']), current)
    seen = []
    def generate(system,user,label):
        payload = json.loads(user)
        seen.append((label,payload))
        if label == 'schat_director':
            return {'present_ids':['char_03_guild_head'], 'speaker_ids':['char_03_guild_head'], 'next_scene_id':'loc_02_library'}
        return {'text':'我知道你的公開身分。','remember':['我聽到玩家介紹身分。']}
    result = engine.take_turn(root,story['id'],initial['id'],'你好',generate,event_id='turn_unique',base_revision=current['world_state']['revision'])
    assert result['scene_id'] == 'loc_03_guild'
    assert result['world_state']['pending_travel']['duration'] is None
    assert result['world_state']['event_states'] == {}
    actor = next(p for label,p in seen if label == 'schat_character')
    serialized = json.dumps(actor)
    assert 'OTHER_PRIVATE_MEMORY' not in serialized and 'SECRET_PRIVATE_FRIEND' not in serialized and 'SECRET_AUTHOR_FACT' not in serialized
    assert actor['authorized_knowledge']['facts'][0]['id'] == 'public_id'
    assert 'avatar' not in serialized and len(seen[0][1]['available_characters']) < 20
    entry = result['world_state']['memory_entries']['char_03_guild_head'][0]
    assert entry['event_id'] == 'turn_unique' and entry['character_id'] == 'char_03_guild_head'
    def no_call(*args): raise AssertionError('duplicate must not regenerate')
    retried = engine.take_turn(root,story['id'],initial['id'],'你好',no_call,event_id='turn_unique',base_revision=0)
    assert retried == result


def test_remote_mentions_do_not_spawn_and_failure_does_not_save(imported):
    root,story,initial = imported
    story['characters'][3]['region_id'] = 'region_01'
    engine._write(engine._story_path(root,story['id']),story)
    current = apply(imported,'arrive',character_id='char_03_guild_head')
    path = engine._session_path(root,story['id'],initial['id'])
    before = path.read_bytes()
    def fail(system,user,label):
        if label == 'schat_director': return {'present_ids':['char_06_rune'],'speaker_ids':['char_06_rune']}
        raise RuntimeError('provider failed')
    with pytest.raises(RuntimeError):
        engine.take_turn(root,story['id'],initial['id'],'提到遠方人物',fail,event_id='failed',base_revision=current['world_state']['revision'])
    assert before == path.read_bytes()
    with pytest.raises(world_runtime.ConflictError):
        engine.take_turn(root,story['id'],initial['id'],'你好',fail,event_id='stale',base_revision=0)
    assert before == path.read_bytes()


def test_world_save_cannot_strip_metadata_or_replace_stable_ids(imported):
    root,story,initial = imported
    edited = copy.deepcopy(story)
    edited.pop('world')
    with pytest.raises(engine.StoryError): engine.save_story(root,edited,story['id'])
    edited = copy.deepcopy(story)
    edited['characters'][0]['id'] = 'new_person'
    with pytest.raises(engine.StoryError): engine.save_story(root,edited,story['id'])
    with pytest.raises(engine.StoryError): engine.get_session(root/'other',story['id'],initial['id'])


def test_import_and_world_actions_use_existing_authenticated_routes(tmp_path, packages, monkeypatch):
    import app
    import auth
    from flask import g
    def signed(req=None):
        g.user_id = 'test_world_author'; g.user_data_dir = str(tmp_path); g.is_admin = False
    monkeypatch.setattr(auth,'check_request',signed)
    client = app.app.test_client()
    # The actual world includes natural locations without a region. JSON
    # serialization must still succeed on the first HTTP import, not just when
    # reading the already-serialized story back from disk.
    world_files, art_files = copy.deepcopy(packages)
    world_files['world/data/world.json']['locations'].append(
        {'id':'loc_natural_sea','name':'大海','region_id':None,'parent_location_id':None})
    response = client.post('/api/schat/world-import',data={
        'world_zip':(BytesIO(archive(world_files)),'world.zip'),
        'images_zip':(BytesIO(archive(art_files)),'images.zip')})
    assert response.status_code == 201
    session = client.post('/api/schat/stories/world_magic_isekai/sessions').json
    route = '/api/schat/stories/world_magic_isekai/sessions/' + session['id'] + '/world-action'
    result = client.post(route,json={'action':'arrive','character_id':'char_06_rune','event_id':'one','base_revision':0})
    assert result.status_code == 200 and result.json['cast'] == ['char_06_rune']
    assert client.post(route,json={'action':'join','character_id':'char_06_rune','event_id':'two','base_revision':0}).status_code == 409
    assert client.post('/api/schat/world-import',data={}).status_code == 400
    assert client.get('/assets/js/schat-library.js').status_code == 200
    monkeypatch.setattr(auth,'check_request',lambda req: ({'error':'not logged in'},401))
    assert client.post('/api/schat/world-import',data={}).status_code == 401
