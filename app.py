"""S.Chat application: stories, invitation login and Windows/PWA access only."""
import os
import sys
import json
import threading
from pathlib import Path
from flask import Flask, g, jsonify, request, render_template, send_from_directory, redirect
from flask_compress import Compress
from werkzeug.exceptions import HTTPException
import auth
import story_engine
import sandbox

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 9 * 1024 * 1024
Compress(app)
_is_client_mode = False
_client_mode_config = {}
_open_webui_requested = threading.Event()
_logout_requested = threading.Event()


def _bundled_resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def _local_origin():
    from urllib.parse import urlsplit
    return (auth.is_local_request(request) and urlsplit(request.host_url).hostname in {'localhost','127.0.0.1','::1'}
        and (not request.headers.get('Origin') or request.headers['Origin'].rstrip('/') == request.host_url.rstrip('/')))


def _body():
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise story_engine.StoryError('操作資料需為物件。')
    return value


@app.before_request
def before_request():
    if request.method in {'POST','PUT','PATCH','DELETE'}:
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
            return jsonify(error='請從 S.Chat 頁面操作。'), 403
    return auth.check_request(request)


@app.after_request
def after_request(response):
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
        if request.path.startswith('/api/schat/assets/') and response.status_code == 200:
            response.headers['Cache-Control'] = 'private, max-age=86400'
    return response


@app.errorhandler(HTTPException)
def http_error(error):
    return jsonify(error=str(error.description)), error.code


def session_response(session):
    story = story_engine.get_story(getattr(g, 'user_data_dir', None), session['story_id'])
    return jsonify(sandbox.player_view(story, session))


@app.get('/')
@app.get('/app')
def index():
    return redirect('/s-chat')


@app.get('/api/health')
def health():
    return jsonify(ok=True, service='s-chat', rules_version=sandbox.RULES_VERSION)


def _persist_config(value):
    from desktop_paths import launcher_config_path
    path = launcher_config_path()
    story_engine._write(path, value)
    _client_mode_config.clear()
    _client_mode_config.update(value)


@app.get('/api/client-config')
def client_config():
    value = {'client_mode':_is_client_mode, 'local_only':bool(_client_mode_config.get('local_only'))}
    if _local_origin():
        value.update({key:_client_mode_config.get(key, '') for key in ('auth_token','user_id','setup_complete')})
    return jsonify(value)


@app.post('/api/client/local/start')
def local_start():
    if not _is_client_mode or not _local_origin():
        return jsonify(error='此功能只在本機 Windows 版使用。'), 403
    result = auth.get_or_create_local_single_device_user()
    _persist_config({'mode':'local','local_only':True,'setup_complete':True,
        'user_id':result['user_id'],'auth_token':result['token'],'server_url':''})
    return jsonify(result)


@app.post('/api/auth/login')
def login():
    body = request.get_json(silent=True)
    code = body.get('code', '') if isinstance(body, dict) else ''
    if not isinstance(code, str) or not code.strip():
        return jsonify(error='請輸入原本的完整邀請碼。'), 400
    if _is_client_mode:
        if not _local_origin():
            return jsonify(error='請從本機登入。'), 403
        server = auth.server_url_from_invitation_code(code)
        if not server:
            return jsonify(error='請輸入完整邀請碼。'), 400
        import requests
        try:
            response = requests.post(server + '/api/auth/login', json={'code':code}, timeout=15)
            result = response.json()
        except (requests.RequestException, ValueError):
            return jsonify(error='無法連上邀請碼對應的伺服器。'), 502
        if response.status_code != 200 or not result.get('token'):
            return jsonify(error='邀請碼無效或暫時無法登入。'), 401
        _persist_config({'user_id':result['user_id'],'auth_token':result['token'],
            'server_url':server, 'local_only':False, 'setup_complete':True})
        return jsonify(**result, server_url=server)
    result = auth.login_with_code(code)
    return (jsonify(result), 200) if result else (jsonify(error='邀請碼無效或已停用。'), 401)


@app.get('/api/auth/me')
def me():
    return jsonify(user_id=g.user_id, is_admin=g.is_admin)


@app.post('/api/auth/logout')
def logout():
    if _is_client_mode and _local_origin():
        _persist_config({})
        _logout_requested.set()
    return jsonify(ok=True)


@app.post('/api/open-webui')
def open_webui():
    if not _local_origin():
        return jsonify(error='local only'), 403
    _open_webui_requested.set()
    return jsonify(ok=True)


@app.get('/assets/<path:name>')
def assets(name):
    return send_from_directory(_bundled_resource_root() / 'assets', name)


