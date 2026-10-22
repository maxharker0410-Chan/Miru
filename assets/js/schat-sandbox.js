'use strict';
function allCharacters() {
  return [...(session?.render_definition?.characters || story?.characters || []), ...(session?.sandbox?.dynamic_characters || [])]
    .filter((c, index, values) => values.findIndex(v => v.id === c.id) === index)
    .map(c => ({...c, avatar:session?.sandbox?.character_art?.[c.id] || c.avatar}));
}
function renderSandboxStatus() {
  const state = session?.sandbox;
  const elapsed = state?.elapsed_seconds || 0;
  $('worldClock').textContent = state ? `第 ${1 + Math.floor(elapsed / 86400)} 天 · ${String(Math.floor(elapsed / 3600) % 24).padStart(2,'0')}:${String(Math.floor(elapsed / 60) % 60).padStart(2,'0')} · ${state.run_status === 'dead' ? '故事結束，請讀檔或重開' : state.run_status === 'paused' ? '暫停中' : state.await_player ? '等待你的決定' : '故事進行中'}` : '';
  $('pauseBtn').textContent = state?.run_status === 'paused' ? '繼續遊玩' : '暫停';
  for (const id of ['savesBtn','pauseBtn','panelBtn']) $(id).disabled = !session || busy || offline;
  $('continueBtn').disabled = !session || busy || offline || state?.run_status !== 'playing';
}
function addSecretRow() {
  const row = document.createElement('div'); row.className = 'entry secret-row';
  row.innerHTML = `<div class="field"><label>秘密內容<textarea data-secret-text maxlength="1000"></textarea></label><label>哪些人一開始就知道<select data-secret-audience multiple aria-label="秘密知情者">${(story?.characters || []).map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select></label><label><input type="checkbox" data-secret-public>所有人都知道（公開）</label></div><button type="button" class="btn ghost" data-remove-secret>移除這項</button>`;
  row.querySelector('[data-remove-secret]').onclick = () => row.remove();
  $('secretRows').append(row);
}
function openOpening() {
  if (!story?.id || busy || offline) return notice('請先選擇或儲存故事。');
  $('openingForm').reset(); $('secretRows').replaceChildren(); $('openingDialog').showModal();
}
$('openingBtn').onclick = openOpening;
$('openingClose').onclick = () => $('openingDialog').close();
$('addSecret').onclick = addSecretRow;
$('openingForm').onsubmit = async event => {
  event.preventDefault();
  const secrets = [...$('secretRows').children].filter(row => row.querySelector('[data-secret-text]').value.trim()).map(row => ({text:row.querySelector('[data-secret-text]').value.trim(), audience:row.querySelector('[data-secret-public]').checked ? 'public' : [...row.querySelector('[data-secret-audience]').selectedOptions].map(option => option.value)}));
  const player_profile = {name:$('playerName').value, background:$('playerBackground').value, abilities:$('playerAbilities').value, opening_event:$('playerOpening').value, secrets};
  $('openingDialog').close();
  await mutateSession(() => api('/stories/' + story.id + '/sessions', {method:'POST', body:JSON.stringify({player_profile})}));
};
$('continueBtn').onclick = () => {
  if (busy || !session) return;
  $('chatInput').value = '繼續'; $('chatForm').requestSubmit();
};
$('pauseBtn').onclick = async () => {
  if (!session || busy) return;
  const request = worldEvent({text:session.sandbox?.run_status === 'paused' ? '/resume' : '/pause'});
  await mutateSession(() => api('/stories/' + story.id + '/sessions/' + session.id + '/turn', {method:'POST', body:JSON.stringify(request)}));
};
let availableSlots = [];
async function refreshSlots() {
  availableSlots = (await api('/stories/' + story.id + '/saves')).slots;
  const current = $('saveSlot').value;
  $('saveSlot').innerHTML = Array.from({length:8}, (_, i) => {
    const id = 'slot_' + (i + 1), saved = availableSlots.find(s => s.slot === id);
    return `<option value="${id}">${i + 1} · ${saved ? esc(saved.label) : '空白欄位'}</option>`;
  }).join('');
  if (current) $('saveSlot').value = current;
}
$('savesBtn').onclick = async () => {
  if (!session || busy) return;
  try { await refreshSlots(); $('saveStatus').textContent = ''; $('saveLabel').value = ''; $('savesDialog').showModal(); }
  catch (error) { notice(error.message); }
};
$('savesClose').onclick = () => $('savesDialog').close();
$('writeSlot').onclick = async () => {
  try {
    await api('/stories/' + story.id + '/saves', {method:'POST', body:JSON.stringify({session_id:session.id, slot:$('saveSlot').value, label:$('saveLabel').value})});
    await refreshSlots(); $('saveStatus').textContent = '已保存此時點的世界、記憶、事件與物品。';
  } catch (error) { $('saveStatus').textContent = error.message; }
};
$('readSlot').onclick = async () => {
  if (!availableSlots.some(slot => slot.slot === $('saveSlot').value)) { $('saveStatus').textContent = '這個欄位還沒有存檔。'; return; }
  $('savesDialog').close();
  await mutateSession(() => api('/stories/' + story.id + '/saves/' + $('saveSlot').value + '/load', {method:'POST', body:'{}'}));
};
function renderPlayerPanel(kind = 'map') {
  const panels = session?.panels || {};
  const content = $('panelContent');
  if (kind === 'map') content.innerHTML = (panels.map || []).map(place => `<article class="entry"><strong>${esc(place.title)}</strong> ${place.current ? '· 目前位置' : `<button class="btn ghost small" data-panel-travel="${esc(place.id)}">前往</button>`}</article>`).join('');
  if (kind === 'inventory') content.innerHTML = (panels.inventory || []).map(item => `<p>${esc(item.name)} × ${item.quantity}</p>`).join('') || '<p>目前沒有已確認的物品。</p>';
  if (kind === 'events') content.innerHTML = (panels.events || []).map(item => `<article class="entry"><strong>${esc(item.intent)}</strong><p>${esc(({executing:'進行中', awaiting_result:'等待處理', resolved:'已結算'})[item.phase] || item.phase)}</p>${item.result_text ? `<p>${esc(item.result_text)}</p>` : ''}</article>`).join('') + (panels.journal || []).map(item => `<p>${esc(item.text)}</p>`).join('') || '<p>目前沒有玩家已知的事件。</p>';
  if (kind === 'people') content.innerHTML = (panels.people || []).map(person => `<article class="entry"><strong>${esc(person.name)}</strong><p>${person.alive ? person.present ? '目前在場' : '曾經接觸' : '已死亡'}</p><label>補充此角色圖片<input type="file" data-person-art="${esc(person.id)}" accept="image/png,image/jpeg,image/webp"></label></article>`).join('') + (panels.knowledge || []).map(item => `<p>${esc(({known:'已知', suspected:'懷疑', rumor:'傳言', false_belief:'目前認知'})[item.certainty])}：${esc(item.text)}</p>`).join('') || '<p>尚未認識任何人。</p>';
}
$('panelBtn').onclick = () => { if (session) { renderPlayerPanel(); $('panelDialog').showModal(); } };
$('panelClose').onclick = () => $('panelDialog').close();
$('panelTabs').onclick = event => { if (event.target.dataset.panel) renderPlayerPanel(event.target.dataset.panel); };
$('panelContent').onclick = async event => {
  const target = event.target.dataset.panelTravel;
  if (!target || !session || busy) return;
  $('panelDialog').close();
  if (story.world) await performWorldAction({action:'travel', location_id:target});
  else await mutateSession(() => api('/stories/' + story.id + '/sessions/' + session.id + '/advance', {method:'POST', body:JSON.stringify(worldEvent({scene_id:target}))}));
};
$('panelContent').onchange = async event => {
  const cid = event.target.dataset.personArt, file = event.target.files?.[0];
  if (!cid || !file || busy) return;
  const data = new FormData(); data.append('image', file);
  try {
    const image = await api('/assets', {method:'POST', body:data});
    await mutateSession(() => api('/stories/' + story.id + '/sessions/' + session.id + '/character-art', {method:'PATCH', body:JSON.stringify({character_id:cid, image:image.file})}));
    notice('已綁定這名角色的圖片，記憶與身分保留。');
  } catch (error) { notice(error.message); }
};
$('packageBtn').onclick = () => { $('packageStatus').textContent = ''; $('packageDialog').showModal(); };
$('packageClose').onclick = () => $('packageDialog').close();
$('packageForm').onsubmit = async event => {
  event.preventDefault();
  const data = new FormData(); data.append('package_zip', $('packageZip').files[0]);
  if (story?.id) data.append('story_id', story.id);
  $('packageStatus').textContent = '正在驗證資料包…';
  try {
    const result = await api('/packages', {method:'POST', body:data});
    $('packageDialog').close(); await loadList(); await openStory(result.story.id);
    notice(result.already_installed ? '這份資料包已安裝，原進度保留。' : '匯入完成，原有存檔與歷史保留。');
  } catch (error) { $('packageStatus').textContent = error.message; }
};
window.visualViewport?.addEventListener('resize', () => requestAnimationFrame(positionSpeech));
$('authorBtn').onclick = () => { $('authorStatus').textContent = ''; $('authorDialog').showModal(); };
$('authorClose').onclick = () => $('authorDialog').close();
$('authorForm').onsubmit = async event => {
  event.preventDefault();
  const file = $('authorDocument').files[0];
  let body;
  if (file) { body = new FormData(); body.append('document',file); }
  else body = JSON.stringify({text:$('authorText').value});
  const button = event.submitter; button.disabled = true; $('authorStatus').textContent = '正在整理設定書…';
  try {
    const result = await api('/author-draft', {method:'POST',body});
    story = result.draft; session = null; edit(); $('authorDialog').close();
    notice('草稿已備妥，請檢查人物與場景後儲存。');
  } catch (error) { $('authorStatus').textContent = error.message; }
  finally { button.disabled = false; }
};
