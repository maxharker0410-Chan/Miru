'use strict';
const $ = id => document.getElementById(id);
function readLocal(key) { try { return localStorage.getItem(key); } catch { return null; } }
function writeLocal(key, value) { try { localStorage.setItem(key, value); } catch { /* Private mode or full storage. */ } }
let token = new URLSearchParams(location.search).get('token') || readLocal('miru_auth_token') || '';
if (token) writeLocal('miru_auth_token', token);
if (new URLSearchParams(location.search).has('token')) {
  const clean = new URL(location.href); clean.searchParams.delete('token');
  history.replaceState(null, '', clean);
}
let story = null, session = null, stories = [], mode = 'welcome', busy = false;
let offline = false, cacheScope = '', installPrompt = null;
let speechKey = '', speechIndex = 0, speechFrames = [];
let pendingPlayer = null;
let castMarkup = '';
let characterPage = 1, scenePage = 1, catalogPage = 1;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const uid = () => 'id_' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '') : Math.random().toString(36).slice(2));
function asset(name) {
  if (!name) return '';
  if (/^https:\/\//i.test(name)) {
    try { const url = new URL(name); return url.protocol === 'https:' && !url.username && !url.password ? url.href : ''; } catch { return ''; }
  }
  return /^[a-f0-9]{32}\.(png|jpg|webp)$/.test(name)
    ? '/api/schat/assets/' + encodeURIComponent(name) + (token ? '?token=' + encodeURIComponent(token) : '') : '';
}
function notice(message) {
  $('status').textContent = message; $('status').classList.add('show'); clearTimeout(notice.timer);
  notice.timer = setTimeout(() => $('status').classList.remove('show'), 5200);
}
function forgetOffline() {
  if (!cacheScope) return;
  try { for (const key of Object.keys(localStorage)) if (key.startsWith(cacheScope)) localStorage.removeItem(key); } catch { /* Storage unavailable. */ }
}
async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (token) headers.Authorization = 'Bearer ' + token;
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api/schat' + path, {...options, headers, cache: 'no-store'});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || (response.status === 401 ? '請先登入 S. Chat' : '請稍後重試'));
    error.status = response.status;
    if (response.status === 401 || response.status === 403) forgetOffline();
    throw error;
  }
  return data;
}
function setOffline(value) {
  offline = value;
  $('connection').hidden = !value;
  $('newStory').disabled = $('welcomeCreate').disabled = $('modelBtn').disabled = value;
  $('saveBtn').disabled = $('editBtn').disabled = $('restartBtn').disabled = value || busy;
  if (story && mode === 'player') renderPlay();
}
function saveSnapshot() {
  if (!cacheScope || !story?.id) return;
  // No model configuration/API key is included in these read-only snapshots.
  writeLocal(cacheScope + 'story:' + story.id, JSON.stringify({story, session}));
  writeLocal(cacheScope + 'last', story.id);
}
function snapshot(id) {
  try { return JSON.parse(readLocal(cacheScope + 'story:' + id) || 'null'); } catch { return null; }
}
function renderList() {
  $('storyList').innerHTML = stories.map(s => `<button class="story-row ${story?.id === s.id ? 'active' : ''}" data-story="${esc(s.id)}">${esc(s.title)}<small>${s.scene_count} 個場景</small></button>`).join('') || '<span class="sub">尚未建立故事</span>';
}
async function loadList() {
  stories = (await api('/stories')).stories;
  if (cacheScope) writeLocal(cacheScope + 'list', JSON.stringify(stories));
  renderList();
}
function view(next) {
  mode = next;
  $('importBtn').disabled = offline || busy;
  $('catalogBtn').hidden = !story?.world || next !== 'player';
  $('catalogBtn').disabled = busy || !session;
  $('settingsBtn').hidden = !story?.world;
  $('settingsBtn').disabled = offline || busy;
  for (const id of ['welcome', 'editor', 'player']) $(id).classList.toggle('on', id === next);
  $('editBtn').hidden = !story || next === 'editor'; $('playBtn').hidden = !story?.id || next === 'player';
  $('restartBtn').hidden = !story?.id || next !== 'player' || !session;
  $('saveBtn').hidden = next !== 'editor'; $('deleteStory').hidden = !story?.id;
  $('historyBtn').hidden = $('visualBtn').hidden = next !== 'player';
  if (next === 'editor') $('storyDrawer').close();
  $('currentTitle').textContent = story?.title || 'S. Chat';
  $('editBtn').disabled = $('saveBtn').disabled = $('restartBtn').disabled = offline || busy;
}
const newCharacter = () => ({id: uid(), name: '', personality: '', backstory: '', avatar: '', visual_states: [], default_visual_state: ''});
function fresh() { return {title: '', premise: '', opening: '', characters: [newCharacter()], scenes: [{id: uid(), title: '', description: '', background: '', cast: [], next: []}]}; }
function edit(newStory = false) {
  if (offline || busy) return;
  if (newStory) { story = fresh(); session = null; }
  if (!story) return;
  view('editor'); $('title').value = story.title; $('premise').value = story.premise; $('opening').value = story.opening;
  resetLibrary(); renderEditor(); renderList();
}
function resetLibrary() {
  characterPage = scenePage = catalogPage = 1;
  for (const id of ['characterSearch','catalogSearch','sceneSearch','characterKind','catalogKind']) $(id).value = '';
  const regions = story?.world?.definition.regions || [];
  for (const prefix of ['character','catalog']) $(prefix + 'Region').innerHTML = '<option value="">所有地區</option>' + regions.map(r => `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('');
}
function updatePager(prefix, result) {
  $(prefix + 'PageInfo').textContent = `${result.total} 筆 · 第 ${result.page} / ${result.totalPages} 頁`;
  $(prefix + 'Prev').disabled = result.page <= 1;
  $(prefix + 'Next').disabled = result.page >= result.totalPages;
}
function worldEvent(body) {
  return story?.world ? {...body, event_id:uid(), base_revision:session?.world_state?.revision ?? 0} : body;
}
function renderCatalog() {
  const result = SChatLibrary.page(story.characters, {query:$('catalogSearch').value, kind:$('catalogKind').value, region:$('catalogRegion').value, page:catalogPage});
  catalogPage = result.page; updatePager('catalog', result);
  const state = session?.world_state;
  $('catalogList').innerHTML = result.rows.map(({item:c}) => {
    const following = state?.party_character_ids.includes(c.id), present = session?.cast.includes(c.id);
    const location = state?.characters[c.id]?.location_id;
    const region = story.world.definition.regions.find(r => r.id === c.region_id)?.name || '';
    return `<article class="catalog-card">${c.avatar ? `<img loading="lazy" src="${esc(asset(c.avatar))}" alt="${esc(c.name)}">` : ''}<h3>${esc(c.name)}</h3><p>${esc(c.id)} · ${esc(region)}<br>${following ? '同行中' : present ? '目前在場' : '不在此處'} · ${esc(story.scenes.find(s => s.id === location)?.title || '確切位置未設定')}<br>${c.search_label ? `圖片索引：${esc(c.search_label)}` : ''}</p><div class="actions">${!present ? `<button class="btn ghost small" data-world-action="arrive" data-cid="${esc(c.id)}">確認已抵達</button>` : `<button class="btn ghost small" data-world-action="${following ? 'leave' : 'join'}" data-cid="${esc(c.id)}">${following ? '結束同行' : '邀請同行'}</button><button class="btn ghost small" data-world-action="depart" data-cid="${esc(c.id)}">離開現場</button>`}</div></article>`;
  }).join('') || '<p>沒有符合搜尋的角色。</p>';
}
function renderWorldTravel() {
  $('worldTravel').hidden = !session;
  if (!session) return;
  const pending = session.world_state?.pending_travel;
  const target = pending?.location_id || session.scene_id;
  $('worldTravel').innerHTML = `<label for="worldDestination">手動選擇目的地（可選）</label><select id="worldDestination">${story.scenes.map(s => `<option value="${esc(s.id)}" ${s.id === target ? 'selected' : ''}>${esc(s.title)}</option>`).join('')}</select><button class="btn ghost" id="worldTravelConfirm" ${busy || offline ? 'disabled' : ''}>前往選定地點</button>${pending ? '<p>尚未出發。可在對話中描述前往或抵達，也可手動切換。</p>' : '<p>直接在對話中前往地點，背景與同行角色會隨劇情更新。</p>'}`;
}
async function performWorldAction(body) {
  const request = worldEvent(body);
  await mutateSession(() => api('/stories/' + story.id + '/sessions/' + session.id + '/world-action', {method:'POST', body:JSON.stringify(request)}));
}
function pictureFields(value, target, label) {
  const url = /^https:\/\//i.test(value || '') ? value : '';
  return `<div class="picture-fields"><div class="upload">${value ? `<img class="thumb" src="${esc(asset(value))}" alt="${esc(label)}預覽" referrerpolicy="no-referrer"><button type="button" class="btn ghost small" data-clear-asset="${target}">移除圖片</button>` : ''}<input class="file" aria-label="上傳${esc(label)}" type="file" accept="image/png,image/jpeg,image/webp" data-upload="${target}"></div><input type="url" aria-label="${esc(label)}圖片網址" data-asset-url="${target}" value="${esc(url)}" placeholder="或貼上 HTTPS 圖片直連網址"><small class="sub">${value && !url ? '已上傳圖片；填入網址可替換。' : '支援 PNG、JPG、WebP；角色立繪可使用透明背景。'}</small></div>`;
}
function renderVisualEditor(c, i) {
  c.visual_states ||= [];
  return `<div class="visual-editor"><div class="entry-head"><h4>狀態圖片</h4><button type="button" class="btn ghost small" data-add-visual="${i}">＋ 新增狀態</button></div><p class="sub">設定表情、服裝或劇情狀態。AI 只從這份清單選圖；未設定圖片時使用預設立繪。</p>${c.visual_states.map((v, j) => `<div class="visual-entry"><div class="entry-head"><strong>狀態 ${j + 1}</strong><button type="button" class="btn ghost small" data-remove-visual="${i}:${j}">移除狀態</button></div><div class="fields"><div class="field"><label>狀態名稱</label><input aria-label="角色 ${i + 1} 狀態 ${j + 1} 名稱" data-visual="${i}:${j}" data-visual-field="name" value="${esc(v.name)}" maxlength="60" placeholder="例如：開心、受傷、戰鬥服"></div><div class="field"><label>使用條件</label><textarea aria-label="角色 ${i + 1} 狀態 ${j + 1} 使用條件" data-visual="${i}:${j}" data-visual-field="condition" maxlength="1000" placeholder="何時使用？何時恢復？例如：受傷後持續使用，直到接受治療。">${esc(v.condition)}</textarea></div><div class="field full"><label>對應圖片</label>${pictureFields(v.image, `visuals:${i}:${j}`, `角色 ${i + 1} 狀態 ${j + 1}`)}</div></div></div>`).join('')}<div class="field"><label>故事開始時的圖片</label><select aria-label="角色 ${i + 1} 預設圖片狀態" data-default-visual="${i}"><option value="">預設立繪</option>${c.visual_states.map(v => `<option value="${esc(v.id)}" ${c.default_visual_state === v.id ? 'selected' : ''}>${esc(v.name || '未命名狀態')}</option>`).join('')}</select></div></div>`;
}
function renderEditor() {
  $('trackerEditorCard').hidden = !(story.state_tracker || []).length;
  $('trackerEditor').innerHTML = (story.state_tracker || []).map((g, i) => `<article class="entry"><h3>${esc(g.title)}</h3><div class="fields">${g.fields.map((f, j) => `<div class="field"><label>${esc(f.label)}（開場初始值）</label>${f.choices?.length ? `<select aria-label="${esc(g.title + ' ' + f.label)}" data-tracker="${i}:${j}">${f.choices.map(v => `<option ${v === f.initial ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>` : `<input aria-label="${esc(g.title + ' ' + f.label)}" data-tracker="${i}:${j}" type="${f.kind === 'number' ? 'number' : 'text'}" ${f.kind === 'number' ? `min="${f.min}" max="${f.max}" step="0.01"` : 'maxlength="160"'} value="${esc(f.initial)}">`}<small class="sub">${esc(f.note || f.unit || '')}</small></div>`).join('')}</div></article>`).join('');
  const cp = SChatLibrary.page(story.characters, {query:$('characterSearch').value, kind:$('characterKind').value, region:$('characterRegion').value, page:characterPage});
  characterPage = cp.page; updatePager('character', cp);
  const sp = SChatLibrary.page(story.scenes, {query:$('sceneSearch').value, page:scenePage});
  scenePage = sp.page; updatePager('scene', sp);
  $('addCharacter').hidden = $('addScene').hidden = !!story.world;
  $('characterEditor').innerHTML = cp.rows.map(({item:c, index:i}) => `<article class="entry"><div class="entry-head"><h3>角色 ${i + 1}</h3><button class="btn ghost" data-remove="characters:${i}" ${story.world ? 'disabled' : ''}>移除</button></div><div class="fields"><div class="field"><label>名字</label><input aria-label="角色 ${i + 1} 名字" data-kind="characters" data-i="${i}" data-field="name" value="${esc(c.name)}" placeholder="角色名稱"></div><div class="field"><label>預設立繪</label>${pictureFields(c.avatar, `characters:${i}:avatar`, `角色 ${i + 1} 預設立繪`)}</div><div class="field full"><label>個性與說話方式</label><textarea aria-label="角色 ${i + 1} 個性" data-kind="characters" data-i="${i}" data-field="personality" placeholder="性格、語氣、禁忌、關係……">${esc(c.personality)}</textarea></div><div class="field full"><label>角色背景</label><textarea aria-label="角色 ${i + 1} 背景" data-kind="characters" data-i="${i}" data-field="backstory">${esc(c.backstory)}</textarea></div></div><p class="library-meta">${esc(c.id)}${c.search_label ? ` · 圖片索引：${esc(c.search_label)}` : ''}${c.identity?.name === null ? ' · 作者姓名尚未設定' : ''}</p>${renderVisualEditor(c, i)}</article>`).join('');
  $('sceneEditor').innerHTML = sp.rows.map(({item:s, index:i}) => `<article class="entry"><div class="entry-head"><h3>場景 ${i + 1}${i === 0 ? ' · 開場' : ''}</h3><button class="btn ghost" data-remove="scenes:${i}" ${story.world ? 'disabled' : ''}>移除</button></div><div class="fields"><div class="field"><label>場景名稱</label><input aria-label="場景 ${i + 1} 名稱" data-kind="scenes" data-i="${i}" data-field="title" value="${esc(s.title)}" placeholder="例如：雨夜圖書館"></div><div class="field"><label>背景圖片</label>${pictureFields(s.background, `scenes:${i}:background`, `場景 ${i + 1} 背景`)}</div><div class="field full"><label>場景描述與劇情目標</label><textarea aria-label="場景 ${i + 1} 描述" data-kind="scenes" data-i="${i}" data-field="description">${esc(s.description)}</textarea></div><div class="field full"><label>在場角色</label><div class="checks">${(story.world ? [] : story.characters).map(c => `<label class="check"><input type="checkbox" data-members="${i}" value="${esc(c.id)}" ${s.cast.includes(c.id) ? 'checked' : ''}> ${esc(c.name || '未命名角色')}</label>`).join('')}</div></div><div class="field full"><label>允許前往的下一場景</label><div class="checks">${(story.world ? [] : story.scenes).filter(n => n.id !== s.id).map(n => `<label class="check"><input type="checkbox" data-next="${i}" value="${esc(n.id)}" ${s.next.includes(n.id) ? 'checked' : ''}> ${esc(n.title || '未命名場景')}</label>`).join('') || '<span class="sub">新增第二個場景後即可設定</span>'}</div></div></div></article>`).join('');
}
function scene() { return story.scenes.find(s => s.id === (session?.scene_id || story.start_scene || story.scenes[0].id)) || story.scenes[0]; }
function visual(c) {
  const state = session?.visuals?.[c.id] || {state_id: c.default_visual_state || '', locked: false};
  const definition = (c.visual_states || []).find(v => v.id === state.state_id);
  return {...state, label: definition?.name || '預設立繪', image: definition?.image || c.avatar};
}
const preloaded = new Map();
function preloadPicture(name) {
  const url = asset(name);
  if (!url || preloaded.has(url)) return;
  if (preloaded.size >= 64) preloaded.delete(preloaded.keys().next().value);
  const image = new Image(); image.referrerPolicy = 'no-referrer'; image.src = url; preloaded.set(url, image);
}
function setBackground(name) {
  const url = asset(name), node = $('stageBg');
  if (node.dataset.source === url) return;
  node.dataset.source = url;
  if (!url) { node.style.backgroundImage = ''; return; }
  const image = new Image(); image.referrerPolicy = 'no-referrer';
  image.onload = () => { if (node.dataset.source === url) node.style.backgroundImage = `url(${JSON.stringify(url)})`; };
  image.onerror = () => { if (node.dataset.source === url) { node.style.backgroundImage = ''; notice('背景圖片暫時無法載入，請檢查圖片網址。'); } };
  image.src = url;
}
function renderVisualControls(s, chars) {
  const available = s.cast.filter(id => (chars[id]?.visual_states || []).length);
  $('visualControls').hidden = !available.length;
  $('visualBtn').disabled = !available.length || !session;
  $('visualList').innerHTML = available.map(id => {
    const c = chars[id], v = visual(c);
    return `<div class="visual-control"><label for="visual-${esc(id)}">${esc(c.name)}</label><select id="visual-${esc(id)}" data-set-visual="${esc(id)}" ${busy || offline ? 'disabled' : ''}><option value="" ${!v.state_id ? 'selected' : ''}>預設立繪</option>${c.visual_states.map(state => `<option value="${esc(state.id)}" ${state.id === v.state_id ? 'selected' : ''}>${esc(state.name)}</option>`).join('')}</select><label class="lock"><input type="checkbox" data-lock-visual="${esc(id)}" ${v.locked ? 'checked' : ''} ${busy || offline ? 'disabled' : ''}> 固定圖片</label></div>`;
  }).join('');
}
function currentSpeech(s) {
  const messages = session?.messages || [];
  const pageSize = typeof matchMedia === 'function' && matchMedia('(max-width:640px)').matches ? 60 : 120;
  // History is capped at 200 entries, so length alone cannot identify a new turn.
  const key = `${session?.id || ''}:${s.id}:${JSON.stringify(messages)}:${s.cast.join(',')}:${pageSize}`;
  if (key !== speechKey) {
    speechKey = key; speechIndex = 0; speechFrames = [];
    let start = 0;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].speaker === 'player' || messages[i].scene_id !== s.id) { start = i + 1; break; }
    }
    for (const message of messages.slice(start)) {
      if (message.scene_id !== s.id || !s.cast.includes(message.speaker)) continue;
      const letters = Array.from(message.text || message.dialogue || '');
      // Page long replies without discarding text or splitting Unicode characters.
      while (letters.length) {
        let end = Math.min(pageSize, letters.length);
        if (end < letters.length) {
          for (let i = end - 1; i >= Math.floor(pageSize / 2); i--) if (/[。！？!?\n]/.test(letters[i])) { end = i + 1; break; }
        }
        speechFrames.push({speaker: message.speaker, text: letters.splice(0, end).join('')});
      }
    }
  }
  speechIndex = Math.min(speechIndex, Math.max(0, speechFrames.length - 1));
  return speechFrames[speechIndex];
}
function currentPlayer(s) {
  if (pendingPlayer?.sessionId === session?.id) return pendingPlayer;
  const message = [...(session?.messages || [])].reverse().find(m => m.speaker === 'player');
  return message ? {text: message.text, state: 'sent'} : null;
}
function renderTracker(s) {
  const groups = story.state_tracker || [];
  $('trackerPanel').hidden = !groups.length;
  const events = session?.tracker_events || [];
  $('trackerList').innerHTML = groups.map(g => `<article class="tracker-group"><h3>${esc(g.title)}${g.character_name ? `<small>${g.character_id && s.cast.includes(g.character_id) ? '在場' : '不在此處 · 數值保留'}</small>` : ''}</h3>${g.fields.map(f => {
    const key = g.id + '.' + f.id, value = session?.tracker?.[key] ?? f.initial;
    const event = [...events].reverse().find(e => e.key === key);
    const suffix = f.kind === 'number' ? f.unit === '單位' ? ` / ${f.max} 單位` : f.unit : '';
    return `<div class="tracker-field"><div><span>${esc(f.label)}</span><strong>${esc(value)}${esc(suffix)}</strong></div>${f.kind === 'number' ? `<meter min="${f.min}" max="${f.max}" value="${esc(value)}" aria-label="${esc(g.title + ' ' + f.label)}">${esc(value)}</meter>` : ''}${event ? `<small class="tracker-reason">${esc(event.reason)}</small>` : ''}</div>`;
  }).join('')}</article>`).join('');
  $('trackerHint').textContent = session ? '依劇情更新；未發生變化的項目會保留。' : '以下為你設定的開場初始值。';
}
function positionSpeech() {
  const stageNode = $('stage'), cast = $('castStage'), caption = $('playerCaption');
  const stageBounds = stageNode.getBoundingClientRect();
  const actors = [...cast.querySelectorAll('.actor')], foreground = cast.querySelector('.actor.active');
  const mobile = stageBounds.width <= 640;
  const captionHeight = caption.hidden ? 0 : caption.getBoundingClientRect().height + 12;
  const topNode = $('speechBubble').hidden ? $('stageNote') : $('speechBubble');
  const topBottom = topNode.hidden ? 90 : topNode.getBoundingClientRect().bottom - stageBounds.top;
  const bottom = captionHeight + 24;
  // Give the speaking portrait its own space instead of dividing a row among everyone.
  // Grow the scene for long dialogue; never shrink the portrait to fit under a bubble.
  const height = actors.length ? (mobile ? Math.max(320, Math.min(400, innerHeight * .44)) : Math.max(380, Math.min(500, innerHeight * .52))) : 100;
  stageNode.style.minHeight = `${Math.ceil(Math.max(mobile ? 560 : 620, topBottom + 28 + height + bottom))}px`;
  cast.style.bottom = `${bottom}px`;
  cast.style.height = `${height}px`;
  const others = actors.filter(actor => actor !== foreground);
  others.forEach((actor, index) => {
    const pair = Math.floor(index / 2), side = index % 2;
    const inset = Math.min(35, 13 + pair * 8);
    actor.style.setProperty('--actor-x', `${foreground ? (side ? 100 - inset : inset) : (index + 1) * 100 / (others.length + 1)}%`);
    actor.style.setProperty('--actor-rise', `${foreground ? 36 + pair * 18 : 0}px`);
    actor.style.setProperty('--actor-depth', `${Math.max(1, 5 - pair)}`);
    actor.style.setProperty('--ensemble-width', `${Math.min(45, 90 / Math.max(1, others.length))}%`);
  });
  const bubble = $('speechBubble');
  if (bubble.hidden || !foreground) return;
  const stage = $('stage').getBoundingClientRect();
  const target = stage.width / 2;
  const half = bubble.getBoundingClientRect().width / 2;
  const center = Math.max(half + 18, Math.min(stage.width - half - 18, target));
  bubble.style.left = `${center}px`;
  bubble.style.setProperty('--pointer-x', `${target - center + half - 14}px`);
}
function renderPlay() {
  if (!story) return;
  $('restartBtn').hidden = !session;
  const configuredScene = scene(), chars = Object.fromEntries(story.characters.map(c => [c.id, c]));
  const s = {...configuredScene, cast: (Array.isArray(session?.cast) ? session.cast : configuredScene.cast).filter(id => chars[id])};
  const changedCast = s.cast.length !== configuredScene.cast.length || s.cast.some(id => !configuredScene.cast.includes(id));
  $('playTitle').textContent = '當下狀態'; $('sceneTitle').textContent = s.title;
  $('sceneDescription').textContent = session?.situation || (changedCast ? (s.cast.length ? '目前在場：' + s.cast.map(id => chars[id].name).join('、') : '你目前獨自在這裡。') : s.description);
  setBackground(s.background);
  $('playSub').textContent = `${story.scenes.findIndex(n => n.id === s.id) + 1} / ${story.scenes.length} · ${s.cast.length} 名角色在場`;
  const pending = pendingPlayer?.sessionId === session?.id && pendingPlayer;
  const waiting = pending?.state === 'sending';
  const speech = pending ? null : currentSpeech(s), active = speech?.speaker;
  $('speechBubble').hidden = !speech;
  $('bubbleSpeaker').textContent = chars[active]?.name || '';
  $('bubbleText').textContent = speech?.text || '';
  $('bubbleCounter').textContent = speechFrames.length > 1 ? `${speechIndex + 1} / ${speechFrames.length}` : '';
  $('bubbleNav').hidden = speechFrames.length <= 1;
  $('prevSpeech').disabled = speechIndex === 0;
  $('nextSpeech').disabled = speechIndex >= speechFrames.length - 1;
  $('stageNote').hidden = !!speech;
  const lastNarration = [...(session?.messages || [])].reverse().find(m => m.scene_id === s.id && m.speaker === 'narrator');
  $('stageNote').textContent = !session ? '故事準備好了，按下「開始故事」進入這個世界。' : lastNarration?.text || (!s.cast.length ? '目前沒有角色在場。' : '等待角色的下一段對話。');
  if (waiting) $('stageNote').textContent = '角色正在回應你…';
  if (pending?.state === 'failed') $('stageNote').textContent = '這次回覆未完成，故事進度與數值未變更。請重試。';
  const player = currentPlayer(s);
  $('playerCaption').hidden = !player;
  $('playerText').textContent = player?.text || '';
  $('playerDelivery').textContent = player?.state === 'sending' ? '已送出 · 等待回覆' : player?.state === 'failed' ? '未送成功 · 文字已回填，請重試' : '你';
  renderTracker(s);
  const markup = s.cast.map(id => {
    const c = chars[id], v = visual(c), src = asset(v.image);
    return `<div class="actor" data-actor="${esc(id)}">${src ? `<img src="${esc(src)}" data-actor-image="${esc(id)}" data-fallback="${esc(asset(c.avatar))}" alt="${esc(c.name)}・${esc(v.label)}" referrerpolicy="no-referrer">` : `<div class="silhouette">${esc(c.name.slice(0, 1))}</div>`}<b title="${esc(c.name)}">${esc(c.name)}</b>${(c.visual_states || []).length ? `<small class="actor-state">${esc(v.label)}${v.locked ? ' · 固定' : ''}</small>` : ''}</div>`;
  }).join('') || '<p class="sub">目前沒有角色在場</p>';
  if (markup !== castMarkup) { $('castStage').innerHTML = markup; castMarkup = markup; }
  $('castStage').classList.toggle('has-speaker', !!active);
  for (const actor of $('castStage').querySelectorAll('.actor')) actor.classList.toggle('active', actor.dataset.actor === active);
  $('characterStatusList').innerHTML = s.cast.map(id => {
    const c = chars[id], v = visual(c);
    const status = session?.statuses?.[id] || (!session ? '故事尚未開始。' : v.state_id ? v.label : '尚未提供當下狀態。');
    const tags = [active === id ? '正在發言' : '', (c.visual_states || []).length ? v.label : '', v.locked ? '圖片固定' : ''].filter(Boolean);
    return `<article class="state-actor"><strong>${esc(c.name)}</strong><p>${esc(status)}</p><div class="state-tags">${tags.map(tag => `<span class="state-tag">${esc(tag)}</span>`).join('')}</div></article>`;
  }).join('') || '<p class="sub">目前沒有角色在場。</p>';
  $('log').innerHTML = session ? session.messages.map(m => `<div class="line ${m.speaker === 'player' ? 'player' : m.speaker === 'narrator' ? 'narrator' : ''}"><b>${esc(chars[m.speaker]?.name || ({player:'你', narrator:'旁白'}[m.speaker] || m.speaker))}</b><p>${esc(m.text)}</p></div>`).join('') : '<div class="line narrator"><p>故事準備好了。按下「開始故事」，進入這個世界。</p></div>';
  $('log').scrollTop = $('log').scrollHeight;
  if (story.world) { $('nextScenes').innerHTML = session ? '' : `<button class="btn primary" id="startStory" ${busy || offline ? 'disabled' : ''}>開始故事</button>`; renderWorldTravel(); }
  else { $('worldTravel').hidden = true;
  $('nextScenes').innerHTML = session ? s.next.map(id => `<button class="btn ghost" data-advance="${esc(id)}" ${busy || offline ? 'disabled' : ''}>前往 ${esc(story.scenes.find(n => n.id === id)?.title || id)} ↗</button>`).join('') : `<button class="btn primary" id="startStory" ${busy || offline ? 'disabled' : ''}>開始故事</button>`;
  }
  $('chatInput').disabled = $('sendBtn').disabled = !session || busy || offline;
  $('chatInput').placeholder = offline ? '離線閱讀中；連線後可繼續對話' : '你會怎麼說、怎麼做？';
  $('memoryList').innerHTML = session ? story.characters.map(c => `<p><strong>${esc(c.name)}</strong></p><ul>${(session.memories[c.id] || []).map(m => `<li>${esc(m)}</li>`).join('') || '<li>尚無個人記憶</li>'}</ul>`).join('') : '<p>開始故事後，角色才會記住經歷。</p>';
  renderVisualControls(s, chars);
  requestAnimationFrame(positionSpeech);
  if (!offline) {
    for (const id of s.cast) { const c = chars[id]; preloadPicture(visual(c).image); preloadPicture(c.avatar); for (const v of (c.visual_states || []).slice(0, 4)) preloadPicture(v.image); }
  }
}
document.addEventListener('error', e => {
  const image = e.target;
  if (!(image instanceof HTMLImageElement)) return;
  if (image.dataset.actorImage) {
    const fallback = image.dataset.fallback; delete image.dataset.fallback;
    if (fallback && fallback !== image.getAttribute('src')) { image.src = fallback; return; }
    const c = story?.characters.find(c => c.id === image.dataset.actorImage);
    const placeholder = document.createElement('div'); placeholder.className = 'silhouette'; placeholder.textContent = c?.name.slice(0, 1) || '?'; image.replaceWith(placeholder);
  } else if (image.classList.contains('thumb')) { image.hidden = true; }
}, true);
async function openStory(id) {
  if (busy) return;
  if (offline) {
    const saved = snapshot(id);
    if (!saved) { notice('這個故事尚未保存供離線閱讀。'); return; }
    story = saved.story; session = saved.session;
  } else {
    story = await api('/stories/' + encodeURIComponent(id)); session = null;
    const recent = (await api('/stories/' + id + '/sessions')).sessions;
    if (recent.length) session = await api('/stories/' + id + '/sessions/' + recent[0].id);
    saveSnapshot();
  }
  resetLibrary(); view('player'); renderPlay(); renderList();
  $('storyDrawer').close();
}
async function save() {
  if (busy || offline) return;
  story.title = $('title').value; story.premise = $('premise').value; story.opening = $('opening').value;
  for (const s of story.scenes) { s.cast = s.cast.filter(id => story.characters.some(c => c.id === id)); s.next = s.next.filter(id => story.scenes.some(n => n.id === id && id !== s.id)); }
  if (story.scenes.length === 1 && !story.scenes[0].cast.length) story.scenes[0].cast = [story.characters[0].id];
  story.start_scene = story.start_scene || story.scenes[0].id;
  try {
    story = await api(story.id ? '/stories/' + story.id : '/stories', {method: story.id ? 'PUT' : 'POST', body: JSON.stringify(story)});
    if (session) session = await api('/stories/' + story.id + '/sessions/' + session.id);
    saveSnapshot(); notice('故事已儲存'); await loadList(); view('player'); renderPlay();
  } catch (e) { notice(e.message); }
}
function setAsset(target, value) {
  const [kind, index, field] = target.split(':');
  if (kind === 'visuals') story.characters[+index].visual_states[+field].image = value;
  else story[kind][+index][field] = value;
}
async function upload(target, file) {
  if (!file || offline) return;
  const body = new FormData(); body.append('image', file);
  const [kind, index, field] = target.split(':'), originalStory = story;
  const item = kind === 'visuals' ? story.characters[+index].visual_states[+field] : story[kind][+index];
  try {
    const res = await api('/assets', {method:'POST', body});
    item[kind === 'visuals' ? 'image' : field] = res.file;
    if (story === originalStory && mode === 'editor') renderEditor();
    notice('圖片已加入；請儲存故事。');
  } catch (e) { notice(e.message); }
}
async function mutateSession(action) {
  if (!story?.id || offline || busy) return;
  busy = true; view(mode); renderPlay();
  try { session = await action(); saveSnapshot(); } catch (e) { notice(e.message); }
  finally { busy = false; view(mode); renderPlay(); if ($('catalogDialog').open) renderCatalog(); }
}
async function updateVisual(cid, stateId, locked) {
  if (!session) return;
  await mutateSession(() => api('/stories/' + story.id + '/sessions/' + session.id + '/visuals', {method:'PATCH', body:JSON.stringify({character_id:cid, state_id:stateId, locked})}));
}
document.addEventListener('input', e => {
  const d = e.target.dataset;
  if (d.kind && d.field) story[d.kind][+d.i][d.field] = e.target.value;
  if (d.visual && d.visualField) { const [i, j] = d.visual.split(':'); story.characters[+i].visual_states[+j][d.visualField] = e.target.value; }
  if (d.tracker) { const [i, j] = d.tracker.split(':'); const f = story.state_tracker[+i].fields[+j]; f.initial = f.kind === 'number' ? e.target.value === '' ? null : Number(e.target.value) : e.target.value; }
});
document.addEventListener('change', e => {
  const d = e.target.dataset;
  if (d.tracker) { const [i, j] = d.tracker.split(':'); const f = story.state_tracker[+i].fields[+j]; f.initial = f.kind === 'number' ? e.target.value === '' ? null : Number(e.target.value) : e.target.value; }
  if (d.members !== undefined) { const s = story.scenes[+d.members]; s.cast = e.target.checked ? [...new Set([...s.cast, e.target.value])] : s.cast.filter(x => x !== e.target.value); }
  if (d.next !== undefined) { const s = story.scenes[+d.next]; s.next = e.target.checked ? [...new Set([...s.next, e.target.value])] : s.next.filter(x => x !== e.target.value); }
  if (d.upload) upload(d.upload, e.target.files?.[0]);
  if (d.assetUrl) { setAsset(d.assetUrl, e.target.value.trim()); renderEditor(); }
  if (d.defaultVisual !== undefined) story.characters[+d.defaultVisual].default_visual_state = e.target.value;
  if (d.setVisual) updateVisual(d.setVisual, e.target.value, true);
  if (d.lockVisual) updateVisual(d.lockVisual, visual(story.characters.find(c => c.id === d.lockVisual)).state_id, e.target.checked);
});
document.addEventListener('click', async e => {
  const d = e.target.closest('button')?.dataset || {};
  try {
    if (d.story) await openStory(d.story);
    if (offline || busy) return;
    if (d.remove) {
      if (story.world) return notice('世界角色與地點的 ID 需保留；本局進出與同行請使用角色名冊。');
      const [kind, i] = d.remove.split(':');
      if (story[kind].length <= 1) { notice('至少保留一名角色和一個場景'); return; }
      const [removed] = story[kind].splice(+i, 1);
      if (kind === 'characters') story.scenes.forEach(s => s.cast = s.cast.filter(id => id !== removed.id));
      else { story.scenes.forEach(s => s.next = s.next.filter(id => id !== removed.id)); if (story.start_scene === removed.id) story.start_scene = story.scenes[0].id; }
      renderEditor();
    }
    if (d.addVisual !== undefined) {
      const c = story.characters[+d.addVisual];
      if (c.visual_states.length >= 32) { notice('每名角色最多設定 32 個圖片狀態'); return; }
      c.visual_states.push({id:uid(), name:'', condition:'', image:''}); renderEditor();
    }
    if (d.removeVisual) { const [i, j] = d.removeVisual.split(':'); const c = story.characters[+i], [removed] = c.visual_states.splice(+j, 1); if (c.default_visual_state === removed.id) c.default_visual_state = ''; renderEditor(); }
    if (d.clearAsset) { setAsset(d.clearAsset, ''); renderEditor(); }
    if (d.advance) await mutateSession(() => api('/stories/' + story.id + '/sessions/' + session.id + '/advance', {method:'POST', body:JSON.stringify({scene_id:d.advance})}));
    if (e.target.id === 'startStory') await mutateSession(() => api('/stories/' + story.id + '/sessions', {method:'POST'}));
  } catch (err) { notice(err.message); }
});
$('newStory').onclick = $('welcomeCreate').onclick = () => edit(true);
$('drawerBtn').onclick = () => $('storyDrawer').showModal();
$('drawerClose').onclick = () => $('storyDrawer').close();
$('historyBtn').onclick = () => { $('historyDialog').showModal(); $('log').scrollTop = $('log').scrollHeight; };
$('historyClose').onclick = () => $('historyDialog').close();
$('visualBtn').onclick = () => $('visualDialog').showModal();
$('visualClose').onclick = () => $('visualDialog').close();
$('prevSpeech').onclick = () => { speechIndex = Math.max(0, speechIndex - 1); renderPlay(); };
$('nextSpeech').onclick = () => { speechIndex = Math.min(speechFrames.length - 1, speechIndex + 1); renderPlay(); };
$('editBtn').onclick = () => edit(); $('playBtn').onclick = () => { view('player'); renderPlay(); };
$('saveBtn').onclick = save;
$('addCharacter').onclick = () => { if (story.characters.length >= 12) return notice('最多建立 12 名角色'); story.characters.push(newCharacter()); renderEditor(); };
$('addScene').onclick = () => { if (story.scenes.length >= 30) return notice('最多建立 30 個場景'); story.scenes.push({id:uid(), title:'', description:'', background:'', cast:[story.characters[0].id], next:[]}); renderEditor(); };
$('deleteStory').onclick = async () => {
  if (!story?.id || !confirm('確定刪除這個故事？')) return;
  try { await api('/stories/' + story.id, {method:'DELETE'}); if (cacheScope) localStorage.removeItem(cacheScope + 'story:' + story.id); story = null; session = null; view('welcome'); await loadList(); } catch (e) { notice(e.message); }
};
$('modelBtn').onclick = async () => {
  try {
    const cfg = await api('/model'); $('modelHost').value = cfg.host || ''; $('modelId').value = cfg.model || ''; $('modelKey').value = '';
    $('modelHint').textContent = cfg.source === 'existing' && cfg.configured ? '目前使用原有的聊天模型；另存設定後，故事模式將使用這組模型。' : '故事導演與角色共用這組模型。API Key 儲存在服務端的使用者資料中，不加入離線快取。';
    $('modelDialog').showModal();
  } catch (e) { notice(e.message); }
};
$('modelCancel').onclick = () => $('modelDialog').close();
$('modelForm').onsubmit = async e => {
  e.preventDefault();
  try { await api('/model', {method:'PUT', body:JSON.stringify({host:$('modelHost').value, model:$('modelId').value, api_key:$('modelKey').value})}); $('modelKey').value = ''; $('modelDialog').close(); notice('聊天模型已儲存'); } catch (err) { notice(err.message); }
};
$('restartBtn').onclick = async () => { if (story?.id && confirm('重新開始會建立新的遊玩紀錄；確定嗎？')) await mutateSession(() => api('/stories/' + story.id + '/sessions', {method:'POST'})); };
$('chatForm').onsubmit = async e => {
  e.preventDefault(); if (!session || busy || offline) return;
  const text = $('chatInput').value.trim(); if (!text) return;
  const previous = pendingPlayer?.sessionId === session.id && pendingPlayer.text === text ? pendingPlayer : null;
  pendingPlayer = {sessionId: session.id, text, state:'sending', request:previous?.request || worldEvent({text})};
  let completed = false;
  busy = true; $('chatInput').blur(); $('chatInput').value = ''; $('sendBtn').textContent = '故事推進中…'; view(mode); renderPlay();
  try { session = await api('/stories/' + story.id + '/sessions/' + session.id + '/turn', {method:'POST', body:JSON.stringify(pendingPlayer.request)}); pendingPlayer = null; completed = true; saveSnapshot(); }
  catch (err) {
    if (story.world) { try { session = await api('/stories/' + story.id + '/sessions/' + session.id); if (session.world_state.accepted_event_ids.includes(pendingPlayer.request.event_id)) { pendingPlayer = null; completed = true; saveSnapshot(); } else if (err.status === 409) pendingPlayer.request.base_revision = session.world_state.revision; } catch { /* Keep the same request ID for a retry. */ } }
    if (pendingPlayer) { pendingPlayer.state = 'failed'; $('chatInput').value = text; notice(err.message); }
  }
  finally {
    busy = false; $('sendBtn').textContent = '送出'; view(mode); renderPlay();
    if (completed) requestAnimationFrame(() => {
      const response = $('speechBubble').hidden ? $('stageNote') : $('speechBubble');
      response.scrollIntoView({block:'start', behavior:matchMedia('(prefers-reduced-motion:reduce)').matches ? 'auto' : 'smooth'});
    });
  }
};
$('reloadBtn').onclick = () => location.reload();
$('signOutBtn').onclick = () => {
  if (busy || !confirm('切換帳號會清除此裝置保存的離線閱讀資料，服務端故事仍會保留。')) return;
  forgetOffline(); try { localStorage.removeItem('miru_auth_token'); } catch { /* Storage unavailable. */ }
  token = ''; location.href = '/login?next=s-chat';
};
window.addEventListener('offline', () => setOffline(true));
window.addEventListener('resize', () => { if (mode === 'player') renderPlay(); });
window.addEventListener('online', () => notice('網路已恢復，按「重新連線」取得最新紀錄。'));
window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); installPrompt = e; });
$('installBtn').onclick = async () => {
  if (installPrompt) { await installPrompt.prompt(); installPrompt = null; }
  else notice('手機瀏覽器選單可選「安裝應用程式」；iPhone 請在 Safari 分享選單選「加入主畫面」。');
};
window.addEventListener('appinstalled', () => $('installBtn').hidden = true);
async function initialize() {
  if (token && crypto.subtle) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token));
    cacheScope = 'schat-offline:' + Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, '0')).join('') + ':';
  }
  $('installBtn').hidden = matchMedia('(display-mode: standalone)').matches;
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/s-chat/service-worker.js', {scope:'/s-chat'}).catch(() => notice('離線閱讀尚未啟用；連線時仍可正常遊玩。'));
  }
  try {
    await api('/account'); await loadList();
    const last = cacheScope && readLocal(cacheScope + 'last');
    if (last && stories.some(s => s.id === last)) await openStory(last);
  } catch (e) {
    if (e.status === 401 || e.status === 403) { notice('請先登入 S. Chat，再開啟故事。'); $('loginLink').hidden = false; return; }
    setOffline(true);
    try { stories = JSON.parse(readLocal(cacheScope + 'list') || '[]'); } catch { stories = []; }
    renderList(); const last = cacheScope && readLocal(cacheScope + 'last');
    if (last) await openStory(last);
    notice('目前為離線閱讀；新對話與編輯需要連線。');
  }
}

