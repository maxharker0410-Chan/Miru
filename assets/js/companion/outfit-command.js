(function(root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.MiruOutfitCommand = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  var outfits = ['normal','home','outdoor'];
  function parse(text,current) {
    var input = String(text || '').replace(/\s+/g,'');
    if (!/(換|穿|切換|改成|改穿)/.test(input) || !/(衣|服|裝|造型)/.test(input)) return null;
    if (/(居家|家居|睡衣|家裡)/.test(input)) return 'home';
    if (/(外出|出門|外面)/.test(input)) return 'outdoor';
    if (/(一般|平常|原本|預設|默认|普通)/.test(input)) return 'normal';
    var index = outfits.indexOf(current);
    return outfits[((index < 0 ? 0 : index) + 1) % outfits.length];
  }
  return {parse:parse};
});
