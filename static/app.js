const app = document.querySelector('#app');
const syncLabel = document.querySelector('#sync-label');

const FILTERS = {
  category: { label: '主分类', values: { 'ai-models': '模型', 'ai-products': '产品', industry: '行业', paper: '论文', tutorial: '教程', opinion: '观点' } },
  topic: { label: '技术方向', values: { agent: '智能体', multimodal: '多模态', rag: 'RAG', 'data-training': '数据与训练', safety: '安全与对齐', embodied: '具身智能', other: '其他' } },
  form: { label: '内容形态', values: { official: '官方发布', news: '新闻报道', research: '论文研究', tutorial: '教程实践', opinion: '观点评论', benchmark: '评测基准', video: '视频', podcast: '播客', repository: '开源仓库', other: '其他' } },
  entity: { label: '公司与模型', values: { openai: 'OpenAI', anthropic: 'Anthropic', google: 'Google', meta: 'Meta', microsoft: 'Microsoft', nvidia: 'NVIDIA', gpt: 'GPT', claude: 'Claude', gemini: 'Gemini', qwen: 'Qwen', other: '其他' } },
};

const state = { page: pageFromPath(), meta: null, content: [], total: 0, lastSyncAt: null, checkingSync: false };

function pageFromPath() {
  const path = location.pathname.replace(/^\//, '').split('/')[0];
  return ['facts', 'content', 'projects', 'launches', 'xrank', 'hn', 'about'].includes(path) ? path : 'content';
}

function escapeHTML(value = '') {
  return String(value).replace(/[—–]/g, '-').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function safeURL(value = '') {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? escapeHTML(url.href) : '#';
  } catch { return '#'; }
}

function formatTime(value, full = false) {
  if (!value) return '时间未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '时间未知';
  return new Intl.DateTimeFormat('zh-CN', full ? { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' } : { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date);
}

function relativeTime(value) {
  if (!value) return '时间未知';
  const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
  const ranges = [[86400, 'day'], [3600, 'hour'], [60, 'minute']];
  for (const [size, unit] of ranges) if (Math.abs(seconds) >= size) return new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' }).format(Math.round(seconds / size), unit);
  return '刚刚';
}

function pageHeader(title, description, meta = '', action = '') {
  return `<header class="page-masthead">
    <div class="page-heading"><h1>${escapeHTML(title)}</h1><p>${escapeHTML(description)}${state.snapshotFallback ? ' 本轮获取失败，展示已有快照；获取时间见右侧。' : ''}</p></div>
    <div class="page-context">${meta ? `<span>${meta}</span>` : ''}${action}</div>
  </header>`;
}

async function api(path, options) {
  if (window.cloudAPI) {
    const data = await window.cloudAPI(path);
    if (!path.startsWith('/api/meta')) state.snapshotFallback = !!data.fallback;
    return data;
  }
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok && response.status !== 207) throw new Error(data.error || data.message || `请求失败 ${response.status}`);
  return data;
}

function setActiveNav() {
  document.querySelectorAll('[data-nav]').forEach(link => {
    const active = link.dataset.nav === state.page;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  document.querySelector('.mobile-more')?.classList.toggle('active', ['hn', 'about'].includes(state.page));
}

function navigate(page, push = true) {
  state.page = page;
  if (push) history.pushState({}, '', `/${page}`);
  setActiveNav();
  render().then(() => app.focus({ preventScroll: true }));
}

document.addEventListener('click', event => {
  const link = event.target.closest('a[data-nav]');
  if (!link || event.metaKey || event.ctrlKey) return;
  event.preventDefault();
  navigate(link.dataset.nav);
});
window.addEventListener('popstate', () => { state.page = pageFromPath(); setActiveNav(); render(); });

function updateSyncLabel() {
  const states = state.meta?.sync || [];
  const successful = states.filter(item => item.last_status !== 'error').sort((a, b) => String(b.last_synced_at).localeCompare(String(a.last_synced_at)))[0];
  const failed = states.some(item => item.last_status === 'error');
  syncLabel.parentElement.classList.toggle('error', failed && !successful);
  state.lastSyncAt = successful?.last_synced_at || null;
  const syncMode = state.meta?.cloud ? '云端定时更新' : state.meta?.autoSync?.enabled ? '每 30 分钟自动同步' : '本地缓存 · 同步已暂停';
  syncLabel.textContent = successful ? `${syncMode} · ${relativeTime(successful.last_synced_at)}更新` : syncMode;
}

function toast(message) {
  document.querySelector('.toast')?.remove();
  const node = document.createElement('div');
  node.className = 'toast';
  node.textContent = message;
  document.body.append(node);
  setTimeout(() => node.remove(), 4200);
}

async function checkAutomaticSync() {
  if (state.checkingSync || document.hidden) return;
  state.checkingSync = true;
  try {
    const previous = state.lastSyncAt;
    state.meta = await api('/api/meta');
    updateSyncLabel();
    if (previous && state.lastSyncAt && previous !== state.lastSyncAt) {
      const scrollTop = window.scrollY;
      await render();
      requestAnimationFrame(() => window.scrollTo({ top: scrollTop }));
      toast('已载入最新一轮同步数据');
    }
  } catch {
    // A temporary status request failure must not replace the currently visible data.
  } finally {
    state.checkingSync = false;
  }
}

function tagsByDimension(item, dimension) {
  return (item.tags || []).filter(tag => tag.dimension === dimension);
}

function contentCard(item) {
  const cat = FILTERS.category.values[item.category] || '其他';
  const tagLabels = [...tagsByDimension(item, 'technology'), ...tagsByDimension(item, 'entity')].filter(tag => tag.slug !== 'other').slice(0, 2);
  return `<article class="card content-card">
    <div class="card-kicker"><span class="pill ${item.selected ? 'selected' : ''}">${item.selected ? 'AIHOT 精选' : escapeHTML(cat)}</span><span>AI 评分 ${item.score ?? '无'}</span></div>
    <h3>${escapeHTML(item.title)}</h3>
    ${item.original_title && item.original_title !== item.title ? `<p class="original-title">${escapeHTML(item.original_title)}</p>` : ''}
    <p class="summary">${escapeHTML(item.summary || item.original_title || 'AIHOT 暂未提供摘要。')}</p>
    <div class="card-meta"><span>${escapeHTML(item.source_name || '信源未知')}</span>${tagLabels.map(tag => `<span>${escapeHTML(tag.label)}</span>`).join('')}</div>
    ${item.reason ? `<div class="digest"><b>推荐理由</b><br>${escapeHTML(item.reason)}</div>` : ''}
    <div class="card-links"><a href="${safeURL(item.aihot_url)}" target="_blank" rel="noopener">AIHOT 阅读 ↗</a><a href="${safeURL(item.original_url)}" target="_blank" rel="noopener">第三方原文 ↗</a></div>
  </article>`;
}

function contentMoment(item) {
  const value = item.published_at || item.discovered_at;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return { key: 'unknown', date: '时间未知', clock: '--:--', value: '' };
  const options = { timeZone: 'Asia/Shanghai' };
  const day = new Intl.DateTimeFormat('zh-CN', { ...options, month: 'long', day: 'numeric' }).format(date);
  const weekday = new Intl.DateTimeFormat('zh-CN', { ...options, weekday: 'long' }).format(date);
  return {
    key: new Intl.DateTimeFormat('zh-CN', { ...options, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date),
    date: `${day} · ${weekday}`,
    clock: new Intl.DateTimeFormat('zh-CN', { ...options, hour: '2-digit', minute: '2-digit', hour12: false }).format(date),
    value,
  };
}

function contentTimeline(items) {
  const groups = new Map();
  items.forEach(item => {
    const moment = contentMoment(item);
    if (!groups.has(moment.key)) groups.set(moment.key, { label: moment.date, items: [] });
    groups.get(moment.key).items.push({ item, moment });
  });
  return [...groups.values()].map(group => `<section class="timeline-group">
    <header class="timeline-date"><h2>${escapeHTML(group.label)}</h2><span>${group.items.length} 条</span></header>
    <div class="timeline-list">${group.items.map(({ item, moment }) => `<div class="timeline-entry"><time datetime="${escapeHTML(moment.value)}">${escapeHTML(moment.clock)}</time><i aria-hidden="true"></i>${contentCard(item)}</div>`).join('')}</div>
  </section>`).join('');
}

function factCard(item, index = 0) {
  const status = item.status === 'settled' ? '事件已稳定' : item.status === 'active' ? '持续更新' : '多源报道';
  return `<article class="card fact-card ${index === 0 ? 'is-leading' : ''}"><span class="rank">${String(item.rank || '无').padStart(2, '0')}</span>
    <div class="card-kicker"><span class="pill">${escapeHTML(status)}</span><span>${relativeTime(item.latest_at)}</span></div>
    <h3>${escapeHTML(item.title)}</h3>
    <div class="fact-signals"><span class="pill">${item.source_count ?? 0} 个独立信源</span><span class="pill">${item.signal_count ?? 0} 个讨论信号</span></div>
    ${item.digest ? `<div class="digest"><b>AIHOT 综述</b><br>${escapeHTML(item.digest)}</div>` : ''}
    <div class="card-meta"><span>代表信源：${escapeHTML(item.representative_source || '未知')}</span></div>
    <div class="card-links"><a href="${safeURL(item.story_url)}" target="_blank" rel="noopener">查看事件综述 ↗</a><a href="${safeURL(item.original_url)}" target="_blank" rel="noopener">查看原始内容 ↗</a></div>
  </article>`;
}

function empty() { return document.querySelector('#empty-template').innerHTML; }

async function renderFacts() {
  const data = await api('/api/facts');
  const latest = data.items[0]?.latest_at;
  const sync = state.meta?.sync?.find(item => item.resource === 'hot-topics');
  const failed = sync?.last_status === 'error';
  const checked = ['ok', 'not-modified'].includes(sync?.last_status);
  const title = failed ? '热点榜暂时未能更新' : checked ? '当前暂无达到榜单门槛的热点事件' : '热点榜暂时没有可展示的数据';
  const detail = failed ? '本次未能获取 AIHOT 热点榜，后续采集会再次尝试。你可以先浏览内容。' : checked ? '这里展示 AIHOT 过去 48 小时内达到热度门槛的事件。当前榜单为空，不代表没有新的 AI 动态。' : '获取到热点榜后，事件会显示在这里。你可以先浏览内容。';
  app.innerHTML = `${pageHeader('事实', 'AIHOT 过去 48 小时的热点事件，按报道与讨论热度筛选。', latest ? `榜单最近信号　<strong>${escapeHTML(formatTime(latest, true))}</strong>` : '当前热点　<strong>0 个事件</strong>')}
    ${data.items.length ? `<section class="grid fact-grid">${data.items.map(factCard).join('')}</section>` : `<section class="empty facts-empty" aria-labelledby="facts-empty-title"><h2 id="facts-empty-title">${title}</h2><p>${detail}</p><a data-nav="content" href="${state.meta?.cloud ? '#/content' : '/content'}">去看内容</a></section>`}`;
}

function getContentState() {
  const params = new URLSearchParams(location.search);
  const result = { scope: params.get('scope') === 'selected' ? 'selected' : 'all', q: params.get('q') || '' };
  Object.keys(FILTERS).forEach(key => result[key] = (params.get(key) || '').split(',').filter(Boolean));
  return result;
}

function contentQuery(filters) {
  const params = new URLSearchParams();
  if (filters.scope === 'selected') params.set('scope', 'selected');
  if (filters.q) params.set('q', filters.q);
  Object.keys(FILTERS).forEach(key => { if (filters[key].length) params.set(key, filters[key].join(',')); });
  params.set('limit', '120');
  return params;
}

function updateContentURL(filters) {
  const params = contentQuery(filters);
  params.delete('limit');
  history.replaceState({}, '', `/content${params.size ? `?${params}` : ''}`);
}

function filterRow(key, config, selected) {
  return `<div class="filter-row"><b>${escapeHTML(config.label)}</b><div class="filter-options" data-filter="${key}"><button data-value="all" aria-pressed="${!selected.length}" class="${selected.length ? '' : 'active'}">全部</button>${Object.entries(config.values).map(([value, label]) => `<button data-value="${value}" aria-pressed="${selected.includes(value)}" class="${selected.includes(value) ? 'active' : ''}">${escapeHTML(label)}</button>`).join('')}</div></div>`;
}

async function renderContent() {
  const filters = getContentState();
  const data = await api(`/api/content?${contentQuery(filters)}`);
  state.content = data.items;
  state.total = data.page.total;
  const chips = [];
  if (filters.scope === 'selected') chips.push({ key: 'scope', value: 'selected', label: '仅看精选' });
  Object.entries(FILTERS).forEach(([key, config]) => filters[key].forEach(value => chips.push({ key, value, label: config.values[value] || value })));
  const filterEntries = Object.entries(FILTERS);
  app.innerHTML = `${pageHeader('内容', '在同一个内容池中切换全部与精选，再按四个维度交叉筛选。', `当前显示　<strong>${Math.min(data.items.length, 120)} / ${data.page.total}</strong>`)}
    <section class="filters"><div class="filter-toolbar"><div class="scope-switch" aria-label="内容范围"><button data-scope="all" aria-pressed="${filters.scope === 'all'}" class="${filters.scope === 'all' ? 'active' : ''}">全部内容</button><button data-scope="selected" aria-pressed="${filters.scope === 'selected'}" class="${filters.scope === 'selected' ? 'active' : ''}">仅看精选</button></div><input class="search" id="search" value="${escapeHTML(filters.q)}" placeholder="搜索标题、摘要或信源" aria-label="搜索内容"></div>
    ${filterRow(filterEntries[0][0], filterEntries[0][1], filters[filterEntries[0][0]])}
    <details class="advanced-filters" ${chips.some(chip => ['topic', 'form', 'entity'].includes(chip.key)) ? 'open' : ''}><summary>更多筛选 <span>技术方向 · 内容形态 · 公司与模型</span></summary><div class="advanced-filter-body">${filterEntries.slice(1).map(([key, config]) => filterRow(key, config, filters[key])).join('')}</div></details>
    <div class="selection-summary"><span>已选条件</span>${chips.length ? chips.map(chip => `<button data-remove="${chip.key}" data-value="${chip.value}">${escapeHTML(chip.label)} ×</button>`).join('') : '<span>无，正在查看全部内容</span>'}${chips.length || filters.q ? '<button class="clear-filters" data-clear-filters>清除全部</button>' : ''}</div></section>
    <div class="results-head"><span><strong>${data.page.total}</strong> 条结果</span><span>按发布时间从新到旧 · 当前载入 ${data.items.length} 条</span></div>
    ${data.items.length ? `<section class="content-timeline">${contentTimeline(data.items)}</section>` : empty()}`;

  app.querySelectorAll('[data-scope]').forEach(button => button.addEventListener('click', () => { filters.scope = button.dataset.scope; updateContentURL(filters); renderContent(); }));
  app.querySelectorAll('[data-filter] button').forEach(button => button.addEventListener('click', () => {
    const key = button.parentElement.dataset.filter;
    const value = button.dataset.value;
    if (value === 'all') filters[key] = [];
    else filters[key] = filters[key].includes(value) ? filters[key].filter(item => item !== value) : [...filters[key], value];
    updateContentURL(filters); renderContent();
  }));
  app.querySelectorAll('[data-remove]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.remove === 'scope') filters.scope = 'all';
    else filters[button.dataset.remove] = filters[button.dataset.remove].filter(value => value !== button.dataset.value);
    updateContentURL(filters); renderContent();
  }));
  app.querySelector('[data-clear-filters]')?.addEventListener('click', () => {
    filters.scope = 'all'; filters.q = '';
    Object.keys(FILTERS).forEach(key => { filters[key] = []; });
    updateContentURL(filters); renderContent();
  });
  let searchTimer;
  app.querySelector('#search').addEventListener('input', event => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { filters.q = event.target.value.trim(); updateContentURL(filters); renderContent(); }, 350);
  });
}

async function renderAbout() {
  app.innerHTML = `${pageHeader('说明', '说明数据从哪里来、本地做了什么，以及哪些边界不会越过。')}
  <section class="about-layout">
    <article class="about-card full"><p class="eyebrow">信息分层</p><h2>事实与内容，刻意分开</h2><p>事实回答“发生了什么”，内容回答“谁具体发布了什么”。第一阶段不建立二者的本地对应关系，因此不会因为多篇内容谈论同一事件就错误删除它们。</p><div class="layer-visual"><div class="layer-box"><b>事实层</b><span>只取 AIHOT 过去 48 小时 Top 10 热点事件，保留状态、综述、独立信源数与核对入口。</span></div><span class="layer-gap">≠</span><div class="layer-box"><b>内容层</b><span>文章、推文、论文、视频各自独立保存；全量与精选共用四组交叉筛选。</span></div></div></article>
    <article class="about-card"><p class="eyebrow">本地处理</p><h2>本地补充了什么</h2><ul><li>公司与模型、技术方向、内容形态关键词标签</li><li>AIHOT 的 tip 本地细分为教程或观点</li><li>相同 ID、规范化 URL、平台 ID、精确文本指纹硬去重</li><li>副本 URL 和来源保存在 aliases 中，不物理删除</li></ul></article>
    <article class="about-card"><p class="eyebrow">来源边界</p><h2>来源与许可</h2><p>AIHOT 与 Product Hunt 数据仅用于个人非商业信息入口，并保留原始署名与回链。技术可访问不等于任意再分发许可；公开或商业上线前，需要重新确认并取得相应授权。</p><p><a href="https://aihot.virxact.com/terms" target="_blank" rel="noopener">AIHOT 规则 ↗</a>　<a href="https://api.producthunt.com/v2/docs" target="_blank" rel="noopener">Product Hunt API 规则 ↗</a></p></article>
    <article class="about-card full"><p class="eyebrow">去重原则</p><h2>这里不会把“同一件事”误当成“同一段内容”</h2><p>同一段内容的重复副本会合并展示；同一事件的官方公告、媒体报道、分析文章和后续进展则分别保留。无法确定时，一律保留。</p></article>
  </section>`;
}

function numberLabel(value) {
  return value == null ? '未知' : new Intl.NumberFormat('zh-CN').format(value);
}

const PROJECT_DESCRIPTIONS_ZH = Object.freeze({
  'fmtlib/fmt': '一个现代化的文本格式化库。',
  'mattpocock/skills': '真正面向工程实践的 Agent 技能合集，直接整理自作者自己的 .agents 目录。',
  'NousResearch/hermes-agent': '一个会随着你的使用不断成长的智能体。',
  'DietrichGebert/ponytail': '让 AI 智能体像经验丰富又惜字如金的资深开发者一样思考：能不写的代码，就是最好的代码。',
  'anthropics/skills': 'Anthropic 公开的 Agent Skills 仓库。',
  'affaan-m/ECC': '面向 AI 编程智能体的性能优化体系，涵盖技能、习惯、记忆、安全与研究优先的开发方法，适配 Claude Code、Codex 等工具。',
  'JuliusBrussee/caveman': '一个用“穴居人式”极简表达减少 Claude Code Token 消耗的技能，号称可节省 65%。',
  'blader/humanizer': '用来消除文本中 AI 写作痕迹的 Agent 技能。',
  'google-research/timesfm': 'Google Research 开发的预训练时间序列基础模型，用于时间序列预测。',
  'averygan/reclip': '轻量、可自托管的视频下载工具，配有简洁的网页界面，可从大多数网站下载视频。',
  'bannedbook/fanqiang': '提供翻墙与科学上网相关内容。',
  'addyosmani/agent-skills': '面向 AI 编程智能体的生产级工程技能合集。',
  'ByteByteGoHq/system-design-101': '用图解和浅显语言讲清复杂系统，帮助准备系统设计面试。',
  'magnitudedev/magnitude': '开源本地推理服务器，可根据你的硬件运行合适的本地模型，并接入现有的智能体工具。',
  'Imbad0202/academic-research-skills': '为 Claude Code 准备的学术研究技能，覆盖研究、写作、评审、修改到定稿的完整流程。',
  'Gitlawb/openclaude': '可在各种环境中运行，也能接入不同工具。',
  'debpalash/VoiceStudio': '完全本地运行的开源 ElevenLabs 替代方案，支持声音克隆、声音设计、视频配音、听写、转录和有声书制作，覆盖 646 种语言。',
  'f/prompts.chat': '原 Awesome ChatGPT Prompts；用于分享、发现和收藏社区提示词，支持免费开源、自托管和组织内私有部署。',
  'obra/superpowers': '一套可以实际落地的智能体技能框架与软件开发方法论。',
});

function projectCard(item) {
  const descriptionZh = item.description_zh || PROJECT_DESCRIPTIONS_ZH[item.full_name] || '';
  return `<article class="project-card"><span class="project-rank">${String(item.rank).padStart(2, '0')}</span><div class="project-main">
    <div class="project-title"><a href="${safeURL(item.repo_url)}" target="_blank" rel="noopener">${escapeHTML(item.full_name)}</a>${item.stars_today != null ? `<strong>今日 +${numberLabel(item.stars_today)} ★</strong>` : ''}</div>
    <div class="project-description"><span>项目简介</span><div class="project-description-copy"><p>${escapeHTML(item.description || '该项目暂未提供简介。')}</p>${descriptionZh ? `<p class="project-description-zh">${escapeHTML(descriptionZh)}</p>` : ''}</div></div>
    <div class="project-meta">${item.language ? `<span>${escapeHTML(item.language)}</span>` : ''}<span>${numberLabel(item.stars_total)} Stars</span><span>${numberLabel(item.forks_total)} Forks</span><a href="${safeURL(item.repo_url)}" target="_blank" rel="noopener">打开 GitHub ↗</a></div>
  </div></article>`;
}

async function renderProjects() {
  const data = await api('/api/projects');
  const snapshot = data.snapshot;
  app.innerHTML = `${pageHeader('项目', 'GitHub Trending 每日热门项目，保留英文简介与自然中文说明。', `最近获取　<strong>${snapshot ? formatTime(snapshot.fetched_at, true) : '暂无数据'}</strong>`, '<a class="source-button" href="https://github.com/trending" target="_blank" rel="noopener">打开 GitHub Trending ↗</a>')}
    ${data.items.length ? `<section class="project-list">${data.items.map(projectCard).join('')}</section>` : empty()}`;
}

const PRODUCTHUNT_RANGES = { today: '今日', yesterday: '昨日', '7d': '近 7 日', '30d': '近 30 日' };

function getProductHuntRange() {
  const value = new URLSearchParams(location.search).get('range');
  return PRODUCTHUNT_RANGES[value] ? value : 'today';
}

function productHuntCard(item) {
  const productURL = item.url || 'https://www.producthunt.com/';
  const score = item.votes_count != null
    ? `<strong>▲ ${numberLabel(item.votes_count)}</strong>`
    : item.reviews_rating
      ? `<strong>★ ${escapeHTML(String(item.reviews_rating))}</strong>`
      : '';
  const activity = item.comments_count != null
    ? `${numberLabel(item.comments_count)} 条评论`
    : item.reviews_count != null
      ? `${numberLabel(item.reviews_count)} 条评价`
      : '';
  return `<article class="ph-card">
    <span class="ph-rank">${String(item.rank).padStart(2, '0')}</span>
    <a class="ph-icon" href="${safeURL(productURL)}" target="_blank" rel="noopener" aria-label="在 Product Hunt 查看 ${escapeHTML(item.name)}">${item.thumbnail_url ? `<img src="${safeURL(item.thumbnail_url)}" alt="" loading="lazy">` : '<span>PH</span>'}</a>
    <div class="ph-main">
      <div class="ph-title"><h2><a href="${safeURL(productURL)}" target="_blank" rel="noopener">${escapeHTML(item.name)}</a></h2></div>
      <div class="ph-description"><p>${escapeHTML(item.tagline || 'Product Hunt 暂未提供简介。')}</p>${item.tagline_zh ? `<p class="ph-description-zh">${escapeHTML(item.tagline_zh)}</p>` : ''}</div>
      <div class="ph-meta">${(item.topics || []).slice(0, 4).map(topic => `<span>${escapeHTML(topic)}</span>`).join('')}${activity ? `<span>${activity}</span>` : ''}</div>
    </div><aside class="ph-rail">${score}<a href="${safeURL(productURL)}" target="_blank" rel="noopener">打开 Product Hunt ↗</a></aside>
  </article>`;
}

async function renderProductHunt() {
  const range = getProductHuntRange();
  const requestedCategory = new URLSearchParams(location.search).get('category') || '';
  app.innerHTML = `<div class="loading-state" role="status" aria-live="polite"><span></span><p>正在读取 Product Hunt…</p></div>`;
  const query = new URLSearchParams({ range });
  if (requestedCategory) query.set('category', requestedCategory);
  const data = await api(`/api/launches?${query}`);
  const category = data.category || '';
  const tabs = `<div class="ph-range" aria-label="Product Hunt 时间范围">${Object.entries(PRODUCTHUNT_RANGES).map(([key, label]) => `<button data-ph-range="${key}" aria-pressed="${!requestedCategory && key === range}" class="${!requestedCategory && key === range ? 'active' : ''}">${label}</button>`).join('')}</div>`;
  const categoryTabs = `<div class="ph-categories" aria-label="Product Hunt 一级垂类">${(data.categories || []).map(item => `<button data-ph-category="${escapeHTML(item.key)}" aria-pressed="${item.key === category}" class="${item.key === category ? 'active' : ''}"><span>${escapeHTML(item.label_zh)}</span><small>${item.count || 20}</small></button>`).join('')}</div>`;
  const configNotice = !data.configured ? '<p class="ph-config">尚未在服务进程中配置 <code>PRODUCTHUNT_TOKEN</code>，配置并重启后会自动读取榜单。</p>' : '';
  const sourceURL = data.snapshot?.source_url || 'https://www.producthunt.com/';
  const modeLabel = category ? '官网垂类 Top reviewed · 每类20个' : '官方新品榜顺序';
  app.innerHTML = `${pageHeader('新品', 'Product Hunt 新发布与官方垂类榜单，保留产品原始简介和中文说明。', `${escapeHTML(modeLabel)}　<strong>${data.snapshot ? formatTime(data.snapshot.fetched_at, true) : '等待首次同步'}</strong>`, `<a class="source-button" href="${safeURL(sourceURL)}" target="_blank" rel="noopener">打开 Product Hunt ↗</a>`)}
  <section class="ph-controls"><div class="ph-filter-stack">${tabs}${categoryTabs}</div></section>${configNotice}<div class="results-head"><span><strong>${data.count}</strong> 个产品</span><span>英文原文 · 中文说明 · 官方回链</span></div>${data.items.length ? `<section class="ph-list">${data.items.map(productHuntCard).join('')}</section>` : empty()}`;
  app.querySelectorAll('[data-ph-range]').forEach(button => button.addEventListener('click', () => {
    history.replaceState({}, '', `/launches?range=${button.dataset.phRange}`);
    renderProductHunt();
  }));
  app.querySelectorAll('[data-ph-category]').forEach(button => button.addEventListener('click', () => {
    const params = new URLSearchParams({ range });
    if (button.dataset.phCategory) params.set('category', button.dataset.phCategory);
    history.replaceState({}, '', `/launches?${params}`);
    renderProductHunt();
  }));
}

const HN_VIEWS = {
  news: { label: '热门', hint: 'HN 首页综合排名' },
  new: { label: '最新', hint: '全部投稿按时间' },
  show: { label: 'Show 热门', hint: '开发者作品综合排名' },
  shownew: { label: 'Show 最新', hint: '开发者作品按时间' },
  ask: { label: 'Ask 讨论', hint: '社区问题与经验' },
};
const HN_SORTS = { rank: '官方顺序', time: '按时间', score: '按分数', comments: '按评论' };

function getHNState() {
  const params = new URLSearchParams(location.search);
  const view = HN_VIEWS[params.get('view')] ? params.get('view') : 'news';
  const scope = params.get('scope') === 'all' ? 'all' : 'ai';
  const sort = HN_SORTS[params.get('sort')] ? params.get('sort') : 'rank';
  return { view, scope, sort };
}

function updateHNURL(next) {
  const params = new URLSearchParams({ view: next.view, scope: next.scope, sort: next.sort });
  history.replaceState({}, '', `/hn?${params}`);
}

function hnCard(item) {
  const hasSeparateOriginal = item.url && item.url !== item.hn_url;
  const titleZh = item.title_zh || '中文译文暂时不可用';
  return `<article class="hn-card">
    <span class="hn-rank">${String(item.rank).padStart(2, '0')}</span>
    <div class="hn-main">
      <div class="hn-title-row"><div class="hn-titles"><h2><a href="${safeURL(item.url)}" target="_blank" rel="noopener">${escapeHTML(item.title)}</a></h2><p class="hn-title-zh">${escapeHTML(titleZh)}</p></div>${item.is_ai ? '<span class="hn-ai">AI</span>' : ''}</div>
      ${item.text ? `<div class="hn-descriptions"><p class="hn-text">${escapeHTML(item.text)}</p><p class="hn-text-zh">${escapeHTML(item.text_zh || '中文译文暂时不可用')}</p></div>` : '<p class="hn-no-description">HN 榜单未提供简介</p>'}
      <div class="hn-meta"><span>${escapeHTML(item.source_domain || 'news.ycombinator.com')}</span><span>${formatTime(item.published_at)}</span><span><b>${numberLabel(item.score)}</b> 分</span><span><b>${numberLabel(item.comments)}</b> 评论</span><span>by ${escapeHTML(item.author || 'unknown')}</span></div>
      <div class="hn-links">${hasSeparateOriginal ? `<a href="${safeURL(item.url)}" target="_blank" rel="noopener">阅读原文 ↗</a>` : ''}<a href="${safeURL(item.hn_url)}" target="_blank" rel="noopener">查看 HN 讨论 ↗</a></div>
    </div>
  </article>`;
}

async function renderHackerNews() {
  const current = getHNState();
  app.innerHTML = `<div class="loading-state" role="status" aria-live="polite"><span></span><p>正在读取 Hacker News…</p></div>`;
  const data = await api(`/api/hn?view=${encodeURIComponent(current.view)}&scope=${encodeURIComponent(current.scope)}&sort=${encodeURIComponent(current.sort)}`);
  const snapshot = data.snapshot;
  app.innerHTML = `${pageHeader('HN', 'Hacker News 热门讨论与开发者新作品，可切换仅看 AI 或完整列表。', `${escapeHTML(HN_VIEWS[current.view].hint)}　<strong>${snapshot ? formatTime(snapshot.fetched_at, true) : '暂无数据'}</strong>`, `<a class="source-button" href="${safeURL(snapshot?.source_url || 'https://news.ycombinator.com/')}" target="_blank" rel="noopener">打开 Hacker News ↗</a>`)}
    <section class="hn-controls">
      <div class="hn-view-tabs" aria-label="Hacker News 页面">${Object.entries(HN_VIEWS).map(([key, value]) => `<button data-hn-view="${key}" aria-pressed="${key === current.view}" class="${key === current.view ? 'active' : ''}">${value.label}</button>`).join('')}</div>
      <div class="hn-scope" aria-label="内容范围"><button data-hn-scope="ai" aria-pressed="${current.scope === 'ai'}" class="${current.scope === 'ai' ? 'active' : ''}">仅看 AI</button><button data-hn-scope="all" aria-pressed="${current.scope === 'all'}" class="${current.scope === 'all' ? 'active' : ''}">全部内容</button></div>
      <div class="hn-sort" aria-label="排序方式">${Object.entries(HN_SORTS).map(([key, label]) => `<button data-hn-sort="${key}" aria-pressed="${key === current.sort}" class="${key === current.sort ? 'active' : ''}">${label}</button>`).join('')}</div>
    </section>
    <div class="results-head hn-results"><span><strong>${data.count}</strong> 条结果${current.scope === 'ai' ? ' · 本地 AI 识别' : ''}</span><span class="hn-fetched">英文原文 · 中文翻译</span></div>
    ${data.items.length ? `<section class="hn-list">${data.items.map(hnCard).join('')}</section>` : empty()}`;
  app.querySelectorAll('[data-hn-view]').forEach(button => button.addEventListener('click', () => { updateHNURL({ ...current, view: button.dataset.hnView, sort: 'rank' }); renderHackerNews(); }));
  app.querySelectorAll('[data-hn-scope]').forEach(button => button.addEventListener('click', () => { updateHNURL({ ...current, scope: button.dataset.hnScope }); renderHackerNews(); }));
  app.querySelectorAll('[data-hn-sort]').forEach(button => button.addEventListener('click', () => { updateHNURL({ ...current, sort: button.dataset.hnSort }); renderHackerNews(); }));
}

const XRANK = {
  tweets: { label: '推文', ranges: { '6h': '6 小时', '24h': '24 小时', '7d': '7 天' }, defaultRange: '24h' },
  creators: { label: '账号', ranges: { today: '今日', yesterday: '昨日', '7d': '7 日', '30d': '30 日' }, defaultRange: '7d' },
  topics: { label: '热点', ranges: { '24h': '24 小时', '7d': '7 日', all: '全部' }, defaultRange: '7d' },
};
const TWEET_BOARDS = { rising: '飙升起爆榜', hot: '最热曝光榜' };
const TOPIC_SORTS = { heat: '按热度', time: '按时间' };
const CREATOR_SORTS = { followers: '粉丝', growth: '涨粉', total_posts: '总帖', posts: '主帖', replies: '评论', views: '曝光', avg_views: '帖均曝光' };
const CREATOR_FILTERS = { all: '全部账号', lt_5k: '<5K', '5k_to_10k': '5K-1万', '10k_to_50k': '1万-5万', gt_50k: '>5万', frozen: '疑似冻结' };

function getXRankState() {
  const params = new URLSearchParams(location.search);
  const kind = XRANK[params.get('kind')] ? params.get('kind') : 'tweets';
  const config = XRANK[kind];
  const range = config.ranges[params.get('range')] ? params.get('range') : config.defaultRange;
  const sort = CREATOR_SORTS[params.get('sort')] ? params.get('sort') : 'followers';
  const filter = CREATOR_FILTERS[params.get('filter')] ? params.get('filter') : 'all';
  const board = TWEET_BOARDS[params.get('board')] ? params.get('board') : 'rising';
  const topicSort = TOPIC_SORTS[params.get('sort')] ? params.get('sort') : 'heat';
  const order = params.get('order') === 'asc' ? 'asc' : 'desc';
  return { kind, range, sort, filter, board, topicSort, order };
}

function updateXRankURL(kind, range, options = {}) {
  const params = new URLSearchParams({ kind, range });
  if (kind === 'creators') {
    params.set('sort', options.sort || 'followers');
    params.set('order', options.order || 'desc');
    if (options.filter && options.filter !== 'all') params.set('filter', options.filter);
  }
  if (kind === 'tweets') params.set('board', options.board || 'rising');
  if (kind === 'topics') params.set('sort', options.topicSort || 'heat');
  history.replaceState({}, '', `/xrank?${params}`);
}

function xRankSourceURL(snapshot, current) {
  const url = new URL(snapshot?.source_url || 'https://sopilot.net/zh/rank');
  if (current.kind === 'topics') url.searchParams.set('sort', current.topicSort);
  return url.href;
}

function xMetric(label, value) {
  return value == null ? '' : `<span><b>${numberLabel(value)}</b>${escapeHTML(label)}</span>`;
}

function xRankItem(item, kind) {
  if (kind === 'creators') {
    const url = `https://sopilot.net/zh/rank/creators/${encodeURIComponent(item.screenName || '')}`;
    return `<article class="xrank-card"><span class="xrank-number">${String(item._rank).padStart(2, '0')}</span><div><header><h2>${escapeHTML(item.name || item.screenName)}</h2><small>@${escapeHTML(item.screenName)}</small></header><p>${escapeHTML(item.description || '暂无账号简介。')}</p><div class="xrank-metrics">${xMetric('粉丝', item.followersCount)}${xMetric('涨粉', item.followerGain)}${xMetric('发帖', item.tweetCount)}${xMetric('篇均曝光', item.avgViewsPerTweet)}</div><a href="${safeURL(url)}" target="_blank" rel="noopener">在 SoPilot 查看 ↗</a></div></article>`;
  }
  if (kind === 'topics') {
    const url = `https://sopilot.net/zh/rank/topic/${encodeURIComponent(item.slug || '')}`;
    return `<article class="xrank-card xrank-topic"><span class="xrank-number">${String(item._rank).padStart(2, '0')}</span><div><header><h2>${escapeHTML(item.title)}</h2><small>AI 热点</small></header><p>${escapeHTML(item.summary || '暂无热点摘要。')}</p>${item.keywords?.length ? `<div class="xrank-keywords">${item.keywords.slice(0, 5).map(word => `<span>${escapeHTML(word)}</span>`).join('')}</div>` : ''}<div class="xrank-metrics">${xMetric('帖子', item.tweetCount)}${xMetric('创作者', item.authorCount)}${xMetric('曝光', item.totalViews)}${xMetric('热度', Math.round(item.heatScore || 0))}</div><a href="${safeURL(url)}" target="_blank" rel="noopener">查看热点详情 ↗</a></div></article>`;
  }
  const title = item.articleTitle || '';
  const board = TWEET_BOARDS[item._board] || '推文榜';
  return `<article class="xrank-card"><span class="xrank-number">${String(item._rank).padStart(2, '0')}</span><div><header><h2>${escapeHTML(title || item.authorName || item.screenName)}</h2><small>${board} · @${escapeHTML(item.screenName)}</small></header><p>${escapeHTML(item.text || '暂无内容摘要。')}</p><div class="xrank-metrics">${xMetric('曝光', item.viewsCount)}${xMetric('点赞', item.likesCount)}${xMetric('转帖', item.retweetsCount)}${xMetric('收藏', item.bookmarksCount)}</div><a href="${safeURL(item.sourceUrl)}" target="_blank" rel="noopener">打开原始内容 ↗</a></div></article>`;
}

function prepareCreatorItems(items, current) {
  const filters = {
    lt_5k: item => Number(item.followersCount || 0) < 5000,
    '5k_to_10k': item => Number(item.followersCount || 0) >= 5000 && Number(item.followersCount || 0) < 10000,
    '10k_to_50k': item => Number(item.followersCount || 0) >= 10000 && Number(item.followersCount || 0) <= 50000,
    gt_50k: item => Number(item.followersCount || 0) > 50000,
    frozen: item => Boolean(item.isFrozen),
  };
  const fields = { followers: 'followersCount', growth: 'followerGain', total_posts: 'statusesCount', posts: 'tweetCount', replies: 'replyCount', views: 'totalViews', avg_views: 'avgViewsPerTweet' };
  const filtered = current.filter === 'all' ? [...items] : items.filter(filters[current.filter]);
  const direction = current.order === 'asc' ? 1 : -1;
  return filtered.sort((a, b) => direction * (Number(a[fields[current.sort]] || 0) - Number(b[fields[current.sort]] || 0))).map((item, index) => ({ ...item, _rank: index + 1 }));
}

async function renderXRank() {
  const current = getXRankState();
  const config = XRANK[current.kind];
  app.innerHTML = `<div class="loading-state" role="status" aria-live="polite"><span></span><p>正在读取 SoPilot AI 榜单…</p></div>`;
  const data = await api(`/api/xrank?kind=${encodeURIComponent(current.kind)}&range=${encodeURIComponent(current.range)}`);
  const items = (current.kind === 'creators' ? prepareCreatorItems(data.items, current) : current.kind === 'tweets' ? data.items.filter(item => item._board === current.board).map((item, index) => ({ ...item, _rank: index + 1 })) : [...data.items].sort((a, b) => current.topicSort === 'time' ? new Date(b.updatedAt || 0) - new Date(a.updatedAt || 0) : Number(b.heatScore || 0) - Number(a.heatScore || 0)).map((item, index) => ({ ...item, _rank: index + 1 })));
  const creatorControls = current.kind === 'creators' ? `<div class="xrank-account-controls"><div class="xrank-option-row"><b>排序</b><div>${Object.entries(CREATOR_SORTS).map(([key, label]) => `<button data-x-sort="${key}" aria-pressed="${key === current.sort}" class="${key === current.sort ? 'active' : ''}">${label}${key === current.sort ? (current.order === 'desc' ? ' ↓' : ' ↑') : ''}</button>`).join('')}</div></div><div class="xrank-option-row"><b>过滤</b><div>${Object.entries(CREATOR_FILTERS).map(([key, label]) => `<button data-x-filter="${key}" aria-pressed="${key === current.filter}" class="${key === current.filter ? 'active' : ''}">${label}</button>`).join('')}</div></div></div>` : '';
  const tweetControls = current.kind === 'tweets' ? `<div class="xrank-board-controls"><b>推文榜单</b><div class="xrank-board-tabs" aria-label="推文榜单分类">${Object.entries(TWEET_BOARDS).map(([key, label]) => `<button data-x-board="${key}" aria-pressed="${key === current.board}" class="${key === current.board ? 'active' : ''}">${label}</button>`).join('')}</div></div>` : '';
  const topicControls = current.kind === 'topics' ? `<div class="xrank-board-controls"><b>排序</b><div class="xrank-board-tabs" aria-label="热点话题排序">${Object.entries(TOPIC_SORTS).map(([key, label]) => `<button data-x-topic-sort="${key}" aria-pressed="${key === current.topicSort}" class="${key === current.topicSort ? 'active' : ''}">${label}</button>`).join('')}</div></div>` : '';
  app.innerHTML = `${pageHeader('X 热榜', 'SoPilot 的 AI 领域推文、账号和热点榜单，保留原始排序与过滤维度。', `仅显示 AI 领域　<strong>${data.snapshot ? formatTime(data.snapshot.fetched_at, true) : '暂无数据'}</strong>`, `<a class="source-button" href="${safeURL(xRankSourceURL(data.snapshot, current))}" target="_blank" rel="noopener">打开 SoPilot ↗</a>`)}
  <section class="xrank-controls"><div class="xrank-tabs" aria-label="X 热榜分类">${Object.entries(XRANK).map(([key, value]) => `<button data-x-kind="${key}" aria-pressed="${key === current.kind}" class="${key === current.kind ? 'active' : ''}">${value.label}</button>`).join('')}</div><div class="xrank-range" aria-label="时间范围">${Object.entries(config.ranges).map(([key, label]) => `<button data-x-range="${key}" aria-pressed="${key === current.range}" class="${key === current.range ? 'active' : ''}">${label}</button>`).join('')}</div>${tweetControls}${topicControls}${creatorControls}</section><div class="results-head"><span><strong>${items.length}</strong> 条结果${current.kind === 'creators' && items.length !== data.count ? ` · 完整 AI 账号 ${data.count} 个` : ''}</span><span>完整分页抓取 · 仅显示 AI</span></div>${items.length ? `<section class="xrank-list">${items.map(item => xRankItem(item, current.kind)).join('')}</section>` : empty()}`;
  app.querySelectorAll('[data-x-kind]').forEach(button => button.addEventListener('click', () => { const kind = button.dataset.xKind; updateXRankURL(kind, XRANK[kind].defaultRange); renderXRank(); }));
  app.querySelectorAll('[data-x-range]').forEach(button => button.addEventListener('click', () => { updateXRankURL(current.kind, button.dataset.xRange, current); renderXRank(); }));
  app.querySelectorAll('[data-x-board]').forEach(button => button.addEventListener('click', () => { updateXRankURL('tweets', current.range, { ...current, board: button.dataset.xBoard }); renderXRank(); }));
  app.querySelectorAll('[data-x-topic-sort]').forEach(button => button.addEventListener('click', () => { updateXRankURL('topics', current.range, { ...current, topicSort: button.dataset.xTopicSort }); renderXRank(); }));
  app.querySelectorAll('[data-x-sort]').forEach(button => button.addEventListener('click', () => { const sort = button.dataset.xSort; const order = sort === current.sort && current.order === 'desc' ? 'asc' : 'desc'; updateXRankURL(current.kind, current.range, { ...current, sort, order }); renderXRank(); }));
  app.querySelectorAll('[data-x-filter]').forEach(button => button.addEventListener('click', () => { updateXRankURL(current.kind, current.range, { ...current, filter: button.dataset.xFilter }); renderXRank(); }));
}

async function render() {
  try {
    if (!state.meta) state.meta = await api('/api/meta');
    updateSyncLabel();
    if (state.page === 'facts') await renderFacts();
    else if (state.page === 'content') await renderContent();
    else if (state.page === 'projects') await renderProjects();
    else if (state.page === 'launches') await renderProductHunt();
    else if (state.page === 'xrank') await renderXRank();
    else if (state.page === 'hn') await renderHackerNews();
    else await renderAbout();
  } catch (error) {
    app.innerHTML = `<section class="error-state"><h1>页面暂时无法读取</h1><p>${escapeHTML(error.message)}</p><button class="retry-button" data-retry>重新读取</button></section>`;
    app.querySelector('[data-retry]')?.addEventListener('click', render);
  }
}

setActiveNav();
render().then(() => {
  setInterval(checkAutomaticSync, 60_000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) checkAutomaticSync(); });
});
