// Static deployment adapter. Published files contain public data only.
(() => {
  let bundle;
  async function load(refresh) {
    if (!bundle || refresh) {
      const response = await fetch('data/site.json', {cache: 'no-cache'});
      if (!response.ok) throw new Error('云端数据尚未发布，请稍后重试');
      bundle = await response.json();
    }
    return bundle;
  }
  window.cloudAPI = async path => {
    const url = new URL(path, location.origin);
    const p = url.searchParams;
    const data = await load(url.pathname === '/api/meta');
    if (url.pathname === '/api/content') {
      const values = key => p.getAll(key).flatMap(v => v.split(',')).filter(v => v && v !== 'all');
      const q = (p.get('q') || '').trim().toLowerCase();
      const categories = values('category');
      const items = data.content.filter(item => {
        if (p.get('scope') === 'selected' && !item.selected) return false;
        if (categories.length && !categories.includes(item.category)) return false;
        if (q && ![item.title, item.summary, item.source_name].some(v => String(v || '').toLowerCase().includes(q))) return false;
        return [['topic', 'technology'], ['form', 'form'], ['entity', 'entity']].every(([key, dimension]) => {
          const selected = values(key);
          return !selected.length || item.tags.some(tag => tag.dimension === dimension && selected.includes(tag.slug));
        });
      });
      const offset = Math.max(0, Number(p.get('offset')) || 0);
      const limit = Math.min(200, Math.max(1, Number(p.get('limit')) || 60));
      const page = items.slice(offset, offset + limit);
      return {items: page, page: {count: page.length, total: items.length, offset, hasMore: offset + limit < items.length}};
    }
    let key = url.pathname.slice(5);
    if (key === 'launches') key += ':' + (p.get('category') || p.get('range') || 'today');
    if (key === 'xrank') key += ':' + (p.get('kind') || 'tweets') + ':' + (p.get('range') || '24h');
    if (key === 'hn') key += ':' + (p.get('view') || 'news') + ':' + (p.get('scope') || 'ai') + ':' + (p.get('sort') || 'rank');
    if (!(key in data)) throw new Error('该视图尚未发布');
    return data[key];
  };
})();
