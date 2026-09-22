(function(root) {
  'use strict';
  function clamp(v,lo,hi) { return Math.max(lo,Math.min(hi,v)); }
  function position(value) {
    value=value || {};
    return {x:Number.isFinite(value.x)?clamp(value.x,.22,.78):.5,
      y:Number.isFinite(value.y)?clamp(value.y,.72,.88):.83};
  }
  function create(options) {
    var win=options.window, point=position(), active=false, frame=null, target=null, last=0;
    var key='miru.companion.room.position.v1';
    try { point=position(JSON.parse(win.localStorage.getItem(key))); } catch(e) {}
    function save() { try { win.localStorage.setItem(key,JSON.stringify(point)); } catch(e) {} }
    function draw() {
      options.resize(win.innerWidth,win.innerHeight,{scale:.55,
        x:(point.x-.5)*win.innerWidth,y:point.y*win.innerHeight-(win.innerHeight-60)});
    }
    function stop() { if(frame!==null)win.cancelAnimationFrame(frame);frame=null;target=null;last=0; }
    function tick(now) {
      frame=null;
      if(!active||!target)return;
      var dt=last?Math.min((now-last)/1000,.05):0;last=now;
      var dx=(target.x-point.x)*win.innerWidth,dy=(target.y-point.y)*win.innerHeight;
      var distance=Math.hypot(dx,dy), step=150*dt;
      if(distance<=step||distance<1) {point=target;target=null;draw();save();return;}
      point.x+=dx/distance*step/win.innerWidth;point.y+=dy/distance*step/win.innerHeight;
      draw();frame=win.requestAnimationFrame(tick);
    }
    function resized() { if(active)draw(); }
    return {
      enter:function(){if(active)return;active=true;win.addEventListener('resize',resized);draw();},
      leave:function(){stop();save();active=false;win.removeEventListener('resize',resized);},
      move:function(x,y){if(!active)return;stop();target=position({x:x,y:y});frame=win.requestAnimationFrame(tick);},
      home:function(){stop();point=position();if(active)draw();save();},
      getPosition:function(){return {x:point.x,y:point.y};}
    };
  }
  var api={create:create,position:position};
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.MiruRoom=api;
})(typeof globalThis!=='undefined'?globalThis:this);
