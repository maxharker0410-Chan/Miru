from test_character_adapter import _run_node


def test_room_movement_bounds_persistence_and_cleanup():
    assert _run_node(r"""
const assert=require('node:assert/strict');
const {create,position}=require('./assets/js/companion/room.js');
assert.deepEqual(position({x:100,y:-3}),{x:.78,y:.72});
assert.deepEqual(position({x:NaN,y:Infinity}),{x:.5,y:.83});
let saved=null,next=0,draws=0;const frames=new Map(),listeners=new Map();
const win={innerWidth:420,innerHeight:760,localStorage:{getItem:()=>saved,setItem:(k,v)=>saved=v},
 requestAnimationFrame:fn=>{frames.set(++next,fn);return next;},cancelAnimationFrame:id=>frames.delete(id),
 addEventListener:(k,fn)=>listeners.set(k,fn),removeEventListener:k=>listeners.delete(k)};
const room=create({window:win,resize:()=>draws++});
room.enter();room.enter();assert.equal(listeners.size,1);
room.move(1,1);let now=100;
for(let i=0;i<200&&frames.size;i++){const [id,fn]=[...frames][0];frames.delete(id);fn(now);now+=16;}
assert.deepEqual(room.getPosition(),{x:.78,y:.88});assert.ok(saved);assert.equal(frames.size,0);
room.move(.22,.72);room.leave();assert.equal(frames.size,0);assert.equal(listeners.size,0);
const count=draws;room.move(.3,.8);assert.equal(draws,count);
const restored=create({window:win,resize:()=>{}});assert.deepEqual(restored.getPosition(),room.getPosition());
restored.enter();restored.home();assert.deepEqual(restored.getPosition(),{x:.5,y:.83});restored.leave();
console.log(JSON.stringify({ok:true}));
""") == {"ok": True}
