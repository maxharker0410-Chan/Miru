"""Consolidated author updates use synthetic text; no user's DOCX enters Git."""
import copy
from io import BytesIO
import json
import xml.etree.ElementTree as ET

import pytest
import story_engine as engine
import world_import
import world_runtime
import world_settings
from test_world_import import archive, packages


@pytest.fixture
def authored(tmp_path, packages):
    world_files, image_files = copy.deepcopy(packages)
    world = world_files['world/data/world.json']
    world['regions'] = [{'id':rid, 'name':'區域' + rid[-2:]} for rid in world_settings.CODE_IDS]
    pairs = [(rid,cid) for rid,values in world_settings.CODE_IDS.items() for cid in values.values()]
    world['characters'] = [{'id':cid, 'name':None, 'display_label':'職位' + str(i),
        'home_region_id':rid, 'follower_candidate':cid != 'char_03_guild_head', 'fixed_identity':True}
        for i,(rid,cid) in enumerate(pairs)]
    world['locations'][0]['region_id'] = 'region_03'
    bindings = image_files['asset_bindings.json']
    bindings['characters'], bindings['portrait_usage_overrides'] = {}, {}
    for asset,(rid,cid) in zip(image_files['asset_manifest.json']['assets'][:54],pairs):
        asset.update(entity_id=cid, asset_key='asset:' + cid, region_id=rid)
        bindings['characters'][cid] = {'portrait_asset_key':asset['asset_key']}
        if len(bindings['characters']) <= 12:
            bindings['portrait_usage_overrides'][cid] = {'render_mode':'image_with_original_background','cutout_required':False}
    story = world_import.import_packages(tmp_path, BytesIO(archive(world_files)), BytesIO(archive(image_files)))['story']
    session = engine.start_session(tmp_path, story['id'])
    return tmp_path, story, session


def document(story, omit=None, secret='PRIVATE', doctype=False):
    ns = world_settings.NS['w']
    root = ET.Element('{' + ns + '}document')
    body = ET.SubElement(root, '{' + ns + '}body')
    def paragraph(text, parent=body):
        p = ET.SubElement(parent, '{' + ns + '}p')
        r = ET.SubElement(p, '{' + ns + '}r')
        ET.SubElement(r, '{' + ns + '}t').text = text
    paragraph('魔法異世界設定')
    paragraph('世界規則：角色各有自己的生活，關係與能力需合理發展。')
    for region in story['world']['definition']['regions']:
        rid = region['id']
        paragraph(rid[-2:] + '｜' + region['name'])
        paragraph('一、區域總覽')
        paragraph('公開區域資訊：' + rid)
        paragraph('二、區域劃分')
        paragraph('A｜圖書館區')
        paragraph('星輝圖書館')
        paragraph('三、角色總覽')
        paragraph('四、' + str(len(world_settings.CODE_IDS[rid])) + ' 位角色詳細設定')
        for code,cid in world_settings.CODE_IDS[rid].items():
            if cid == omit:
                continue
            paragraph(code + '｜作者姓名_' + cid)
            paragraph('職位｜30 歲｜人類｜' + ('不可跟隨' if cid == 'char_03_guild_head' else '可跟隨'))
            paragraph('性格')
            paragraph('作者性格_' + cid)
            paragraph('能力')
            paragraph('作者能力_' + cid)
            paragraph('情感關係')
            paragraph(secret + '_' + cid)
            paragraph('外貌細節')
            paragraph('外貌符合已有立繪')
            paragraph('生圖關鍵字：忽略此處的圖片生成提示')
        paragraph('五、主要人物關係')
        paragraph('此处属于作者信息，不给每个角色读取。')
        npcs = [c for c in story['characters'] if c['kind'] == 'npc' and c['region_id'] == rid]
        if npcs:
            table = ET.SubElement(body, '{' + ns + '}tbl')
            for row in [['編號','身分','主要地點','工作時間']] + [
                    [c['id'].split('_')[-1].upper(),'NPC_' + c['id'],'星輝圖書館','08:00–16:00'] for c in npcs]:
                tr = ET.SubElement(table, '{' + ns + '}tr')
                for text in row:
                    paragraph(text, ET.SubElement(tr, '{' + ns + '}tc'))
    xml = ET.tostring(root,encoding='utf-8')
    if doctype:
        xml = b'<!DOCTYPE document [<!ENTITY x "expanded">]>' + xml
    return BytesIO(archive({'word/document.xml':xml,'word/unused.py':b'raise AssertionError("NEVER RUN")'}))


