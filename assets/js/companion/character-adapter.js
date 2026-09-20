/*
 * Miru Companion character adapter facade.
 *
 * This file intentionally contains no renderer, model, microphone, screen
 * capture, chat, or memory logic.  It only provides a small, failure-isolated
 * contract between the desktop pet UI and a visual character implementation.
 */
(function(root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.MiruCharacterAdapter = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';

  var STATES = [
    'idle',
    'thinking',
    'talking',
    'walking-left',
    'walking-right',
    'happy',
    'sad',
    'surprised',
    'sleeping'
  ];

  var STATE_SET = {};
  for (var i = 0; i < STATES.length; i++) STATE_SET[STATES[i]] = true;

  function clamp(value, low, high) {
    var number = Number(value);
    if (!isFinite(number)) number = 0;
    return Math.max(low, Math.min(high, number));
  }

  function normalizeState(value) {
    return STATE_SET[value] ? value : 'idle';
  }

  function normalizeCapabilities(value) {
    value = value || {};
    return Object.freeze({
      motions: value.motions === true,
      expressions: value.expressions === true,
      lipSync: value.lipSync === true,
      focusTracking: value.focusTracking === true,
      transparentBackground: value.transparentBackground === true
    });
  }

  function normalizeBounds(value) {
    if (!value) return null;
    var left = Number(value.left);
    var top = Number(value.top);
    var right = Number(value.right);
    var bottom = Number(value.bottom);
    if (![left, top, right, bottom].every(isFinite)) return null;
    if (right < left || bottom < top) return null;
    return { left: left, top: top, right: right, bottom: bottom };
  }

  function createFacade(adapter, options) {
    if (!adapter || typeof adapter !== 'object') {
      throw new TypeError('Character adapter must be an object.');
    }
    if (!adapter.id || typeof adapter.id !== 'string') {
      throw new TypeError('Character adapter id must be a non-empty string.');
    }

    options = options || {};
    var capabilities = normalizeCapabilities(adapter.capabilities);
    var mounted = false;
    var state = 'idle';
    var emotion = '';
    var mountPromise = null;

    function report(action, error) {
      if (typeof options.onError === 'function') {
        try { options.onError({ adapterId: adapter.id, action: action, error: error }); }
        catch (ignored) {}
      }
    }

    function callAsync(action, callback) {
      return Promise.resolve()
        .then(callback)
        .then(function() { return true; })
        .catch(function(error) {
          report(action, error);
          return false;
        });
    }

    var facade = {
      id: adapter.id,
      capabilities: capabilities,

      mount: function(host, mountOptions) {
        if (mounted) return Promise.resolve(true);
        if (mountPromise) return mountPromise;
        mountPromise = callAsync('mount', function() {
          if (typeof adapter.mount !== 'function') {
            throw new TypeError('Character adapter is missing mount().');
          }
          return adapter.mount(host, mountOptions || {});
        }).then(function(ok) {
          mounted = ok;
          mountPromise = null;
          return ok;
        });
        return mountPromise;
      },

      unmount: function() {
        if (!mounted && !mountPromise) return Promise.resolve(true);
        return Promise.resolve(mountPromise).catch(function() { return false; })
          .then(function() {
            return callAsync('unmount', function() {
              if (typeof adapter.unmount === 'function') return adapter.unmount();
            });
          })
          .then(function(ok) {
            mounted = false;
            mountPromise = null;
            state = 'idle';
            return ok;
          });
      },

      setState: function(nextState, payload) {
        var normalized = normalizeState(nextState);
        if (state === 'sleeping' && normalized === 'talking') normalized = 'sleeping';
        state = normalized;
        if (!mounted || typeof adapter.setState !== 'function') return Promise.resolve(false);
        return callAsync('setState', function() {
          return adapter.setState(normalized, payload);
        });
      },

      setEmotion: function(nextEmotion, intensity) {
        emotion = typeof nextEmotion === 'string' ? nextEmotion : '';
        var normalizedIntensity = intensity == null ? 1 : clamp(intensity, 0, 1);
        if (!mounted || typeof adapter.setEmotion !== 'function') return Promise.resolve(false);
        return callAsync('setEmotion', function() {
          return adapter.setEmotion(emotion, normalizedIntensity);
        });
      },

      lookAt: function(x, y) {
        if (!mounted || !capabilities.focusTracking || typeof adapter.lookAt !== 'function') return false;
        try {
          adapter.lookAt(clamp(x, -1, 1), clamp(y, -1, 1));
          return true;
        } catch (error) {
          report('lookAt', error);
          return false;
        }
      },

      resize: function(width, height, layout) {
        if (!mounted || typeof adapter.resize !== 'function') return false;
        var normalizedWidth = Number(width);
        var normalizedHeight = Number(height);
        if (!isFinite(normalizedWidth) || normalizedWidth <= 0 ||
            !isFinite(normalizedHeight) || normalizedHeight <= 0) return false;
        try {
          adapter.resize(normalizedWidth, normalizedHeight, layout || {});
          return true;
        } catch (error) {
          report('resize', error);
          return false;
        }
      },

      getBounds: function() {
        if (!mounted || typeof adapter.getBounds !== 'function') return null;
        try { return normalizeBounds(adapter.getBounds()); }
        catch (error) {
          report('getBounds', error);
          return null;
        }
      },

      isMounted: function() { return mounted; },
      getState: function() { return state; },
      getEmotion: function() { return emotion; }
    };

    return Object.freeze(facade);
  }

  return Object.freeze({
    states: Object.freeze(STATES.slice()),
    normalizeState: normalizeState,
    createFacade: createFacade
  });
});
