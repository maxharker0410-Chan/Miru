import json

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

from mobile_gateway import MobileGateway, PUBLIC


@pytest.fixture
def gate():
    seen = []
    def inner(environ, start):
        seen.append(environ)
        return Response('inner',headers={'Access-Control-Allow-Origin':'https://other.test'})(environ,start)
    app = MobileGateway(inner, 'private-pair', 'phone-token', 'desktop-secret')
    return Client(app, Response), app, seen


@pytest.mark.parametrize('path', ['/api/admin/users','/api/client-config','/api/auth/export','/api/open-webui','/api/user-settings','/app','/api/health'])
def test_desktop_and_admin_routes_are_not_exposed_even_with_phone_token(gate, path):
    client, app, seen = gate
    response = client.get(path,headers={'Authorization':'Bearer phone-token'})
    assert response.status_code == 404
    assert not seen


@pytest.mark.parametrize('path', ['/api/schat/stories','/api/schat/model','/api/schat/assets/'+ 'a'*32+'.png'])
def test_loopback_and_forged_forwarded_headers_cannot_bypass_phone_login(gate, path):
    client, app, seen = gate
    response = client.get(path,headers={'X-Forwarded-For':'127.0.0.1','X-Real-IP':'127.0.0.1'})
    assert response.status_code == 401
    assert not seen


def test_pairing_returns_phone_token_without_exposing_desktop_credential(gate):
    client, app, seen = gate
    assert client.post('/mobile/pair',json={'pairing_code':'incorrect'}).status_code == 401
    response = client.post('/mobile/pair',json={'pairing_code':'private-pair'})
    assert response.json == {'token':'phone-token'}
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'desktop-secret' not in response.get_data(as_text=True)
    assert not seen


@pytest.mark.parametrize('payload', [[],None,{'pairing_code':123},{'pairing_code':'繁體🙂'}])
def test_malformed_pairing_is_rejected_without_server_error(gate, payload):
    client, app, seen = gate
    response = client.post('/mobile/pair',data=json.dumps(payload),content_type='application/json')
    assert response.status_code == 401


def test_only_matching_phone_token_reaches_account_data(gate):
    client, app, seen = gate
    assert client.get('/api/schat/account',headers={'Authorization':'Bearer desktop-secret'}).status_code == 401
    assert client.get('/api/schat/account?token=wrong').status_code == 401
    response = client.get('/api/schat/account',headers={'Authorization':'Bearer phone-token','X-Real-IP':'forged'})
    assert response.status_code == 200
    assert seen[-1]['HTTP_AUTHORIZATION'] == 'Bearer desktop-secret'
    assert seen[-1]['REMOTE_ADDR'] == '127.0.0.1'
    assert 'HTTP_X_REAL_IP' not in seen[-1]
    assert 'Access-Control-Allow-Origin' not in response.headers
    assert response.headers['Referrer-Policy'] == 'no-referrer'


def test_image_url_token_is_supported_and_unknown_methods_are_blocked(gate):
    client, app, seen = gate
    assert client.get('/api/schat/assets/'+ 'a'*32+'.png?token=phone-token').status_code == 200
    assert client.open('/api/schat/stories',method='OPTIONS').status_code == 404


def test_cross_origin_mutation_and_pairing_are_denied(gate):
    client, app, seen = gate
    headers={'Authorization':'Bearer phone-token','Origin':'https://foreign.test'}
    assert client.post('/api/schat/stories',json={},headers=headers).status_code == 403
    assert client.post('/mobile/pair',json={'pairing_code':'private-pair'},headers=headers).status_code == 403
    assert not seen


def test_bad_pairing_attempts_are_limited_and_window_expires(gate):
    client, app, seen = gate
    now = [0]
    app.clock = lambda:now[0]
    for _ in range(10):
        assert client.post('/mobile/pair',json={'pairing_code':'bad'}).status_code == 401
    assert client.post('/mobile/pair',json={'pairing_code':'bad'}).status_code == 429
    now[0] = 61
    assert client.post('/mobile/pair',json={'pairing_code':'private-pair'}).status_code == 200


@pytest.mark.parametrize('path', sorted(PUBLIC))
def test_pwa_public_shell_routes_remain_reachable(gate, path):
    client, app, seen = gate
    assert client.get(path).status_code == 200
    assert len(seen) == 1


def test_public_login_uses_mobile_pairing_and_contains_no_token(gate):
    client, app, seen = gate
    response = client.get('/login')
    assert '手機配對碼' in response.get_data(as_text=True)
    assert 'phone-token' not in response.get_data(as_text=True)
    assert client.get('/mobile/login.js').mimetype == 'application/javascript'
    assert client.get('/').headers['Location'] == '/login'


def test_gateway_and_real_story_api_keep_data_in_paired_users_scope(tmp_path, monkeypatch):
    import app
    import auth
    import story_engine
    monkeypatch.setattr(auth, '_BASE_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(auth, '_ADMIN_DIR', str(tmp_path / '_admin'))
    monkeypatch.setattr(app, '_is_client_mode', True)
    monkeypatch.setattr(app, '_client_mode_config', {'user_id':'u_phonetest', 'auth_token':'internal-only'})
    gateway = MobileGateway(app.app, 'pair-test', 'phone-only', 'internal-only')
    client = Client(gateway, Response)
    assert client.get('/api/schat/stories').status_code == 401
    paired = client.post('/mobile/pair',json={'pairing_code':'pair-test'})
    assert paired.status_code == 200
    headers = {'Authorization':'Bearer ' + paired.json['token']}
    result = client.post('/api/schat/stories',json={
        'title':'手機測試故事', 'characters':[{'id':'alice','name':'小艾'}],
        'scenes':[{'id':'one','title':'圖書館','cast':['alice'],'next':[]}], 'start_scene':'one'},headers=headers)
    assert result.status_code == 201
    sid = result.json['id']
    assert client.get('/api/schat/account',headers=headers).json == {'user_id':'u_phonetest'}
    assert client.get('/api/schat/stories',headers=headers).json['stories'][0]['id'] == sid
    saved = tmp_path / 'users' / 'u_phonetest' / 's_chat' / 'stories' / (sid + '.json')
    assert saved.is_file()
    assert client.post('/api/schat/stories/'+sid+'/sessions',headers=headers).status_code == 201
    story_engine.save_model(str(tmp_path/'users'/'u_phonetest'),{
        'host':'https://model.example/v1','model':'test-model','api_key':'never-return-this-key'})
    model = client.get('/api/schat/model',headers=headers)
    assert model.status_code == 200 and model.json['configured']
    assert 'never-return-this-key' not in model.get_data(as_text=True)
    assert 'api_key' not in model.json
