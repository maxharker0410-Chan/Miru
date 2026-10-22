'use strict';
const message = document.getElementById('message');
const stored = localStorage.getItem('miru_auth_token') || '';
function enter(token, server = '') {
  localStorage.setItem('miru_auth_token', token);
  location.replace((server || '') + '/s-chat?token=' + encodeURIComponent(token));
}
async function request(path, body) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body), cache:'no-store'});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '登入失敗');
  return value;
}
document.getElementById('loginForm').onsubmit = async event => {
  event.preventDefault();
  const button = document.getElementById('loginButton'); button.disabled = true;
  try { const value = await request('/api/auth/login', {code:document.getElementById('code').value.trim()}); enter(value.token, value.server_url); }
  catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
};
document.getElementById('localButton').onclick = async () => {
  try { const value = await request('/api/client/local/start', {}); enter(value.token); }
  catch (error) { message.textContent = error.message; }
};
(async () => {
  try {
    const config = await (await fetch('/api/client-config', {cache:'no-store'})).json();
    document.getElementById('localButton').hidden = !config.client_mode;
    if (config.auth_token && config.setup_complete) return enter(config.auth_token);
    if (stored) {
      const check = await fetch('/api/auth/me', {headers:{Authorization:'Bearer ' + stored}, cache:'no-store'});
      if (check.ok) enter(stored);
    }
  } catch { message.textContent = '請確認 S.Chat 服務已啟動。'; }
})();
