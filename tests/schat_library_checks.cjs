'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {page} = require('../assets/js/schat-library.js');
const characters = Array.from({length:153},(_,i)=>({id:'stable_' + i, name:'角色' + i,
  kind:i<54?'important_character':'npc', region_id:i%2?'region_01':'region_02', search_label:i===150?'星輝守衛':''}));
test('153-character library renders six rows and retains original edit indexes',()=>{
  const result=page(characters,{page:2});
  assert.equal(result.rows.length,6); assert.equal(result.totalPages,26);
  assert.equal(result.rows[0].item.id,'stable_6'); assert.equal(result.rows[0].index,6);
});
test('NPC pagination finds all 99 exactly once',()=>{
  const ids=[];
  for(let n=1;n<=17;n++) ids.push(...page(characters,{kind:'npc',page:n}).rows.map(r=>r.item.id));
  assert.equal(ids.length,99); assert.equal(new Set(ids).size,99);
});
test('search by asset label and stable ID resolves a late-page character',()=>{
  assert.equal(page(characters,{query:'星輝守衛'}).rows[0].index,150);
  assert.equal(page(characters,{query:'STABLE_150'}).rows[0].item.id,'stable_150');
});
test('combined filters, empty results and oversized page remain usable',()=>{
  const filtered=page(characters,{kind:'npc',region:'region_02',page:100});
  assert.equal(filtered.page,filtered.totalPages); assert.ok(filtered.rows.every(r=>r.item.kind==='npc'&&r.item.region_id==='region_02'));
  const empty=page(characters,{query:'不存在'}); assert.equal(empty.total,0); assert.equal(empty.page,1);
});
