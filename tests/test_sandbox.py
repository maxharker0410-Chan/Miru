"""Sandbox v1.1 state transitions, privacy, replay and legacy save compatibility."""
import copy
import json
from io import BytesIO
import hashlib

import pytest
from PIL import Image
import story_engine as engine
import sandbox
import story_packages
from test_story_engine import definition
from test_world_import import archive


@pytest.fixture
def game(tmp_path):
    story = engine.save_story(tmp_path, definition())
    session = engine.start_session(tmp_path, story['id'])
    return tmp_path, story, session


def turn(game, text='繼續', changes=None, direction=None, actor=None):
    root, story, first = game
    before = engine.get_session(root, story['id'], first['id'])
    proposal = {'present_ids':before['cast'], 'speaker_ids':[], 'sandbox':changes or {}}
    proposal.update(direction or {})
    def generate(system, user, label):
        if label == 'schat_director':
            return copy.deepcopy(proposal)
        return actor(json.loads(user)) if actor else {'text':'我明白了。'}
    return engine.take_turn(root,story['id'],first['id'],text,generate,
        event_id='turn_' + str(before['sandbox']['revision']),base_revision=before['sandbox']['revision'])


def test_clock_uses_one_context_estimate_not_actor_count_or_wall_time(game):
    seen = []
    result = turn(game,changes={'elapsed_seconds':120,'context':'ordinary'},
        direction={'speaker_ids':['alice','alice','bob']},actor=lambda p:(seen.append(p) or {'text':'我看著窗外。'}))
    assert result['sandbox']['elapsed_seconds'] == 120
    assert len(seen) == 2
    assert all(p['personal_context']['elapsed_seconds'] == 120 for p in seen)
    urgent = turn(game,changes={'elapsed_seconds':900,'context':'urgent'})
    assert urgent['sandbox']['elapsed_seconds'] == 150


def test_empty_speaker_list_allows_silence_and_narration(game):
    result = turn(game,changes={'narration':'兩人沉默地看著雨勢。','await_player':True})
    assert result['messages'][-1]['speaker'] == 'narrator'
    assert result['sandbox']['await_player'] is True
    assert result['sandbox']['elapsed_seconds'] == 0


def test_secret_audience_is_preserved_and_not_sent_to_other_actor(game):
    root, story, _ = game
    session = engine.start_session(root,story['id'], player_profile={'background':'旅行者','secrets':[
        {'text':'ALICE_ONLY_BACKGROUND','audience':['alice']}, {'text':'PLAYER_ONLY_BACKGROUND','audience':[]}]})
    seen = []
    result = turn((root,story,session),direction={'speaker_ids':['alice','bob']},actor=lambda p:(seen.append(p) or {'text':'你好。'}))
    alice, bob = seen
    assert 'ALICE_ONLY_BACKGROUND' in json.dumps(alice)
    assert 'ALICE_ONLY_BACKGROUND' not in json.dumps(bob)
    assert 'PLAYER_ONLY_BACKGROUND' not in json.dumps(seen)
    assert 'ALICE_ONLY_BACKGROUND' in json.dumps(result['sandbox'])


def test_known_rumor_and_relationship_dimensions_do_not_become_objective_facts(game):
    evidence = '我聽說北邊的橋斷了'
    result = turn(game,evidence,{'knowledge_updates':[
        {'holder':'alice','text':'北橋可能已斷','certainty':'rumor','channel':'report','evidence':evidence},
        {'holder':'bob','text':'沒有來源的資料','certainty':'known','channel':'report','evidence':'偽造的證據來源'}],
        'relationship_changes':[
            {'holder':'alice','target':'player','dimension':'trust','delta':5,'evidence':evidence},
            {'holder':'alice','target':'player','dimension':'fear','delta':-2,'evidence':evidence}]})
    state = result['sandbox']
    assert state['knowledge']['alice'][0]['certainty'] == 'rumor'
    assert 'bob' not in state['knowledge'] and state['objective_facts'] == []
    assert state['relationships']['alice']['player']['trust'] == 5
    assert state['relationships']['alice']['player']['affection'] == 0
    view = sandbox.player_view(game[1],result)
    assert '北橋可能已斷' not in json.dumps(view,ensure_ascii=False)
    assert view['memories'] == {} and 'relationships' not in view['sandbox']