$('importBtn').onclick = () => { if (!busy && !offline) { $('importStatus').textContent = ''; $('importDialog').showModal(); } };
$('importCancel').onclick = () => { if (!busy) $('importDialog').close(); };
$('importDialog').addEventListener('cancel', e => { if (busy) e.preventDefault(); });
$('importForm').onsubmit = async e => {
  e.preventDefault(); if (busy || offline) return;
  const world = $('worldZip').files[0], images = $('imagesZip').files[0];
  if (!world || !images) return notice('請選擇兩份 ZIP。');
  if (world.size + images.size > 512 * 1024 * 1024) return notice('兩份 ZIP 合計請小於 512 MB。');
  const body = new FormData(); body.append('world_zip', world); body.append('images_zip', images);
  busy = true; view(mode); $('importSubmit').disabled = $('importCancel').disabled = true;
  $('importStatus').textContent = '匯入中：正在核對世界資料與 195 張圖片，請稍候…';
  try {
    const result = await api('/world-import', {method:'POST', body});
    busy = false; await loadList(); await openStory(result.story.id); $('importDialog').close();
    notice(result.already_imported ? '此世界已匯入，沿用原有紀錄。' : '已匯入 153 名角色與 195 張圖片。');
  } catch (error) { $('importStatus').textContent = error.message; }
  finally { busy = false; $('importSubmit').disabled = $('importCancel').disabled = false; view(mode); }
};
$('catalogBtn').onclick = () => { resetLibrary(); renderCatalog(); $('catalogDialog').showModal(); };
$('catalogClose').onclick = () => $('catalogDialog').close();
$('settingsBtn').onclick = () => { if (!busy && !offline) { $('settingsStatus').textContent = ''; $('settingsDialog').showModal(); } };
$('settingsCancel').onclick = () => { if (!busy) $('settingsDialog').close(); };
$('settingsDialog').addEventListener('cancel', e => { if (busy) e.preventDefault(); });
$('settingsForm').onsubmit = async e => {
  e.preventDefault(); if (busy || offline || !story?.world) return;
  const file = $('settingsDocx').files[0];
  if (!file) return notice('請選擇完整的 Word 設定書。');
  if (file.size > 16 * 1024 * 1024) return notice('設定書請小於 16 MB。');
  const body = new FormData(); body.append('world_document', file);
  body.append('base_settings_revision', story.world.author_settings?.revision || 0);
  busy = true; view(mode); $('settingsSubmit').disabled = $('settingsCancel').disabled = true;
  $('settingsStatus').textContent = '正在核對七區角色與地點；記憶、圖片及存檔會保留…';
  try {
    const result = await api('/stories/' + story.id + '/world-settings', {method:'POST', body});
    story = result.story;
    if (session) session = await api('/stories/' + story.id + '/sessions/' + session.id);
    resetLibrary(); saveSnapshot(); await loadList();
    if (mode === 'editor') renderEditor(); else if (mode === 'player') renderPlay();
    $('settingsDialog').close(); notice(result.already_applied ? '已使用這份設定書，進度保留。' : '設定書已更新；153 名角色、圖片與存檔保留。');
  } catch (error) { $('settingsStatus').textContent = error.message; }
  finally { busy = false; $('settingsSubmit').disabled = $('settingsCancel').disabled = false; view(mode); if (mode === 'player') renderPlay(); }
};
for (const prefix of ['character','catalog']) {
  for (const suffix of ['Search','Kind','Region']) $(prefix + suffix).addEventListener(suffix === 'Search' ? 'input' : 'change', () => {
    if (prefix === 'character') characterPage = 1; else catalogPage = 1;
    if (prefix === 'character') renderEditor(); else renderCatalog();
  });
  for (const [suffix,delta] of [['Prev',-1],['Next',1]]) $(prefix + suffix).onclick = () => {
    if (prefix === 'character') { characterPage += delta; renderEditor(); } else { catalogPage += delta; renderCatalog(); }
  };
}
$('sceneSearch').oninput = () => { scenePage = 1; renderEditor(); };
$('scenePrev').onclick = () => { scenePage--; renderEditor(); };
$('sceneNext').onclick = () => { scenePage++; renderEditor(); };
document.addEventListener('click', async e => {
  const d = e.target.closest('button')?.dataset || {};
  if (!session || !story?.world || busy || offline) return;
  if (d.worldAction) {
    const character = story.characters.find(c => c.id === d.cid);
    await performWorldAction({action:d.worldAction, character_id:d.cid});
  }
  if (e.target.id === 'worldTravelConfirm') {
    const target = $('worldDestination').value, location = story.scenes.find(s => s.id === target);
    if (target !== session.scene_id) await performWorldAction({action:'travel', location_id:target});
    else notice('目前就在這個地點，對話與在場角色已保留。');
  }
});

initialize().catch(e => notice(e.message));
