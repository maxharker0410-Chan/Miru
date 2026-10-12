(function (root) {
  'use strict';
  function page(items, options = {}) {
    const query = String(options.query || '').normalize('NFKC').toLocaleLowerCase().trim();
    const kind = options.kind || '', region = options.region || '';
    const rows = items.map((item, index) => ({item, index})).filter(({item}) => {
      if (kind && item.kind !== kind || region && item.region_id !== region) return false;
      const text = [item.id, item.name, item.title, item.search_label, item.identity?.display_label].filter(Boolean).join(' ').normalize('NFKC').toLocaleLowerCase();
      return !query || text.includes(query);
    });
    const size = Math.min(24, Math.max(1, Number(options.pageSize) || 6));
    const totalPages = Math.max(1, Math.ceil(rows.length / size));
    const currentPage = Math.min(totalPages, Math.max(1, Number(options.page) || 1));
    return {rows:rows.slice((currentPage - 1) * size, currentPage * size), total:rows.length, page:currentPage, totalPages};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {page};
  else root.SChatLibrary = {page};
})(typeof window !== 'undefined' ? window : this);
