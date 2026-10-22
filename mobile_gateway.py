"""Restricted, paired phone access to S. Chat; never expose desktop/admin APIs."""
from collections import deque
import hmac
import json
import threading
import time
from urllib.parse import parse_qs

from werkzeug.wrappers import Request, Response

PUBLIC = {'/s-chat', '/s-chat/manifest.json', '/s-chat/service-worker.js', '/assets/js/schat-library.js',
          '/assets/js/schat-sandbox.js',
          '/assets/css/schat-stage.css',
          '/assets/brand/schat-icon.png',
          '/assets/js/schat.js', '/assets/brand/schat-pwa-192.png',
          '/assets/brand/schat-pwa-512.png'}
PAGE = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>S. Chat 手機配對</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100svh;background:#120e1c;color:#f4eafa;font:16px/1.6 system-ui;display:grid;place-items:center;padding:24px}
main{width:min(100%,420px);padding:28px;background:#21172f;border:1px solid #59436c;border-radius:22px}h1{margin:0;font-size:32px}p{color:#cdbddd}label{display:block;margin-bottom:8px}input,button{font:inherit;width:100%;border-radius:12px;padding:12px}input{background:#120e1c;color:white;border:1px solid #89709d}button{background:#a777d1;color:white;border:0;margin-top:16px;cursor:pointer}#message{min-height:26px;color:#ffd1df}small{color:#cdbddd}
</style><main><h1>S. Chat</h1><p>輸入這台電腦提供的手機配對碼，開啟你的故事。</p><form id="pairForm"><label for="pairCode">手機配對碼</label><input id="pairCode" type="password" required autocomplete="off" autocapitalize="none" spellcheck="false"><button id="pairButton">連接故事</button></form><p id="message" role="status"></p><small>這台電腦需保持開機及連線。成功連接後，可從故事頁選擇「安裝到手機」。</small></main><script src="/mobile/login.js" defer></script></html>'''
LOGIN_JS = ''''use strict';
const form=document.getElementById('pairForm'), code=document.getElementById('pairCode'), button=document.getElementById('pairButton'), message=document.getElementById('message');
const linked=new URLSearchParams(location.hash.slice(1)).get('pair');
if(linked){code.value=linked;history.replaceState(null,'','/login');}
form.addEventListener('submit',async event=>{
 event.preventDefault();button.disabled=true;message.textContent='正在連接…';
 try{const response=await fetch('/mobile/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pairing_code:code.value.trim()}),cache:'no-store'});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'配對失敗');
 localStorage.setItem('miru_auth_token',result.token);code.value='';location.replace('/s-chat');
 }catch(error){message.textContent=error.message;button.disabled=false;}
});
'''


class MobileGateway:
    def __init__(self, application, pairing_code, phone_token, internal_token, clock=time.monotonic):
        self.application = application
        self.pairing_code = pairing_code
        self.phone_token = phone_token
        self.internal_token = internal_token
        self.clock = clock
        self.attempts = {}
        self.lock = threading.Lock()

    @staticmethod
    def headers(status, headers, exc_info=None):
        headers = [(k, v) for k, v in headers if k.lower() not in {
            'access-control-allow-origin', 'access-control-allow-headers',
            'access-control-allow-methods', 'referrer-policy'}]
        headers += [('Referrer-Policy', 'no-referrer'), ('X-Content-Type-Options', 'nosniff'),
                    ('X-Frame-Options', 'DENY'), ('Content-Security-Policy',
                     "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                     "font-src 'self' https://fonts.gstatic.com; img-src 'self' https: data:; "
                     "connect-src 'self'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
        return status, headers, exc_info

    def __call__(self, environ, start_response):
        req = Request(environ)
        def start(status, headers, exc_info=None):
            return start_response(*self.headers(status, headers, exc_info))
        def reply(value, status=200, mimetype='application/json'):
            text = json.dumps(value, ensure_ascii=False) if mimetype == 'application/json' else value
            return Response(text, status=status, mimetype=mimetype,
                            headers={'Cache-Control': 'no-store'})(environ, start)
        path = req.path
        if path == '/' and req.method in {'GET', 'HEAD'}:
            return Response('', status=302, headers={'Location':'/login', 'Cache-Control':'no-store'})(environ, start)
        if path == '/login' and req.method in {'GET', 'HEAD'}:
            return reply(PAGE, mimetype='text/html')
        if path == '/mobile/login.js' and req.method in {'GET', 'HEAD'}:
            return reply(LOGIN_JS, mimetype='application/javascript')
        if path == '/mobile/health' and req.method == 'GET':
            return reply({'ok': True, 'service':'schat-mobile'})
        if path == '/mobile/pair' and req.method == 'POST':
            if req.content_length is None or req.content_length > 2048:
                return reply({'error':'配對資料無效。'}, 400)
            if not self._same_origin(req):
                return reply({'error':'請從手機配對頁登入。'}, 403)
            if self._limited(req):
                return reply({'error':'嘗試次數過多，請一分鐘後重試。'}, 429)
            data = req.get_json(silent=True)
            provided = data.get('pairing_code') if isinstance(data, dict) else None
            if not isinstance(provided, str) or not hmac.compare_digest(provided.encode(), self.pairing_code.encode()):
                return reply({'error':'配對碼不正確，請確認電腦上的配對說明。'}, 401)
            return reply({'token': self.phone_token})
        if path in PUBLIC and req.method in {'GET', 'HEAD'}:
            return self.application(environ, start)
        if not path.startswith('/api/schat/') or req.method not in {'GET','HEAD','POST','PUT','PATCH','DELETE'}:
            return reply({'error':'找不到這個頁面。'}, 404)
        header = req.headers.get('Authorization', '')
        provided = header[7:].strip() if header.startswith('Bearer ') else req.args.get('token', '')
        if not provided or not hmac.compare_digest(provided.encode(), self.phone_token.encode()):
            return reply({'error':'請先配對登入 S. Chat。'}, 401)
        if not self._same_origin(req):
            return reply({'error':'請從 S. Chat 頁面操作。'}, 403)
        # Only after phone authorization is checked can local client auth apply.
        inner = dict(environ)
        inner['REMOTE_ADDR'] = '127.0.0.1'
        inner['HTTP_AUTHORIZATION'] = 'Bearer ' + self.internal_token
        for key in ['HTTP_X_FORWARDED_FOR','HTTP_X_REAL_IP','HTTP_X_FORWARDED_HOST']:
            inner.pop(key, None)
        return self.application(inner, start)

    @staticmethod
    def _same_origin(req):
        origin = req.headers.get('Origin', '')
        return not origin or origin in {'http://' + req.host, 'https://' + req.host}

    def _limited(self, req):
        now = self.clock()
        ip = req.headers.get('Cf-Connecting-Ip', req.remote_addr or '')[:80]
        with self.lock:
            if len(self.attempts) >= 2048 and ip not in self.attempts:
                return True
            history = self.attempts.setdefault(ip, deque())
            while history and history[0] < now - 60:
                history.popleft()
            if len(history) >= 10:
                return True
            history.append(now)
            return False