@app.route("/s-chat")
def s_chat_page():
    """S. Chat story studio and scene player."""
    resp = app.make_response(render_template("s-chat.html"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/s-chat/manifest.json")
def schat_manifest():
    return send_from_directory(_bundled_resource_root(), "schat-manifest.json",
                               mimetype="application/manifest+json")


@app.route("/s-chat/service-worker.js")
def schat_service_worker():
    resp = send_from_directory(_bundled_resource_root(), "schat-service-worker.js",
                               mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/s-chat"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/api/schat/account")
def api_schat_account():
    return jsonify({"user_id": g.user_id})


def _story_user_dir():
    return getattr(g, "user_data_dir", None)


@app.errorhandler(story_engine.StoryError)
def _story_error(error):
    from world_runtime import ConflictError
    return jsonify({"error": str(error)}), 409 if isinstance(error, ConflictError) else 400


@app.route("/api/schat/world-import", methods=["POST"])
def api_schat_world_import():
    from world_import import import_packages, MAX_UPLOAD
    request.max_content_length = MAX_UPLOAD
    if (request.content_length or 0) > MAX_UPLOAD:
        return jsonify({"error":"兩份 ZIP 合計請小於 512 MB。"}), 413
    world = request.files.get("world_zip")
    images = request.files.get("images_zip")
    if not world or not images:
        return jsonify({"error":"請一次選擇世界資料包及 WebP 圖片包。"}), 400
    try:
        result = import_packages(_story_user_dir(), world.stream, images.stream)
    except story_engine.StoryError:
        raise
    except (KeyError, TypeError, ValueError):
        return jsonify({"error":"資料包索引格式不完整，既有故事與紀錄未變更。"}), 400
    return jsonify(result), 200 if result["already_imported"] else 201


@app.route("/api/schat/stories/<story_id>/sessions/<session_id>/world-action", methods=["POST"])
def api_schat_world_action(story_id, session_id):
    import world_runtime
    return session_response(world_runtime.action(_story_user_dir(), story_id, session_id, request.get_json(silent=True)))


@app.route("/api/schat/stories/<story_id>/world-settings", methods=["POST"])
def api_schat_world_settings(story_id):
    from world_settings import apply_document, MAX_DOCUMENT
    request.max_content_length = MAX_DOCUMENT
    if (request.content_length or 0) > MAX_DOCUMENT:
        return jsonify({"error":"Word 設定書請小於 16 MB。"}), 413
    document = request.files.get("world_document")
    if not document or not (document.filename or "").lower().endswith(".docx"):
        return jsonify({"error":"請選擇完整的魔法異世界 Word 設定書（.docx）。"}), 400
    revision = request.form.get("base_settings_revision", "")
    if not revision.isdecimal():
        return jsonify({"error":"請重新載入故事後更新設定書。"}), 400
    return jsonify(apply_document(_story_user_dir(), story_id, document.stream, int(revision)))


@app.route("/api/schat/model", methods=["GET", "PUT"])
def api_schat_model():
    if request.method == "GET":
        return jsonify(story_engine.model_status(_story_user_dir()))
    return jsonify(story_engine.save_model(_story_user_dir(), request.get_json(silent=True)))


@app.route("/api/schat/model/test", methods=["POST"])
def api_schat_model_test():
    try:
        answer = story_engine._model(_story_user_dir(), "只輸出 JSON：{\"ok\":true}", "測試連線", "schat_test")
        if not isinstance(answer, dict):
            raise ValueError("回覆格式錯誤")
        return jsonify({"ok": True})
    except Exception as error:
        app.logger.warning("S.Chat model test failed (%s)", type(error).__name__)
        return jsonify({"error": "模型連線失敗，請檢查服務地址、模型 ID 和 API Key。"}), 502


@app.route("/api/schat/stories", methods=["GET", "POST"])
def api_schat_stories():
    if request.method == "GET":
        return jsonify({"stories": story_engine.list_stories(_story_user_dir())})
    return jsonify(story_engine.save_story(_story_user_dir(), request.get_json(silent=True))), 201


@app.route("/api/schat/stories/<story_id>", methods=["GET", "PUT", "DELETE"])
def api_schat_story(story_id):
    if request.method == "GET":
        return jsonify(story_engine.get_story(_story_user_dir(), story_id))
    if request.method == "DELETE":
        story_engine.delete_story(_story_user_dir(), story_id)
        return jsonify({"ok": True})
    return jsonify(story_engine.save_story(_story_user_dir(), request.get_json(silent=True), story_id))


@app.route("/api/schat/stories/<story_id>/sessions", methods=["GET", "POST"])
def api_schat_start(story_id):
    if request.method == "GET":
        return jsonify({"sessions": story_engine.list_sessions(_story_user_dir(), story_id)})
    body = _body()
    test_run = isinstance(body, dict) and body.get("test_run") is True
    return session_response(story_engine.start_session(_story_user_dir(), story_id, test_run=test_run, player_profile=(body or {}).get("player_profile"))), 201


@app.route("/api/schat/stories/<story_id>/sessions/<session_id>")
def api_schat_session(story_id, session_id):
    return session_response(story_engine.get_session(_story_user_dir(), story_id, session_id))


@app.route("/api/schat/stories/<story_id>/sessions/<session_id>/advance", methods=["POST"])
def api_schat_advance(story_id, session_id):
    body = _body()
    return session_response(story_engine.advance(_story_user_dir(), story_id, session_id, body.get("scene_id"),
                   body.get("event_id"), body.get("base_revision")))


@app.route("/api/schat/stories/<story_id>/sessions/<session_id>/visuals", methods=["PATCH"])
def api_schat_visuals(story_id, session_id):
    body = _body()
    return session_response(story_engine.set_visual(_story_user_dir(), story_id, session_id,
                   body.get("character_id"), body.get("state_id"), body.get("locked")))


@app.route("/api/schat/stories/<story_id>/sessions/<session_id>/turn", methods=["POST"])
def api_schat_turn(story_id, session_id):
    body = _body()
    try:
        return session_response(story_engine.take_turn(_story_user_dir(), story_id, session_id, body.get("text"),
                       event_id=body.get("event_id"), base_revision=body.get("base_revision")))
    except story_engine.StoryError:
        raise
    except Exception as error:
        app.logger.warning("S.Chat model failed (%s)", type(error).__name__)
        return jsonify({"error": "角色暫時無法回應，請檢查聊天模型設定後重試。"}), 502


@app.route("/api/schat/assets", methods=["POST"])
def api_schat_upload():
    from io import BytesIO
    from PIL import Image, UnidentifiedImageError
    import uuid
    uploaded = request.files.get("image")
    if not uploaded or (request.content_length or 0) > 9 * 1024 * 1024:
        return jsonify({"error": "請上傳小於 8 MB 的 PNG、JPG 或 WebP 圖片"}), 400
    raw = uploaded.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        return jsonify({"error": "圖片超過 8 MB"}), 400
    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            if image.width > 6000 or image.height > 6000:
                raise ValueError("圖片尺寸超過限制")
            ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(image.format)
    except (UnidentifiedImageError, OSError, ValueError):
        ext = None
    if not ext:
        return jsonify({"error": "圖片格式或尺寸不支援"}), 400
    root = story_engine._root(_story_user_dir()) / "media"
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + "." + ext
    (root / name).write_bytes(raw)
    return jsonify({"file": name, "url": "/api/schat/assets/" + name}), 201


@app.route("/api/schat/assets/<name>")
def api_schat_asset(name):
    if not story_engine._IMAGE.fullmatch(name):
        return jsonify({"error": "無效圖片"}), 404
    return send_from_directory(story_engine._root(_story_user_dir()) / "media", name)


@app.route("/login")
def login_page():
    """Invitation code entry — Japanese minimalist design.

    DMG WebView opens this on first launch when no auth token is stored.
    On successful login, JS redirects to /app?token=<token>.
    """
    resp = app.make_response(render_template("login.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp



@app.route('/api/schat/stories/<story_id>/saves', methods=['GET','POST'])
def saves(story_id):
    if request.method == 'GET':
        return jsonify(slots=sandbox.list_slots(_story_user_dir(), story_id))
    body = _body()
    return jsonify(sandbox.save_slot(_story_user_dir(), story_id, body.get('session_id'), body.get('slot'), body.get('label')))


@app.post('/api/schat/stories/<story_id>/saves/<slot>/load')
def load_save(story_id, slot):
    return session_response(sandbox.load_slot(_story_user_dir(), story_id, slot))


@app.post('/api/schat/packages')
def install_package():
    import story_packages
    request.max_content_length = story_packages.MAX_UPLOAD
    uploaded = request.files.get('package_zip')
    if not uploaded:
        raise story_engine.StoryError('請選擇故事、素材或 DLC ZIP。')
    return jsonify(story_packages.install(_story_user_dir(), uploaded.stream, request.form.get('story_id')))


@app.patch('/api/schat/stories/<story_id>/sessions/<session_id>/character-art')
def character_art(story_id, session_id):
    body = _body()
    return session_response(sandbox.bind_art(_story_user_dir(), story_id, session_id, body.get('character_id'), body.get('image')))


@app.post('/api/schat/author-draft')
def author_draft():
    import story_author
    request.max_content_length = 16 * 1024 * 1024
    document = request.files.get('document')
    if document:
        if not (document.filename or '').lower().endswith('.docx'):
            raise story_engine.StoryError('請選擇 Word .docx 設定書。')
        text = story_author.document_text(document.stream)
    else:
        text = _body().get('text')
    try:
        return jsonify(draft=story_author.draft(_story_user_dir(), text))
    except story_engine.StoryError:
        raise
    except Exception:
        return jsonify(error='整理草稿失敗，原有故事不受影響。請確認模型或稍後再試。'), 502


def run_client_mode(server_url='', auth_token='', port=5001):
    global _is_client_mode
    _is_client_mode = True
    from desktop_paths import launcher_config_path
    path = launcher_config_path()
    config = story_engine._read(path) if path.is_file() else {}
    _client_mode_config.update(config)
    from waitress import serve
    serve(app, host='127.0.0.1', port=port, threads=8, expose_tracebacks=False)


if __name__ == '__main__':
    from waitress import serve
    serve(app, host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '5001')), threads=8)
