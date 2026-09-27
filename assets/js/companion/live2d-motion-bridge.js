/* Named, model-declared motions only; no arbitrary sample-clip guessing. */
(function(root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.MiruLive2DMotionBridge = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  var aliases = {
    idle: ['idle'], thinking: ['thinking', 'think'], talking: ['talking', 'talk'],
    sleeping: ['sleeping', 'sleep'], happy: ['happy', 'smile', '开心', '開心', '高興'],
    sad: ['sad', '悲傷', '悲伤', '難過', '难过'],
    surprised: ['surprised', 'surprise', '驚訝', '惊讶'],
    neutral: ['neutral', 'normal'],
    'walking-left': ['walking-left', 'walk_left'],
    'walking-right': ['walking-right', 'walk_right']
  };
  function canonical(value) {
    var name = String(value || '').trim().toLowerCase();
    return Object.keys(aliases).find(function(key) { return aliases[key].indexOf(name) >= 0; }) || name;
  }
  function create(model, forcePriority) {
    var internal = model.internalModel || {};
    var settings = internal.settings || {};
    var raw = settings.json || {};
    var refs = raw.FileReferences || {};
    var motions = settings.motions || refs.Motions || raw.motions || {};
    var expressions = settings.expressions || refs.Expressions || raw.expressions || [];
    var manager = internal.motionManager;
    var motionMap = Object.create(null);
    var expressionMap = Object.create(null);
    var disposed = false;
    Object.keys(motions).forEach(function(group) {
      if (!Array.isArray(motions[group])) return;
      // Do not trigger bundled voice lines as a side effect of UI state.
      var index = motions[group].findIndex(function(entry) {
        return entry && (entry.File || entry.file) && !entry.Sound && !entry.sound;
      });
      if (index >= 0) motionMap[canonical(group)] = {group: group, index: index};
    });
    if (Array.isArray(expressions)) expressions.forEach(function(entry, index) {
      var name = entry && (entry.Name || entry.name);
      if (name && (entry.File || entry.file)) expressionMap[canonical(name)] = index;
    });
    function stop() {
      if (manager && typeof manager.stopAllMotions === 'function') manager.stopAllMotions();
    }
    return {
      capabilities: {
        motions: typeof model.motion === 'function' && Object.keys(motionMap).length > 0,
        expressions: typeof model.expression === 'function' && Object.keys(expressionMap).length > 0
      },
      setState: async function(state) {
        if (disposed) return false;
        var entry = motionMap[canonical(state)] || motionMap.idle;
        if (!entry || typeof model.motion !== 'function') { stop(); return false; }
        // FORCE lets a completed conversation replace its thinking clip.
        var started = await model.motion(entry.group, entry.index, forcePriority);
        if (disposed) return false;
        // A false result can mean a newer request won; do not stop that motion.
        return !!started;
      },
      setEmotion: async function(emotion) {
        if (disposed) return false;
        var index = expressionMap[canonical(emotion)];
        if (index === undefined) index = expressionMap.neutral;
        if (index !== undefined && typeof model.expression === 'function') {
          return model.expression(index);
        }
        var expressionManager = manager && manager.expressionManager;
        if (expressionManager && typeof expressionManager.resetExpression === 'function') {
          expressionManager.resetExpression();
        }
        return false;
      },
      dispose: function() { disposed = true; stop(); }
    };
  }
  return {create: create};
});
