// The Windows main WebView may render /app from the configured remote server.
// Its local desktop API is the bridge to the separate, bundled pet WebView.
(function() {
  'use strict';
  if (window.__miruOutfitBridgeInstalled) return;
  window.__miruOutfitBridgeInstalled = true;

  function install(remaining) {
    if (typeof window.sendCompanionMessage !== 'function') {
      if (remaining) setTimeout(function() { install(remaining - 1); }, 250);
      return;
    }
    var original = window.sendCompanionMessage;
    window.sendCompanionMessage = async function() {
      var input = document.getElementById('textInput');
      var text = input && input.value.trim();
      if (!text || !window.MiruOutfitCommand.parse(text, 'normal')) {
        return original.apply(this, arguments);
      }
      // Consume the command locally; the remote AI cannot operate this pet.
      input.value = '';
      input.style.height = '44px';
      if (typeof window.addCompanionUserBubble === 'function') {
        window.addCompanionUserBubble(text, null, null);
      }
      var reply;
      try {
        var api = window.pywebview && window.pywebview.api;
        if (!api) throw new Error('無法連線到 Windows 桌寵');
        var current = await api.get_local_settings();
        if (!current.ok) throw new Error(current.error || '無法讀取服裝設定');
        var next = window.MiruOutfitCommand.parse(text,
          (current.settings || {}).pet_outfit || 'normal');
        var changed = await api.set_local_settings({pet_outfit: next});
        if (!changed.ok) throw new Error(changed.error || '無法儲存服裝設定');
        var label = {normal:'一般服',home:'居家服',outdoor:'外出服'}[next];
        reply = '換好' + label + '了。桌寵會在幾秒內切換。';
      } catch(error) {
        reply = '換裝失敗：' + error.message;
      }
      if (typeof window.addCompanionReplyBubble === 'function') {
        window.addCompanionReplyBubble(reply, [], null);
        window.scrollCompanionChatToBottom();
      }
    };
  }
  install(20);
})();
