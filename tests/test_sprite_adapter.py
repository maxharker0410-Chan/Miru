from pathlib import Path

from PIL import Image
from test_character_adapter import _run_node
import app as app_module


def test_sprite_lifecycle_states_blink_and_emotions():
    assert _run_node(r"""
const assert=require('node:assert/strict');
const {create}=require('./assets/js/companion/sprite-adapter.js');
const timers=new Map(), listeners=new Map(); let next=0,element;
const win={innerWidth:420,innerHeight:760,setTimeout:(fn,ms)=>{timers.set(++next,{fn,ms});return next;},clearTimeout:id=>timers.delete(id),
 addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)};
const host={children:[],appendChild:e=>host.children.push(e)};
const doc={createElement:()=>{element={style:{},dataset:{},remove:()=>{host.children=[];}};return element;}};
function image(){return {set src(value){this.url=value;queueMicrotask(()=>this.onload());},get src(){return this.url;}};}
(async()=>{
 const adapter=create({window:win,document:doc,createImage:image});
 await Promise.all([adapter.mount(host),adapter.mount(host)]);
 assert.equal(host.children.length,1); assert.equal(timers.size,1);
 assert.equal(element.dataset.state,'idle');
 function tick(){const [id,timer]=[...timers][0];timers.delete(id);timer.fn();}
 tick();assert.equal(element.dataset.state,'blink');tick();assert.equal(element.dataset.state,'idle');
 await adapter.setState('thinking');assert.equal(element.dataset.state,'thinking');
 await adapter.setEmotion('開心');assert.equal(element.dataset.state,'thinking');
 await adapter.setState('idle');assert.equal(element.dataset.state,'happy');
 await adapter.setState('talking');tick();assert.equal(element.dataset.state,'talking');
 await adapter.setState('sleeping');await adapter.setEmotion('sad');assert.equal(element.dataset.state,'sleeping');
 await adapter.setEmotion('unknown');await adapter.setState('walking-left');assert.equal(element.dataset.state,'idle');
 const before=adapter.getBounds();adapter.resize(420,760,{scale:1,x:20,y:30});
 const after=adapter.getBounds();assert.equal(after.left-before.left,20);assert.equal(after.top-before.top,30);
 await adapter.unmount();await adapter.unmount();assert.equal(timers.size,0);assert.equal(listeners.size,0);
 assert.equal(host.children.length,0);assert.equal(adapter.getBounds(),null);
 await adapter.mount(host);assert.equal(host.children.length,1);await adapter.unmount();
 console.log(JSON.stringify({ok:true}));
})();
""") == {"ok": True}


def test_portrait_images_are_transparent_and_served():
    client = app_module.app.test_client()
    root = Path(__file__).resolve().parents[1] / 'assets/companion/portrait'
    for state in ['idle','blink','talking','thinking','happy','sad','surprised','sleeping']:
        with Image.open(root / f'{state}.png') as image:
            assert image.format == 'PNG'
            assert image.size == (1254, 1254)
            assert image.getchannel('A').getextrema() == (0, 255)
        response = client.get(f'/assets/companion/portrait/{state}.png')
        assert response.status_code == 200
        assert response.mimetype == 'image/png'
    assert client.get('/assets/js/companion/sprite-adapter.js').status_code == 200
    assert client.get('/assets/companion/portrait/preview.html').status_code == 200
    assert client.get('/assets/companion/portrait/../../../app.py').status_code == 404
