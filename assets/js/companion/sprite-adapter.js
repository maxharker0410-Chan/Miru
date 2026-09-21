(function(root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.MiruSpriteAdapter = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  var frames = ['idle','blink','talking','thinking','happy','sad','surprised','sleeping'];
  var emotions = {happy:'happy',smile:'happy','開心':'happy','开心':'happy',sad:'sad',
    '難過':'sad','难过':'sad',surprised:'surprised','驚訝':'surprised','惊讶':'surprised'};
  function create(options) {
    options = options || {};
    var win = options.window || window, doc = options.document || document;
    var makeImage = options.createImage || function() { return new Image(); };
    var base = options.base || '/assets/companion/portrait/';
    var images = {}, element = null, timer = null, pending = null, epoch = 0, cancelLoads = [];
    var state = 'idle', emotion = 'idle', closed = false, mounted = false;
    var layout = {scale:1,x:0,y:0}, size = 0, left = 0, top = 0;
    function draw() {
      if (!mounted) return;
      var frame = state === 'idle' ? (emotion === 'idle' && closed ? 'blink' : emotion) : state;
      element.src = images[frame].src;
      element.dataset.state = frame;
    }
    function blink() {
      if (!mounted) return;
      closed = !closed; draw();
      timer = win.setTimeout(blink,closed ? 140 : 4000);
    }
    function resize(width,height,next) {
      if (!mounted) return;
      next = next || layout;
      ['scale','x','y'].forEach(function(key) {
        if (typeof next[key] === 'number' && isFinite(next[key])) layout[key] = next[key];
      });
      layout.scale = Math.max(0.1,Math.min(3,layout.scale));
      size = Math.min(height*0.72,width*1.5)*layout.scale;
      left = (width-size)/2+layout.x; top = height-60-size+layout.y;
      Object.assign(element.style,{width:size+'px',height:size+'px',left:left+'px',top:top+'px'});
    }
    function onResize() { resize(win.innerWidth,win.innerHeight); }
    function cleanup() {
      epoch++; mounted = false;
      cancelLoads.forEach(function(cancel) { cancel(); }); cancelLoads = [];
      if (timer !== null) win.clearTimeout(timer);
      timer = null;
      win.removeEventListener('resize',onResize);
      if (element) element.remove();
      element = null; images = {}; state = 'idle'; emotion = 'idle'; closed = false;
    }
    return {
      id:'portrait-sprite',
      capabilities:{motions:true,expressions:true,lipSync:false,focusTracking:false,transparentBackground:true},
      mount: function(target,mountOptions) {
        if (mounted) return Promise.resolve();
        if (pending) return pending;
        var token = ++epoch;
        pending = Promise.all(frames.map(function(name) {
          return new Promise(function(resolve,reject) {
            var img = makeImage(), settled = false;
            var deadline = win.setTimeout(function() { finish(new Error('Image load timeout: '+name)); },15000);
            function finish(error) {
              if (settled) return;
              settled = true;
              win.clearTimeout(deadline); img.onload = img.onerror = null;
              if (error) reject(error); else resolve([name,img]);
            }
            img.onload = function() { finish(); };
            img.onerror = function() { finish(new Error('Image load failed: '+name)); };
            cancelLoads.push(function() { finish(new Error('Image load cancelled')); });
            img.src = base+name+'.png';
          });
        })).then(function(loaded) {
          if (token !== epoch) throw new Error('Sprite mount cancelled');
          cancelLoads = [];
          loaded.forEach(function(pair) { images[pair[0]] = pair[1]; });
          element = doc.createElement('img'); element.alt = '角色'; element.draggable = false;
          Object.assign(element.style,{position:'absolute',pointerEvents:'none',objectFit:'contain'});
          target.appendChild(element); mounted = true;
          resize(win.innerWidth,win.innerHeight,(mountOptions || {}).layout); draw();
          timer = win.setTimeout(blink,4000); win.addEventListener('resize',onResize);
        }).catch(function(error) { cleanup(); throw error; })
          .finally(function() { pending = null; });
        return pending;
      },
      unmount: async function() { cleanup(); },
      setState: async function(next) {
        state = frames.indexOf(next) >= 0 && next !== 'blink' ? next : 'idle';
        closed = false; draw();
      },
      setEmotion: async function(next) {
        var key = String(next || '').trim().toLowerCase();
        emotion = Object.prototype.hasOwnProperty.call(emotions,key) ? emotions[key] : 'idle'; draw();
      },
      lookAt: function() {},
      resize: resize,
      getBounds: function() {
        if (!mounted) return null;
        // Stable visual body envelope, excluding transparent side margins.
        return {left:left+size*0.29,top:top,right:left+size*0.71,bottom:top+size};
      }
    };
  }
  return {create:create};
});