def test_wait_stops_at_deadline_and_action_continues_after_leaving(game):
    line = '請查查那座橋到底怎麼了'
    result = turn(game,line,{'npc_actions':[{'id':'bridge','actor':'alice','intent':'查明橋梁狀況',
        'method':'前往橋頭詢問','resources':'自己的時間','duration_seconds':90,'visibility':'public','evidence':line}]})
    assert result['sandbox']['actions']['bridge']['phase'] == 'executing'
    result = turn(game,'等待 1 小時',direction={'present_ids':[]})
    assert result['sandbox']['elapsed_seconds'] == 90
    assert result['sandbox']['actions']['bridge']['phase'] == 'awaiting_result'
    assert result['sandbox']['await_player'] is True
    # A due time alone does not invent a successful investigation.
    assert 'result' not in result['sandbox']['actions']['bridge']


def test_private_actions_are_absent_from_player_panels(game):
    line = '她低聲說要找人調查線索'
    result = turn(game,line,{'npc_actions':[{'id':'private','actor':'alice','intent':'PRIVATE_NPC_PLAN',
        'method':'私人管道','resources':'人脈','duration_seconds':90,'visibility':'private','evidence':line}]})
    assert 'PRIVATE_NPC_PLAN' in json.dumps(result['sandbox'])
    assert 'PRIVATE_NPC_PLAN' not in json.dumps(sandbox.player_view(game[1],result))


def test_pause_resume_and_panel_reads_do_not_advance_clock_or_speak(game):
    root,story,first = game
    result = turn(game,'/pause')
    assert result['sandbox']['run_status'] == 'paused' and result['messages'] == first['messages']
    with pytest.raises(engine.StoryError,match='暫停'):
        turn(game,'你好')
    result = turn(game,'/resume')
    assert result['sandbox']['elapsed_seconds'] == 0
    before = copy.deepcopy(result)
    sandbox.player_panel(story,result)
    sandbox.list_slots(root,story['id'])
    assert engine.get_session(root,story['id'],first['id']) == before


def test_saves_restore_entire_state_as_separate_branch(game):
    root,story,first = game
    evidence = '我把桌上的舊鑰匙收起來'
    result = turn(game,evidence,{'elapsed_seconds':30,'inventory_changes':[{'id':'key','name':'舊鑰匙','delta':1,'evidence':evidence}]})
    result['memories']['alice'] = ['保留重要承諾']
    engine._write(engine._session_path(root,story['id'],first['id']),result)
    sandbox.save_slot(root,story['id'],first['id'],'slot_1','談判之前')
    later = turn(game,'等待 2 小時')
    restored = sandbox.load_slot(root,story['id'],'slot_1')
    assert restored['id'] != result['id']
    assert restored['sandbox'] == result['sandbox']
    assert restored['memories'] == result['memories']
    assert restored['messages'] == result['messages']
    assert engine.get_session(root,story['id'],first['id']) == later
    other = engine.save_story(root,definition())
    with pytest.raises(engine.StoryError):
        sandbox.load_slot(root,other['id'],'slot_1')


