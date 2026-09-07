// Static deployment adapter. Published files contain public data only.
(() => {
  const bootstrap = document.querySelector('#cloud-bootstrap');
  let manifest = bootstrap ? JSON.parse(bootstrap.textContent) : null;
  let initialMeta = true;
  const cache = new Map();
  let warming;
  let warmingStarted = false;
  async function metadata() {
    if (manifest && initialMeta) { initialMeta = false; return manifest.meta; }
    const response = await fetch('data/manifest.json', {cache: 'no-cache'});
    if (!response.ok) throw new Error('云端目录尚未发布，请稍后重试');
    manifest = await response.json();
    initialMeta = false;
    if (warmingStarted) scheduleWarmup();
    return manifest.meta;
  }
  async function load(key, background = false) {
    if (!manifest) await metadata();
    const path = manifest.views[key];
    if (!path) throw new Error('该视图尚未发布');
    if (!cache.has(path)) {
      const pending = fetch(path, {priority: background ? 'low' : 'auto'}).then(async response => {
      if (!response.ok) throw new Error('云端数据尚未发布，请稍后重试');
        return response.json();
      }).catch(error => { cache.delete(path); throw error; });
      cache.set(path, pending);
    }
    return cache.get(path);
  }
  // Only start after the initial page is usable. Clicks share these same promises.
  window.prefetchCloudViews = () => {
    warmingStarted = true;
    if (warming) return warming;
    warming = (async () => {
      if (!manifest) await metadata();
      const first = ['facts', 'projects', 'launches:today', 'hn:news:ai:rank', 'xrank:tweets:24h'];
      const queue = [...new Set([...first, ...Object.keys(manifest.views)])]
        .filter(key => manifest.views[key] && !cache.has(manifest.views[key]));
      async function worker() {
        while (queue.length) {
          const key = queue.shift();
          try { await load(key, true); } catch { /* A click can retry a failed preload. */ }
        }
      }
      await Promise.all([worker(), worker()]);
    })().finally(() => { warming = null; });
    return warming;
  };
  function scheduleWarmup() {
    const run = () => window.prefetchCloudViews().catch(() => {});
    if (window.requestIdleCallback) window.requestIdleCallback(run, {timeout: 1500});
    else setTimeout(run, 300);
  }
  window.scheduleCloudWarmup = scheduleWarmup;
  window.cloudAPI = async path => {
    const url = new URL(path, location.origin);
    const p = url.searchParams;
    if (url.pathname === '/api/meta') return metadata();
    if (url.pathname === '/api/content') {
      const content = await load('content');
      const values = key => p.getAll(key).flatMap(v => v.split(',')).filter(v => v && v !== 'all');
      const q = (p.get('q') || '').trim().toLowerCase();
      const categories = values('category');
      const items = content.filter(item => {
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
    return load(key);
  };
})();
