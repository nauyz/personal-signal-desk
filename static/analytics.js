/* Cookieless analytics. Local previews never send data to the production project. */
(() => {
  const pages = new Set(['content', 'facts', 'projects', 'launches', 'xrank', 'hn', 'about']);
  // Search text stays in memory, not in the URL captured by third-party analytics.
  window.signalSearch = '';
  const sanitizeSearch = () => {
    const url = new URL(location.href);
    const hashParts = url.hash.split('?');
    const hashParams = new URLSearchParams(hashParts[1] || '');
    if (hashParams.has('q') || url.searchParams.has('q')) {
      window.signalSearch = hashParams.get('q') || url.searchParams.get('q') || '';
      hashParams.delete('q');
      url.searchParams.delete('q');
      url.hash = hashParts[0] + (hashParams.size ? '?' + hashParams : '');
      history.replaceState(history.state, '', url.href);
    }
  };
  sanitizeSearch();
  window.addEventListener('popstate', sanitizeSearch);
  window.addEventListener('hashchange', sanitizeSearch);
  const production = location.hostname === 'nauyz.github.io' && location.pathname.startsWith('/personal-signal-desk/');
  if (!production) return;
  const blocked = navigator.globalPrivacyControl === true || navigator.doNotTrack === '1';
  if (blocked) return;
  const page = () => {
    const value = location.hash.split('?')[0].replace(/^#\//, '');
    return pages.has(value) ? value : 'content';
  };
  let ready = false, failed = false;
  const queue = [];
  const send = data => {
    if (failed) return;
    if (!ready) { if (queue.length < 100) queue.push(data); return; }
    try { window.goatcounter.count(data); } catch { /* analytics must never break navigation */ }
  };
  // Do not let default SDK fields pick up search text or full referrer URLs.
  let referrer = '';
  try { referrer = new URL(document.referrer).origin; } catch { /* direct visit */ }
  window.goatcounter = {no_onload: true, no_events: true, endpoint: 'https://zya119.goatcounter.com/count'};
  const track = name => send({path: name, title: name, event: true, no_session: true, referrer: ''});
  const view = name => send({path: '/' + name, title: name, event: false, referrer});
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://gc.zgo.at/count.js';
  script.dataset.goatcounter = window.goatcounter.endpoint;
  script.referrerPolicy = 'no-referrer';
  script.onload = () => {
    if (typeof window.goatcounter.count !== 'function') { failed = true; queue.length = 0; return; }
    ready = true;
    queue.splice(0).forEach(send);
  };
  script.onerror = () => { failed = true; queue.length = 0; };
  document.head.appendChild(script);
  document.addEventListener('click', event => {
    const target = event.target.closest('a,button,summary');
    if (!target) return;
    if (target.dataset.nav && pages.has(target.dataset.nav)) track('nav_' + target.dataset.nav);
    else if (target.matches('[data-filter] button')) {
      const dimension = target.parentElement.dataset.filter;
      const value = target.dataset.value;
      if (['category', 'topic', 'form', 'entity'].includes(dimension) && /^[a-z0-9-]{1,50}$/.test(value)) track('filter_' + dimension + '_' + value);
    } else if (target.matches('[data-scope]')) track('content_scope_' + (target.dataset.scope === 'selected' ? 'selected' : 'all'));
    else if (target.matches('summary')) track('expand_options_' + page());
    else if (target.matches('a[target="_blank"]')) {
      try {
        const destination = new URL(target.href);
        if (['http:', 'https:'].includes(destination.protocol)) track(('outbound_' + page() + ':' + destination.hostname + destination.pathname).slice(0, 190));
      } catch { /* invalid link */ }
    } else if (target.matches('button')) {
      const control = Object.entries(target.dataset).find(([key, value]) => /^(phRange|phCategory|hnView|hnScope|hnSort|xKind|xRange|xBoard|xTopicSort|xSort|xFilter)$/.test(key) && /^[a-z0-9-]{0,50}$/.test(value));
      track('control_' + page() + (control ? '_' + control[0] + '_' + (control[1] || 'all') : '_retry'));
    }
  }, true);
  let lastPage = page();
  let elapsed = 0, lastTick = performance.now(), visible = !document.hidden;
  const milestones = new Set();
  const tick = () => {
    const now = performance.now();
    if (visible) elapsed += Math.max(0, now - lastTick);
    lastTick = now;
    for (const seconds of [15, 30, 60]) {
      if (elapsed >= seconds * 1000 && !milestones.has(seconds)) {
        milestones.add(seconds);
        track('dwell_' + lastPage + '_' + seconds + 's');
      }
    }
  };
  const trackPage = () => {
    const next = page();
    if (next !== lastPage) {
      tick();
      lastPage = next;
      elapsed = 0;
      milestones.clear();
      view(next);
    }
  };
  window.addEventListener('hashchange', trackPage);
  window.addEventListener('signal-page', trackPage);
  window.addEventListener('signal-search', () => track('content_search'));
  document.addEventListener('visibilitychange', () => {
    tick();
    visible = !document.hidden;
  });
  window.addEventListener('pagehide', () => { tick(); visible = false; });
  window.addEventListener('pageshow', () => { lastTick = performance.now(); visible = !document.hidden; });
  setInterval(tick, 1000);
  view(lastPage);
})();
