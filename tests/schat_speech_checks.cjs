'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../assets/js/schat.js'), 'utf8');
const speechFunction = source.slice(source.indexOf('function currentSpeech('), source.indexOf('function positionSpeech('));
function reader(messages) {
  const context = vm.createContext({session:{id:'play',messages},pendingPlayer:null,speechKey:'',speechIndex:0,speechFrames:[]});
  vm.runInContext(speechFunction, context);
  return context;
}
const msg = (speaker, text, scene_id='one', dialogue) => ({speaker,text,scene_id,dialogue});
const scene = {id:'one',cast:['alice','bob']};
test('only the latest turn and currently present speakers appear', () => {
  const c = reader([msg('alice','old reply'),msg('player','private visit'),msg('cat','absent'),msg('bob','actions','one','spoken words')]);
  assert.equal(c.currentSpeech(scene).text, 'actions');
  assert.equal(c.speechFrames.length, 1);
});
test('full character response takes priority over an echoed player summary', () => {
  const c = reader([msg('player','你有沒有受傷？'),msg('alice','她搖頭：「我沒事，謝謝你。」','one','你有沒有受傷？')]);
  assert.equal(c.currentSpeech(scene).text, '她搖頭：「我沒事，謝謝你。」');
  assert.equal(c.currentPlayer(scene).text, '你有沒有受傷？');
});
test('submitted player text appears immediately and failures remain clearly labelled', () => {
  const c = reader([msg('player','previous'),msg('alice','old response')]);
  c.pendingPlayer = {sessionId:'play', text:'new input', state:'sending'};
  assert.equal(c.currentPlayer(scene).text, 'new input');
  c.pendingPlayer.state = 'failed';
  assert.equal(c.currentPlayer(scene).state, 'failed');
  c.pendingPlayer = null;
  assert.equal(c.currentPlayer(scene).text, 'previous');
});
test('changing scenes cannot carry dialogue from the prior location', () => {
  const c = reader([msg('bob','old'),msg('narrator','new place','two')]);
  assert.equal(c.currentSpeech({id:'two',cast:['bob']}), undefined);
});
test('long Unicode replies keep every character across pages', () => {
  const text = ('記得旅途🙂，接著一起走吧。\n'.repeat(80)) + '最後一句';
  const c = reader([msg('player','hello'),msg('alice',text)]);
  c.currentSpeech(scene);
  assert.ok(c.speechFrames.length > 1);
  assert.equal(c.speechFrames.map(f => f.text).join(''), text);
  assert.ok(c.speechFrames.every(f => Array.from(f.text).length <= 240));
  assert.ok(c.speechFrames.every(f => !/[\uD800-\uDBFF]$/.test(f.text)));
});
test('new reply resets selection even when capped history has the same length', () => {
  const c = reader([msg('player','first'),msg('alice','A'),msg('bob','B')]);
  c.currentSpeech(scene); c.speechIndex = 1;
  c.session.messages = [msg('player','second'),msg('alice','new A'),msg('bob','new B')];
  assert.equal(c.currentSpeech(scene).text, 'new A');
  assert.equal(c.speechIndex, 0);
});
test('manual image updates preserve the current dialogue page', () => {
  const c = reader([msg('player','hello'),msg('alice','A'),msg('bob','B')]);
  c.currentSpeech(scene); c.speechIndex = 1;
  c.session = JSON.parse(JSON.stringify(c.session));
  c.session.visuals = {bob:{state_id:'hurt',locked:true}};
  assert.equal(c.currentSpeech(scene).speaker, 'bob');
  assert.equal(c.speechIndex, 1);
});
test('a turn with no present speaker clears the previous bubble', () => {
  const c = reader([msg('player','hello'),msg('alice','A')]);
  c.currentSpeech(scene);
  c.session.messages.push(msg('player','everyone leaves'), msg('narrator','empty room'));
  assert.equal(c.currentSpeech({id:'one',cast:[]}), undefined);
});