def test_dynamic_npc_has_stable_identity_and_picture_binding_keeps_memory(game):
    root,story,first = game
    evidence = '我向大門口的警衛詢問入口'
    result = turn(game,evidence,{'new_npcs':[{'key':'guard','name':'王警衛','role':'門衛','background':'值班警衛','motive':'核對來客','evidence':evidence}]},
        direction={'speaker_ids':['guard']},actor=lambda p:{'text':'請先登記。','remember':['玩家來訪']})
    npc = result['sandbox']['dynamic_characters'][0]
    assert npc['id'].startswith('npc_') and npc['avatar'] == ''
    assert result['messages'][-1]['speaker'] == npc['id']
    assert result['memories'][npc['id']] == ['玩家來訪']
    assert npc['id'] in engine.get_session(root,story['id'],first['id'])['cast']
    data=BytesIO(); Image.new('RGB',(2,2)).save(data,'WEBP')
    image='a'*32+'.webp'; media=engine._root(root)/'media';media.mkdir(exist_ok=True);(media/image).write_bytes(data.getvalue())
    bound=sandbox.bind_art(root,story['id'],first['id'],npc['id'],image)
    assert bound['memories'][npc['id']] == ['玩家來訪']
    effective=sandbox.effective_story(story,bound)
    assert next(c for c in effective['characters'] if c['id']==npc['id'])['avatar']==image
    assert len(engine.get_story(root,story['id'])['characters'])==2


def test_death_ends_run_and_dead_npc_cannot_speak_again(game):
    evidence='阿柏已經沒有呼吸心跳了'
    result=turn(game,evidence,{'outcomes':[{'character_id':'bob','result':'dead','evidence':evidence,'reason':'傷勢無法挽回'}]},direction={'speaker_ids':['bob']})
    assert 'bob' not in result['cast']
    assert not any(m['speaker']=='bob' for m in result['messages'])
    result=turn(game,'我倒在地上失去所有生命跡象',{'outcomes':[{'character_id':'player','result':'dead','evidence':'我倒在地上失去所有生命跡象','reason':'致命傷勢'}]})
    assert result['sandbox']['run_status']=='dead'
    with pytest.raises(engine.StoryError,match='故事已結束'):
        turn(game)


def test_failed_actor_or_retried_event_does_not_double_commit(game):
    root,story,first=game
    path=engine._session_path(root,story['id'],first['id']); before=path.read_bytes()
    def fail(payload): raise RuntimeError('provider failed')
    with pytest.raises(RuntimeError):
        turn(game,changes={'elapsed_seconds':10},direction={'speaker_ids':['alice']},actor=fail)
    assert path.read_bytes()==before
    result=turn(game,changes={'elapsed_seconds':10})
    def no_call(*args): raise AssertionError('must not regenerate')
    retried=engine.take_turn(root,story['id'],first['id'],'繼續',no_call,event_id='turn_0',base_revision=0)
    assert retried==result


def test_legacy_save_migrates_without_losing_history_or_memory(game):
    root,story,first=game
    first.pop('sandbox');first['memories']['alice']=['舊版重要經歷']
    engine._write(engine._session_path(root,story['id'],first['id']),first)
    migrated=engine.get_session(root,story['id'],first['id'])
    assert migrated['sandbox']['rules_version']=='1.1'
    assert migrated['memories']==first['memories'] and migrated['messages']==first['messages']


def test_story_package_dlc_retroactivity_and_art_preserve_saved_history(game):
    root,story,first=game
    turn(game,'等待 2 分鐘')
    before=engine._session_path(root,story['id'],first['id']).read_bytes()
    package={'schema_version':1,'type':'dlc','package_id':'rain','version':'1','target_story_id':story['id'],
        'characters':[{'id':'vendor','name':'攤販'}], 'events':[
            {'id':'future','trigger':'after_seconds','seconds':30,'text':'商人到訪。','interrupt':True},
            {'id':'past','trigger':'after_seconds','seconds':30,'text':'舊消息傳來。','retroactive':True}]}
    raw=archive({'schat-package.json':package})
    result=story_packages.install(root,BytesIO(raw),story['id'])
    assert not result['already_installed']
    assert engine._session_path(root,story['id'],first['id']).read_bytes()==before
    assert story_packages.install(root,BytesIO(raw),story['id'])['already_installed']
    current=turn(game)
    assert current['sandbox']['installed_events']['rain:past']['triggered']
    assert not current['sandbox']['installed_events']['rain:future']['triggered']
    current=turn(game,'等待 2 分鐘')
    assert current['sandbox']['elapsed_seconds']==150
    assert current['sandbox']['installed_events']['rain:future']['triggered']
    text=[m['text'] for m in current['messages']]
    turn(game)
    assert sum('商人到訪。' in m['text'] for m in current['messages'])==1