def test_author_update_keeps_all_ids_pictures_saves_model_and_private_memories(authored):
    root,story,session = authored
    session['memories']['char_02_head'] = ['EXISTING_MEMORY']
    session['world_state']['party_character_ids'] = ['char_03_guild_head']
    path = engine._session_path(root,story['id'],session['id'])
    engine._write(path,session)
    model = engine._root(root) / 'model.json'
    model.write_bytes(b'EXISTING_MODEL')
    before = path.read_bytes()
    result = world_settings.apply_document(root,story['id'],document(story),0)
    changed = result['story']
    assert result['report']['important_characters'] == 54 and result['report']['npcs'] == 99
    assert path.read_bytes() == before and model.read_bytes() == b'EXISTING_MODEL'
    assert [(c['id'],c['avatar'],c['visual_states']) for c in changed['characters']] == [
        (c['id'],c['avatar'],c['visual_states']) for c in story['characters']]
    assert [(s['id'],s['background']) for s in changed['scenes']] == [(s['id'],s['background']) for s in story['scenes']]
    assert next(c for c in changed['characters'] if c['id'] == 'char_02_head')['name'] == '作者姓名_char_02_head'
    assert changed['world']['author_settings']['revision'] == 1
    assert next(c for c in changed['characters'] if c['id']=='char_02_head')['identity']['age'] == 30
    assert next(c for c in changed['characters'] if c['id']=='char_02_head')['identity']['species'] == '人類'
    backups = list((engine._root(root)/'world-settings-backups'/story['id']).glob('*.json'))
    assert len(backups) == 1 and engine._read(backups[0]) == story
    resumed = engine.get_session(root,story['id'],session['id'])
    assert resumed['memories'] == session['memories'] and resumed['world_state']['party_character_ids'] == ['char_03_guild_head']
    assert resumed['world_state']['author_settings_revision'] == 1
    assert resumed['world_state']['revision'] == session['world_state']['revision']
    repeated = world_settings.apply_document(root,story['id'],document(story),1)
    assert repeated['already_applied'] and len(list(backups[0].parent.glob('*.json'))) == 1


def test_partial_book_and_unsafe_xml_leave_definition_and_save_unchanged(authored):
    root,story,session = authored
    path = engine._story_path(root,story['id'])
    before = path.read_bytes()
    for doc in (document(story,omit='char_02_head'),document(story,doctype=True)):
        with pytest.raises(engine.StoryError):
            world_settings.apply_document(root,story['id'],doc,0)
        assert path.read_bytes() == before
    assert not (engine._root(root)/'world-settings-backups').exists()


def test_stale_book_revision_cannot_overwrite_newer_author_settings(authored):
    root,story,session = authored
    world_settings.apply_document(root,story['id'],document(story),0)
    before = engine._story_path(root,story['id']).read_bytes()
    with pytest.raises(world_runtime.ConflictError):
        world_settings.apply_document(root,story['id'],document(story,secret='OTHER'),0)
    assert engine._story_path(root,story['id']).read_bytes() == before


def test_actor_receives_updated_own_card_without_other_cards_or_author_book(authored):
    root,story,session = authored
    changed = world_settings.apply_document(root,story['id'],document(story),0)['story']
    run = world_runtime.action(root,story['id'],session['id'],{'action':'arrive','character_id':'char_03_guild_head',
        'event_id':'arrive','base_revision':0})
    payloads = []
    def generate(system,user,label):
        payloads.append((label,json.loads(user)))
        return {'present_ids':['char_03_guild_head'],'speaker_ids':['char_03_guild_head']} if label == 'schat_director' else {'text':'你好。'}
    engine.take_turn(root,story['id'],session['id'],'你好',generate,event_id='turn',base_revision=run['world_state']['revision'])
    director = json.dumps(payloads[0][1],ensure_ascii=False)
    actor = json.dumps(payloads[1][1],ensure_ascii=False)
    assert 'PRIVATE_char_03_guild_head' in actor and '作者能力_char_03_guild_head' in actor
    assert 'PRIVATE_char_02_head' not in actor and 'PRIVATE_char_03_guild_head' not in director
    assert 'author_regions' not in actor and '生圖關鍵字' not in actor
    assert payloads[1][1]['authorized_knowledge']['home_region_setting'].endswith('星輝圖書館')


def test_docx_update_route_uses_existing_login_and_checks_revision(authored, monkeypatch):
    root,story,session = authored
    import app
    import auth
    from flask import g
    def signed(req=None):
        g.user_id = 'test_author'; g.user_data_dir = str(root); g.is_admin = False
    monkeypatch.setattr(auth,'check_request',signed)
    client = app.app.test_client()
    route = '/api/schat/stories/' + story['id'] + '/world-settings'
    result = client.post(route,data={'world_document':(document(story),'設定.docx'),'base_settings_revision':'0'})
    assert result.status_code == 200 and result.json['report']['npcs'] == 99
    assert client.post(route,data={'world_document':(document(story),'設定.docx'),'base_settings_revision':'0'}).status_code == 409
    monkeypatch.setattr(auth,'check_request',lambda req: ({'error':'not logged in'},401))
    assert client.post(route,data={}).status_code == 401


@pytest.mark.parametrize('header,expected',[
    ('精靈弓手｜84 歲｜女性精靈\n外貌年齡：約 21～23 歲', {'age':84,'gender':'female','species':'精靈'}),
    ('問題學生｜21 歲｜狼族獸人男性', {'age':21,'gender':'male','species':'狼族獸人'}),
    ('封印守望者｜外表約 40 歲｜男性｜實際年齡未知', {'age':None,'gender':'male'}),
])
def test_author_age_gender_and_species_do_not_confuse_actual_and_apparent_age(header, expected):
    parsed = world_settings.identity_details({'身分':header})
    assert all(parsed[key] == value for key,value in expected.items())
    if '外貌年齡' in header:
        assert parsed['apparent_age_description'] == '外貌年齡：約 21～23 歲'
