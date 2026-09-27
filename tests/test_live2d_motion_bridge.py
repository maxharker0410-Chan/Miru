from test_character_adapter import _run_node


def test_declared_motions_expressions_fallback_and_disposal():
    assert _run_node(r"""
const assert = require('node:assert/strict');
const {create} = require('./assets/js/companion/live2d-motion-bridge.js');
const calls = [];
const model = {
  internalModel: {
    settings: {json:{FileReferences:{
      Motions:{Idle:[{File:'idle'}], Think:[{File:'think'}], Talk:[{File:'voice',Sound:'voice.wav'},{File:'talk'}]},
      Expressions:[{Name:'Smile',File:'smile'},{Name:'Neutral',File:'neutral'}]
    }}},
    motionManager:{stopAllMotions:()=>calls.push(['stop'])}
  },
  motion:async(...args)=>{calls.push(['motion',...args]);return true;},
  expression:async(index)=>{calls.push(['expression',index]);return true;}
};
(async()=>{
  const bridge = create(model, 3);
  assert.equal(bridge.capabilities.motions, true);
  assert.equal(bridge.capabilities.expressions, true);
  await bridge.setState('thinking');
  await bridge.setState('talking');
  await bridge.setState('sleeping');
  await bridge.setEmotion('開心');
  await bridge.setEmotion('unmapped mood');
  assert.deepEqual(calls,[['motion','Think',0,3],['motion','Talk',1,3],['motion','Idle',0,3],['expression',0],['expression',1]]);
  bridge.dispose();
  const count = calls.length;
  assert.equal(await bridge.setState('talking'), false);
  assert.equal(await bridge.setEmotion('happy'), false);
  assert.equal(calls.length,count);
  const empty = create({internalModel:{settings:{}}},3);
  assert.equal(empty.capabilities.motions,false);
  assert.equal(await empty.setState('thinking'),false);
  assert.equal(await empty.setEmotion('sad'),false);
  console.log(JSON.stringify({ok:true}));
})();
""") == {"ok": True}


def test_failed_mount_cleanup_and_capabilities_after_mount():
    assert _run_node(r"""
const assert = require('node:assert/strict');
const {createFacade} = require('./assets/js/companion/character-adapter.js');
(async()=>{
  let cleaned=0;
  const broken=createFacade({id:'broken', mount:async()=>{throw Error('missing model');}, unmount:async()=>{cleaned++;}});
  assert.equal(await broken.mount({}),false);
  assert.equal(cleaned,1);
  const facade=createFacade({id:'ok',capabilities:{motions:false},mount:async function(){this.capabilities.motions=true;}});
  assert.equal(facade.capabilities.motions,false);
  await facade.mount({});
  assert.equal(facade.capabilities.motions,true);
  assert.equal(Object.isFrozen(facade.capabilities),true);
  console.log(JSON.stringify({ok:true}));
})();
""") == {"ok": True}
