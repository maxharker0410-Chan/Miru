"""The S.Chat-only server keeps original accounts and isolates every story."""
import json
from io import BytesIO
import pytest
from flask import g
from test_story_engine import definition
import story_engine as engine
import sandbox


@pytest.fixture
def signed_app(tmp_path,monkeypatch):
    import app,auth
    def authenticated(req=None):
        g.user_id='u_test';g.user_data_dir=str(tmp_path);g.is_admin=False
    monkeypatch.setattr(auth,'check_request',authenticated)
    return app.app.test_client(),tmp_path


def test_retired_miru_routes_do_not_exist(signed_app):
    client,_=signed_app
    for path in ('/pet','/api/sensor','/api/memory','/api/models/list','/api/admin/users','/assets/js/companion/sprite-adapter.js'):
        assert client.get(path).status_code==404
    assert client.get('/api/health').json['service']=='s-chat'
    assert client.get('/login').status_code==200
    assert client.get('/assets/js/schat-sandbox.js').status_code==200
    assert client.get('/assets/js/schat-login.js').status_code==200


def test_api_save_restore_and_private_state_redaction(signed_app):
    client,root=signed_app
    story=client.post('/api/schat/stories',json=definition()).json
    base='/api/schat/stories/'+story['id']
    first=client.post(base+'/sessions',json={'player_profile':{'name':'測試玩家'}}).json
    raw=engine.get_session(root,story['id'],first['id'])
    raw['memories']['bob']=['BOB_PRIVATE_MEMORY']
    raw['sandbox']['knowledge']['bob']=[{'text':'BOB_PRIVATE_BELIEF'}]
    engine._write(engine._session_path(root,story['id'],first['id']),raw)
    view=client.get(base+'/sessions/'+first['id']).json
    assert 'BOB_PRIVATE' not in json.dumps(view)
    assert client.post(base+'/saves',json={'session_id':first['id'],'slot':'slot_1','label':'新存檔'}).status_code==200
    assert client.get(base+'/saves').json['slots'][0]['label']=='新存檔'
    loaded=client.post(base+'/saves/slot_1/load').json
    assert loaded['id']!=first['id']
    assert engine.get_session(root,story['id'],loaded['id'])['memories']['bob']==['BOB_PRIVATE_MEMORY']


def test_non_object_requests_and_wrong_origin_are_rejected(signed_app):
    client,_=signed_app
    story=client.post('/api/schat/stories',json=definition()).json
    assert client.post('/api/schat/stories/'+story['id']+'/sessions',json=[]).status_code==400
    assert client.post('/api/schat/stories',json=definition(),headers={'Origin':'https://hostile.test'}).status_code==403


def test_original_local_account_is_reused_and_not_duplicated(tmp_path,monkeypatch):
    import app,auth
    monkeypatch.setattr(auth,'_BASE_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setattr(auth,'_ADMIN_DIR',str(tmp_path/'data/_admin'))
    monkeypatch.setattr(app,'_is_client_mode',True)
    saved=[]
    monkeypatch.setattr(app,'_persist_config',lambda value:saved.append(value))
    client=app.app.test_client()
    first=client.post('/api/client/local/start',environ_base={'REMOTE_ADDR':'127.0.0.1'}).json
    second=client.post('/api/client/local/start',environ_base={'REMOTE_ADDR':'127.0.0.1'}).json
    assert first['user_id']==second['user_id'] and first['token']==second['token']
    assert saved[-1]['auth_token']==first['token']
    assert client.post('/api/client/local/start',environ_base={'REMOTE_ADDR':'203.0.113.1'}).status_code==403
    assert client.post('/api/client/local/start',headers={'Host':'attacker.test'},environ_base={'REMOTE_ADDR':'127.0.0.1'}).status_code==403


def test_prose_and_word_draft_use_existing_model_without_saving(signed_app,monkeypatch):
    import story_author
    from test_world_import import archive
    client,root=signed_app
    monkeypatch.setattr(engine,'_model',lambda *args:definition())
    before=engine.list_stories(root)
    response=client.post('/api/schat/author-draft',json={'text':'兩個朋友在圖書館尋書。'})
    assert response.status_code==200 and 'id' not in response.json['draft']
    xml=b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Test story</w:t></w:r></w:p></w:body></w:document>'
    response=client.post('/api/schat/author-draft',data={'document':(BytesIO(archive({'word/document.xml':xml})),'story.docx')})
    assert response.status_code==200 and response.json['draft']['title']=='雨夜圖書館'
    assert engine.list_stories(root)==before
    with pytest.raises(engine.StoryError):
        story_author.document_text(BytesIO(archive({'word/document.xml':b'<!DOCTYPE document><document />'})))


def test_windows_reuses_local_or_remote_login_destination():
    import windows_launcher
    assert windows_launcher._initial_url({'auth_token':'saved','setup_complete':True,'local_only':True}).startswith('http://127.0.0.1:5001/s-chat')
    assert windows_launcher._initial_url({'auth_token':'saved','server_url':'https://existing.example'}).startswith('https://existing.example/s-chat')
    assert windows_launcher._initial_url({'auth_token':'saved','server_url':'javascript:evil'}).startswith('http://127.0.0.1:5001/s-chat')