@pytest.mark.parametrize('bad_path',['../evil.py','/absolute','a\\b','a:b'])
def test_zip_paths_rejected_without_changes(game,bad_path):
    root,story,first=game
    package={'schema_version':1,'type':'assets','package_id':'art','version':'1','target_story_id':story['id']}
    raw = archive({'schat-package.json':package,bad_path:b'data'})
    if bad_path == 'a\\b':
        raw = raw.replace(b'a/b', b'a\\b')  # Windows ZipInfo normalizes paths while writing.
    with pytest.raises(engine.StoryError):
        story_packages.install(root,BytesIO(raw),story['id'])
    assert 'packages' not in engine.get_story(root,story['id'])


def test_cross_story_assets_and_dlc_cannot_overwrite_characters(game):
    root,story,first=game
    package={'schema_version':1,'type':'dlc','package_id':'bad','version':'1','target_story_id':story['id'],
             'characters':[{'id':'alice','name':'被覆寫的人'}]}
    with pytest.raises(engine.StoryError):
        story_packages.install(root,BytesIO(archive({'schat-package.json':package})),story['id'])
    package.update(type='assets',target_story_id='unrelated_story')
    with pytest.raises(engine.StoryError):
        story_packages.install(root,BytesIO(archive({'schat-package.json':package})),story['id'])


def test_restored_branch_retains_old_picture_and_accepts_new_dlc(game):
    root,story,first=game
    sandbox.save_slot(root,story['id'],first['id'],'slot_1')
    restored=sandbox.load_slot(root,story['id'],'slot_1')
    changed=copy.deepcopy(story)
    changed['characters'][0]['name']='作者的新名稱'
    engine.save_story(root,changed,story['id'])
    package={'schema_version':1,'type':'dlc','package_id':'new_shop','version':'1','target_story_id':story['id'],
        'characters':[{'id':'shopkeeper','name':'店主'}], 'scenes':[{'id':'shop','title':'新商店','cast':['shopkeeper'],'next':[]}],
        'events':[{'id':'arrival','trigger':'after_seconds','seconds':10,'text':'收到商店開幕消息。'}]}
    story_packages.install(root,BytesIO(archive({'schat-package.json':package})),story['id'])
    raw=engine.get_session(root,story['id'],restored['id'])
    effective=sandbox.effective_story(engine.get_story(root,story['id']),raw)
    assert effective['characters'][0]['name']=='小艾'
    assert any(c['id']=='shopkeeper' for c in effective['characters'])
    assert any(s['id']=='shop' for s in effective['scenes'])
    assert 'new_shop:arrival' in raw['sandbox']['installed_events']
    view=sandbox.player_view(engine.get_story(root,story['id']),raw)
    assert view['render_definition']['characters'][0]['name']=='小艾'


def test_private_minor_action_does_not_interrupt_player_wait(game):
    evidence='她低聲說要找人調查線索'
    turn(game,evidence,{'npc_actions':[{'id':'private','actor':'alice','intent':'私下調查','method':'詢問朋友',
        'resources':'人脈','duration_seconds':30,'visibility':'private','evidence':evidence}]})
    result=turn(game,'等待 1 小時')
    assert result['sandbox']['elapsed_seconds']==3600
    assert result['sandbox']['actions']['private']['phase']=='awaiting_result'


@pytest.mark.parametrize('text,seconds', [('我等一個小時',3600),('*等待半小時*',1800),('等待兩分鐘',120),('等待十二秒',12),('「我等一小時」',None),('明天再等一小時',None)])
def test_explicit_wait_supports_chinese_numbers_without_turning_quotes_into_commands(text,seconds):
    assert sandbox.wait_seconds(text)==seconds
