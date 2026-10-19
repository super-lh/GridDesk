/* ==========================================================================
   方块桌面 · GridDesk 前端
   ========================================================================== */
(() => {
  'use strict';

  /* ------------------------------------------------------------ 工具 */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
  const pad2 = (n) => String(n).padStart(2, '0');
  const debounce = (fn, ms) => {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  };

  const ICON = {
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.4"/><path d="M16.2 16.2L21 21"/></svg>',
    refresh: '<svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4.5V10h-5.4"/></svg>',
    settings: '<svg viewBox="0 0 24 24"><path d="M4 7h10"/><path d="M18 7h2"/><circle cx="16" cy="7" r="2"/><path d="M4 17h2"/><path d="M10 17h10"/><circle cx="8" cy="17" r="2"/><path d="M4 12h6"/><path d="M14 12h6"/><circle cx="12" cy="12" r="2"/></svg>',
    star: '<svg viewBox="0 0 24 24"><path d="M12 3.6l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 9.8l5.9-.9z"/></svg>',
    pin: '<svg viewBox="0 0 24 24"><path d="M9 3h6l-1 6 4 3v2h-5l-1 7-1-7H6v-2l4-3z"/></svg>',
    arrow: '<svg viewBox="0 0 24 24"><path d="M7 17L17 7"/><path d="M8 7h9v9"/></svg>',
    external: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="M20 4L11 13"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
    eyeOff: '<svg viewBox="0 0 24 24"><path d="M3 3l18 18"/><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.4 5.5A9.7 9.7 0 0 1 21 12a15 15 0 0 1-3 3.6"/><path d="M6.3 6.3A15 15 0 0 0 3 12a9.6 9.6 0 0 0 12.4 5.9"/></svg>',
    folder: '<svg viewBox="0 0 24 24"><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z"/></svg>',
    tag: '<svg viewBox="0 0 24 24"><path d="M3 11V4h7l10 10-7 7z"/><circle cx="7.5" cy="8" r="1.3"/></svg>',
    pencil: '<svg viewBox="0 0 24 24"><path d="M4 20l4.5-1 10-10a2 2 0 0 0-2.8-2.8l-10 10z"/><path d="M14 6l4 4"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M4.5 12.5l5 5 10-10"/></svg>',
    empty: '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><path d="M14 14h6v6"/></svg>',
  };

  const CAT_ORDER = ['浏览', 'AI', '社交', '影音', '办公', '开发', '设计', '游戏', '工具', '系统', '其他'];
  const SORT_LABEL = { custom: '自定义', name: '名称', recent: '最近', frequent: '常用' };

  /* ------------------------------------------------------------ 网络 */
  async function api(path, { method = 'GET', body } = {}) {
    const res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* ignore */ }
    if (!res.ok || (data && data.ok === false)) {
      throw new Error((data && (data.error || data.message)) || ('请求失败 ' + res.status));
    }
    return data || {};
  }

  /* ------------------------------------------------------------ 状态 */
  const S = {
    apps: [], settings: {}, scan: {}, cats: [], stats: {}, version: '', dataDir: '', user: '',
    view: 'all', category: '全部', focusId: null, menuApp: null,
    searchResults: [], searchIndex: 0, cols: 6, c: 3, tile: 220, gap: 12,
    visible: [], firstPaint: true, viewKey: '', pollTimer: null,
    dragging: null, launching: new Set(), wallpaper: null,
  };

  /* ------------------------------------------------------------ 启动 */
  document.addEventListener('DOMContentLoaded', boot);

  async function boot() {
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    bind();
    updateClock();
    setInterval(updateClock, 15000);
    setInterval(heartbeat, 5000);
    heartbeat();
    try {
      await load();
    } catch (e) {
      toast('连接本地服务失败：' + e.message, 'err');
    }
    document.body.classList.remove('booting');
    S.firstPaint = false;
    // 浏览器可能恢复上次的滚动位置，启动器应该始终回到顶部
    setTimeout(() => {
      const wrap = $('#gridWrap');
      if (wrap) wrap.scrollTop = 0;
      updateGridFade();
    }, 60);
  }

  async function load() {
    const data = await api('/api/bootstrap');
    apply(data);
    schedulePoll();
  }

  function apply(data) {
    S.apps = data.apps || [];
    S.settings = data.settings || {};
    S.scan = data.scan || {};
    S.cats = data.categories || [];
    S.stats = data.stats || {};
    S.version = data.version || '';
    S.dataDir = data.dataDir || '';
    S.user = data.user || '本地用户';
    S.wallpaper = data.wallpaper || null;
    document.documentElement.style.setProperty('--wall', S.wallpaper ? 'url("' + S.wallpaper + '")' : 'none');
    document.body.classList.toggle('no-wallpaper', !S.wallpaper || S.settings.background !== 'wallpaper');
    renderAll();
  }

  function renderAll() {
    renderRailCounts();
    renderHeader();
    renderChips();
    renderGrid();
    renderOpenedIcons();
    renderCorner();
    renderRecent();
    renderScanbar();
    syncSettings();
  }

  /* ------------------------------------------------------------ 数据 */
  const visibleApps = () => S.apps.filter((a) => !a.hidden);
  const appById = (id) => S.apps.find((a) => a.id === id);

  function currentList() {
    let list = visibleApps();
    if (S.view === 'categories' && S.category !== '全部') {
      list = list.filter((a) => a.category === S.category);
    }
    if (S.view === 'pinned') {
      list = list.filter((a) => a.pinned || a.launchCount > 0);
    }
    if (S.view === 'recent') {
      list = list.filter((a) => a.lastLaunch > 0);
    }
    return sortList(list);
  }

  function sortList(list) {
    const arr = list.slice();
    const mode = S.settings.sort || 'custom';
    if (S.view === 'recent') return arr.sort((a, b) => b.lastLaunch - a.lastLaunch);
    if (S.view === 'pinned') {
      return arr.sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0)
        || b.launchCount - a.launchCount
        || a.name.localeCompare(b.name, 'zh-Hans-CN'));
    }
    if (mode === 'name') return arr.sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
    if (mode === 'recent') return arr.sort((a, b) => b.lastLaunch - a.lastLaunch);
    if (mode === 'frequent') return arr.sort((a, b) => b.launchCount - a.launchCount);
    return arr; // 服务端已按自定义顺序返回
  }

  function relTime(ts) {
    if (!ts) return '从未打开';
    const diff = Date.now() / 1000 - ts;
    if (diff < 90) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
    if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' 天前';
    const d = new Date(ts * 1000);
    return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日';
  }

  function subtitleOf(a) {
    if (a.pinned) return a.launchCount ? '已固定 · 启动 ' + a.launchCount + ' 次' : '已固定';
    if (a.lastLaunch) return '上次 ' + relTime(a.lastLaunch);
    if (a.launchCount) return '启动 ' + a.launchCount + ' 次';
    return '';
  }

  /* ------------------------------------------------------------ 渲染：导航 */
  function renderRailCounts() {
    const counts = {
      all: S.stats.total || 0,
      pinned: visibleApps().filter((a) => a.pinned).length,
      recent: visibleApps().filter((a) => a.lastLaunch).length,
      categories: Math.max(0, S.cats.length - 1),
    };
    Object.keys(counts).forEach((key) => {
      const node = $('.rail-count[data-count="' + key + '"]');
      if (node) node.textContent = counts[key];
    });
  }

  function setView(view) {
    if (S.view === view) return;
    S.view = view;
    S.category = '全部';
    S.focusId = null;
    $$('#railNav .rail-item').forEach((b) => b.classList.toggle('is-active', b.dataset.view === view));
    renderHeader();
    renderChips();
    renderGrid();
  }

  function renderHeader() {
    const counts = {
      all: S.stats.total || 0,
      pinned: visibleApps().filter((a) => a.pinned).length,
      recent: visibleApps().filter((a) => a.lastLaunch).length,
    };
    let title = '全部';
    let sub = '';
    if (S.view === 'all') {
      sub = (S.stats.total || 0) + ' 个应用 · ' + Math.max(0, S.cats.length - 1) + ' 个分类';
    } else if (S.view === 'pinned') {
      title = '常用应用';
      sub = counts.pinned + ' 个已固定 · ' + (S.stats.launched || 0) + ' 个使用过';
    } else if (S.view === 'recent') {
      title = '最近打开';
      sub = (S.stats.launched || 0) + ' 个应用有打开记录';
    } else if (S.view === 'categories') {
      title = '分类浏览';
      const list = currentList().length;
      sub = S.category === '全部' ? (S.stats.total || 0) + ' 个应用，按分类筛选' : S.category + ' · ' + list + ' 个应用';
    }
    $('#viewTitle').textContent = title;
    $('#viewSub').textContent = sub;
  }

  function renderChips() {
    const box = $('#chips');
    const info = $('#viewInfo');
    const show = S.view === 'categories';
    box.hidden = !show;
    if (info) info.hidden = show;
    if (!show) return;
    box.innerHTML = S.cats.map((c) => (
      '<button class="chip' + (c.name === S.category ? ' is-active' : '') + '" data-cat="' + esc(c.name) + '">'
      + esc(c.name) + '<small>' + c.count + '</small></button>'
    )).join('');
  }

  /* ------------------------------------------------------------ 渲染：磁贴墙 */
  function isCornerVisible() {
    const card = $('#cornerCard');
    return !!card && getComputedStyle(card).display !== 'none';
  }

  function skeletonHTML(n) {
    const c = S.c;
    let html = '';
    for (let i = 0; i < n; i += 1) {
      const r = Math.floor(i / (c * 2));
      const col = i % (c * 2);
      const gridCol = col < c ? col + 1 : col + 2;
      html += '<div class="tile skeleton" style="--i:' + i + ';grid-column:' + gridCol
        + ';grid-row:' + (r + 1) + ';"></div>';
    }
    return html;
  }

  function tileHTML(app, index, place) {
    const span = place.span || 1;
    const isBig = span === 2;
    const gridCol = place.col < S.c ? place.col + 1 : place.col + 2;
    const chip = S.settings.showChips !== false
      ? '<span class="tile-chip">' + esc(app.category) + '</span>' : '';
    const pin = app.pinned ? '<span class="tile-pin">' + ICON.star + '</span>' : '';
    const subText = subtitleOf(app);
    const sub = (S.settings.showSubtitle !== false && subText)
      ? '<p class="tile-sub">' + esc(subText) + '</p>' : '';
    const cover = app.cover
      ? '<img class="tile-cover" src="' + app.cover + '" alt="" loading="lazy" draggable="false">'
      : '<div class="tile-cover tile-cover--empty"></div>';
    return '<article class="tile' + (isBig ? ' is-pinned' : '') + '" data-id="' + app.id + '"'
      + ' style="grid-column:' + gridCol + ' / span ' + span
      + ';grid-row:' + (place.r + 1) + ' / span ' + span
      + ';--accent:' + (app.accent || '#7aa2ff') + ';--i:' + Math.min(index, 30) + '"'
      + ' tabindex="0" role="button" aria-label="打开 ' + esc(app.name) + '">'
      + cover
      + '<div class="tile-grad"></div>'
      + chip + pin
      + '<div class="tile-foot"><h3 class="tile-name">' + esc(app.name) + '</h3>' + sub + '</div>'
      + '<div class="tile-open">打开 ' + ICON.arrow + '</div>'
      + '</article>';
  }

  /* 依次把应用排进左右两片墙：跳过中间竖栏和右上角卡片占用的格子 */
  function packTiles(list) {
    const c = S.c;
    const total = c * 2;
    const rows = [];
    const rowAt = (r) => {
      while (rows.length <= r) rows.push(new Array(total).fill(false));
      return rows[r];
    };
    if (isCornerVisible()) {
      const reserveRows = Math.max(1, S.cardRows || 1);
      for (let r = 0; r < reserveRows; r += 1) {
        const row = rowAt(r);
        row[total - 1] = true;
        row[total - 2] = true;
      }
    }
    const fits = (r, col, size) => {
      const sideEnd = col < c ? c : total;
      if (col + size > sideEnd) return false;
      for (let rr = r; rr < r + size; rr += 1) {
        const row = rowAt(rr);
        for (let cc = col; cc < col + size; cc += 1) if (row[cc]) return false;
      }
      return true;
    };
    const mark = (r, col, size) => {
      for (let rr = r; rr < r + size; rr += 1) {
        const row = rowAt(rr);
        for (let cc = col; cc < col + size; cc += 1) row[cc] = true;
      }
    };
    const collage = S.settings.layout === 'collage';
    return list.map((app) => {
      const size = collage && app.pinned ? 2 : 1;
      for (let r = 0; r < rows.length + 80; r += 1) {
        for (let col = 0; col < total; col += 1) {
          if (fits(r, col, size)) {
            mark(r, col, size);
            return { app, r, col, span: size };
          }
        }
      }
      return { app, r: 0, col: 0, span: 1 };
    });
  }

  function renderGrid() {
    const grid = $('#grid');
    const empty = $('#empty');
    if (!grid) return;
    const list = currentList();
    S.visible = list;
    applyLayout();
    const viewKey = [S.view, S.category, S.settings.layout, S.settings.sort,
      S.settings.showChips, S.settings.showSubtitle, list.map((a) => a.id).join(',')].join('|');
    const animate = viewKey !== S.viewKey;
    S.viewKey = viewKey;

    if (!S.apps.length && S.scan.running) {
      grid.classList.remove('no-anim');
      grid.innerHTML = skeletonHTML(S.c * 6);
      empty.hidden = true;
      updateGridFade();
      return;
    }
    if (!list.length) {
      grid.innerHTML = '';
      empty.hidden = false;
      empty.innerHTML = emptyHTML();
      bindEmpty();
      updateGridFade();
      return;
    }
    empty.hidden = true;
    const places = packTiles(list);
    grid.classList.toggle('no-anim', !animate);
    grid.innerHTML = places.map((p, i) => tileHTML(p.app, i, p)).join('');
    if (canReorder()) {
      $$('.tile', grid).forEach((tile) => { tile.draggable = true; });
    }
    updateGridFade();
  }

  function updateGridFade() {
    const wrap = $('#gridWrap');
    const fade = $('#gridFade');
    if (!wrap || !fade) return;
    const noScroll = wrap.scrollHeight <= wrap.clientHeight + 6;
    const atEnd = wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 24;
    fade.classList.toggle('is-hidden', noScroll || atEnd);
  }

  function emptyHTML() {
    const glyph = '<div class="empty-glyph">' + ICON.empty + '</div>';
    if (!S.apps.length) {
      return glyph + '<h3>还没有扫描到应用</h3><p>点下面的按钮重新扫描开始菜单、桌面和 Microsoft Store 应用。</p>'
        + '<button class="btn" id="emptyRescan">重新扫描</button>';
    }
    if (S.view === 'pinned') {
      return glyph + '<h3>还没有常用的应用</h3><p>右键任意应用 →「固定到常用」，它就会出现在这里；拼贴模式下固定的应用还会放大成 2×2。</p>';
    }
    if (S.view === 'recent') {
      return glyph + '<h3>还没有打开记录</h3><p>打开几个应用之后，这里会按最近使用时间自动排序。</p>';
    }
    if (S.view === 'categories') {
      return glyph + '<h3>这个分类下暂时没有应用</h3><p>换个分类看看，或在设置里重新扫描。</p>';
    }
    return glyph + '<h3>没有匹配的应用</h3><p>试试别的关键词，或者重新扫描应用列表。</p>';
  }

  function bindEmpty() {
    const btn = $('#emptyRescan');
    if (btn) btn.addEventListener('click', () => rescan(false));
  }

  function applyLayout() {
    const grid = $('#grid');
    const wrap = $('#gridWrap');
    const dock = $('#dock');
    if (!grid || !wrap) return;
    const width = wrap.clientWidth;
    const dockW = dock ? dock.offsetWidth : 76;
    const mode = S.settings.layout || 'collage';
    const compact = mode === 'compact';
    const gap = compact ? 8 : 10;
    const minTile = mode === 'collage' ? 200 : compact ? 128 : 205;
    let c = Math.floor((width - dockW + gap) / (2 * (minTile + gap)));
    c = Math.max(2, Math.min(5, c));
    if (S.settings.columns > 0 && !compact) {
      c = Math.max(2, Math.min(6, Math.round(Number(S.settings.columns) / 2)));
    }
    const tile = Math.max(110, (width - dockW - 2 * c * gap) / (2 * c));
    grid.style.setProperty('--c', c);
    grid.style.setProperty('--gap', gap + 'px');
    grid.style.setProperty('--tile', tile.toFixed(2) + 'px');
    grid.classList.toggle('layout-compact', compact);
    const cardRows = Math.max(1, Math.ceil(200 / (tile + gap)));
    const card = $('#cornerCard');
    if (card) {
      card.style.setProperty('--card-w', (2 * tile + gap).toFixed(2) + 'px');
      card.style.setProperty('--card-h', (cardRows * tile + (cardRows - 1) * gap).toFixed(2) + 'px');
    }
    S.c = c;
    S.cols = c * 2;
    S.tile = tile;
    S.gap = gap;
    S.cardRows = cardRows;
  }

  function canReorder() {
    const modal = $('#searchModal');
    return S.view === 'all'
      && (S.settings.sort || 'custom') === 'custom'
      && S.category === '全部'
      && (!modal || modal.hidden);
  }

  /* ------------------------------------------------------------ 渲染：底栏 / 竖栏 / 右上角 */
  /* 底部左侧：最近打开的应用（播放条样式） */
  function recentApp() {
    const list = visibleApps().filter((a) => a.lastLaunch);
    list.sort((a, b) => b.lastLaunch - a.lastLaunch);
    if (list.length) return list[0];
    const pinned = visibleApps().filter((a) => a.pinned);
    if (pinned.length) return pinned[0];
    return null;
  }

  function renderRecent() {
    const app = recentApp();
    S.recentId = app ? app.id : '';
    const cover = $('#recentCover');
    const label = $('#recentLabel');
    const name = $('#recentName');
    const sub = $('#recentSub');
    if (!cover || !name) return;
    if (!app) {
      cover.style.backgroundImage = 'none';
      label.textContent = '最近打开';
      name.textContent = '还没有打开过应用';
      sub.textContent = '单击磁贴打开，这里会记住最近用的应用';
      return;
    }
    cover.style.backgroundImage = app.cover ? 'url("' + app.cover + '")' : 'none';
    cover.style.backgroundColor = app.accent || 'rgba(255,255,255,0.06)';
    label.textContent = app.lastLaunch ? '最近打开' : '常用';
    name.textContent = app.name;
    const meta = subtitleOf(app);
    sub.textContent = meta ? meta : (app.category + ' · 单击重新打开');
  }

  function renderCorner() {
    const node = $('#cornerStats');
    if (!node) return;
    const pinned = visibleApps().filter((a) => a.pinned).length;
    const cats = Math.max(0, S.cats.length - 1);
    node.innerHTML = '<span>' + (S.stats.total || 0) + ' 个应用</span>'
      + '<span>' + cats + ' 个分类 · ' + pinned + ' 个固定</span>';
  }

  /* 中间竖栏：已打开应用（运行中 / 最近使用），只显示图标 */
  function openedApps() {
    return visibleApps().filter((a) => a.running || a.lastLaunch)
      .sort((a, b) => (b.running ? 1 : 0) - (a.running ? 1 : 0)
        || (b.lastLaunch || 0) - (a.lastLaunch || 0))
      .slice(0, 18);
  }

  function openedIconHTML(app) {
    const sub = app.running ? '运行中' : (app.lastLaunch ? '上次 ' + relTime(app.lastLaunch) : app.category);
    const img = app.icon
      ? '<img src="' + app.icon + '" alt="" loading="lazy" draggable="false">'
      : '<img src="/brand.png" alt="" loading="lazy" draggable="false">';
    return '<button class="opened-icon" data-id="' + app.id + '" title="' + esc(app.name + ' · ' + sub) + '">'
      + img + (app.running ? '<i class="dot"></i>' : '') + '</button>';
  }

  function renderOpenedIcons() {
    const box = $('#openedList');
    if (!box) return;
    const list = openedApps();
    box.innerHTML = list.length
      ? list.map(openedIconHTML).join('')
      : '<span class="opened-hint" title="打开应用后会出现在这里">＋</span>';
  }

  function renderScanbar() {
    const bar = $('#scanbar');
    const running = !!S.scan.running;
    bar.hidden = !running;
    if (!running) return;
    const total = S.scan.total || 0;
    const done = S.scan.done || 0;
    const pct = total ? Math.round((done / total) * 100) : 0;
    $('#scanFill').style.width = (total ? pct : 6) + '%';
    $('#scanText').textContent = S.scan.phase === 'listing'
      ? '正在读取开始菜单与 Store 应用…'
      : '正在生成图标与封面 ' + done + ' / ' + total;
    $('#scanPct').textContent = total ? pct + '%' : '';
  }

  /* ------------------------------------------------------------ 设置面板 */
  function syncSettings() {
    const s = S.settings;
    $$('#layoutSeg button').forEach((b) => b.classList.toggle('is-active', b.dataset.layout === (s.layout || 'square')));
    $$('#setLayout button').forEach((b) => b.classList.toggle('is-active', b.dataset.value === (s.layout || 'square')));
    $$('#setColumns button').forEach((b) => b.classList.toggle('is-active', Number(b.dataset.value) === Number(s.columns || 0)));
    $$('#setBg button').forEach((b) => b.classList.toggle('is-active', b.dataset.value === (s.background || 'wallpaper')));
    $$('#setLaunch button').forEach((b) => b.classList.toggle('is-active', b.dataset.value === (s.launchMode || 'single')));
    $$('#setWindow button').forEach((b) => b.classList.toggle('is-active', b.dataset.value === (s.windowMode || 'maximized')));
    $$('.switch[data-key]').forEach((sw) => sw.setAttribute('aria-checked', s[sw.dataset.key] ? 'true' : 'false'));
    const auto = $('#switchAutostart');
    if (auto) auto.setAttribute('aria-checked', s.autostart ? 'true' : 'false');
    $('#aboutVer').textContent = 'v' + (S.version || '0.1.0');
    $('#dataPath').textContent = S.dataDir ? '数据目录：' + S.dataDir : '';
    const avatar = $('#avatarText');
    if (avatar) {
      const user = S.user || '本地用户';
      avatar.textContent = /^[A-Za-z]/.test(user) ? user.slice(0, 1).toUpperCase() : 'G';
    }
  }

  async function updateSetting(key, value) {
    S.settings[key] = value;
    syncSettings();
    if (key === 'layout' || key === 'columns' || key === 'showChips'
      || key === 'showSubtitle' || key === 'sort') {
      renderGrid();
      if (key === 'sort') renderHeader();
    }
    if (key === 'background') {
      document.body.classList.toggle('no-wallpaper', !S.wallpaper || value !== 'wallpaper');
    }
    try {
      await api('/api/settings', { method: 'POST', body: { settings: { [key]: value } } });
    } catch (e) {
      toast('保存设置失败：' + e.message, 'err');
    }
  }

  /* ------------------------------------------------------------ 操作 */
  async function launch(app, tileEl) {
    if (!app || S.launching.has(app.id)) return;
    S.launching.add(app.id);
    if (tileEl) tileEl.classList.add('is-launching');
    try {
      const r = await api('/api/launch', { method: 'POST', body: { id: app.id } });
      app.launchCount = r.launchCount != null ? r.launchCount : (app.launchCount || 0) + 1;
      app.lastLaunch = Date.now() / 1000;
      toast('已打开 ' + app.name);
      renderRecent();
      renderOpenedIcons();
    } catch (e) {
      toast('打开失败：' + e.message, 'err');
    }
    setTimeout(() => {
      S.launching.delete(app.id);
      if (tileEl) tileEl.classList.remove('is-launching');
    }, 900);
  }

  async function rescan(force) {
    if (S.scan.running) { toast('正在扫描中，请稍候…'); return; }
    try {
      await api('/api/rescan', { method: 'POST', body: { force: !!force } });
      S.scan.running = true;
      renderScanbar();
      renderGrid();
      toast(force ? '正在重建图标与封面…' : '正在重新扫描应用…');
      schedulePoll(400);
    } catch (e) {
      toast('扫描失败：' + e.message, 'err');
    }
  }

  function schedulePoll(delay) {
    clearTimeout(S.pollTimer);
    const wait = S.scan.running ? (delay || 800) : 15000;
    S.pollTimer = setTimeout(async () => {
      try {
        const data = await api('/api/bootstrap');
        apply(data);
      } catch (e) { /* 服务可能已退出 */ }
      schedulePoll();
    }, wait);
  }

  async function heartbeat() {
    try { await fetch('/api/ping?hb=1', { cache: 'no-store' }); } catch (e) { /* ignore */ }
  }

  function updateClock() {
    const now = new Date();
    const clock = $('#clock');
    if (!clock) return;
    clock.innerHTML = '<b>' + pad2(now.getHours()) + ':' + pad2(now.getMinutes()) + '</b>'
      + '<span>' + (now.getMonth() + 1) + ' 月 ' + now.getDate() + ' 日 · 周'
      + '日一二三四五六'[now.getDay()] + '</span>';
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (e) {
      toast('全屏失败：' + e.message, 'err');
    }
  }

  async function quitApp() {
    if (!window.confirm('确定退出方块桌面？本地服务会一并关闭。')) return;
    try { await api('/api/quit', { method: 'POST' }); } catch (e) { /* ignore */ }
    document.body.innerHTML = '<div class="quit-overlay"><b>方块桌面已退出</b><span>正在关闭窗口…</span></div>';
    setTimeout(() => {
      try { window.close(); } catch (e) { /* 留在原地，让用户手动关闭 */ }
    }, 500);
  }

  /* ------------------------------------------------------------ 菜单 */
  function showMenu(items, x, y, cls) {
    const menu = $('#ctxMenu');
    menu.className = 'menu' + (cls ? ' ' + cls : '');
    menu.innerHTML = items.map((item, index) => {
      if (item.sep) return '<div class="menu-sep"></div>';
      if (item.title) return '<div class="menu-title">' + esc(item.title) + '</div>';
      return '<button class="menu-item' + (item.danger ? ' danger' : '') + '" data-index="' + index + '">'
        + (item.icon || '') + '<span>' + esc(item.label) + '</span>'
        + (item.kbd ? '<span class="k">' + esc(item.kbd) + '</span>' : '')
        + (item.submenu ? '<svg class="caret-r" viewBox="0 0 24 24"><path d="M7 10l5 5 5-5"/></svg>' : '')
        + '</button>';
    }).join('');
    menu.hidden = false;
    const rect = menu.getBoundingClientRect();
    const left = Math.min(x, window.innerWidth - rect.width - 12);
    const top = Math.min(y, window.innerHeight - rect.height - 12);
    menu.style.left = Math.max(12, left) + 'px';
    menu.style.top = Math.max(12, top) + 'px';
    menu.onclick = (e) => {
      const btn = e.target.closest('.menu-item');
      if (!btn) return;
      const item = items[Number(btn.dataset.index)];
      if (!item) return;
      if (item.submenu) {
        const r = btn.getBoundingClientRect();
        showMenu(item.submenu, r.right + 4, r.top, 'menu-sub');
        return;
      }
      hideMenu();
      if (item.onClick) item.onClick();
    };
  }

  function hideMenu() {
    const menu = $('#ctxMenu');
    menu.hidden = true;
    menu.innerHTML = '';
  }

  function openAppMenu(app, x, y) {
    S.menuApp = app;
    const categories = CAT_ORDER.includes(app.category)
      ? CAT_ORDER : CAT_ORDER.concat([app.category]);
    const catItems = categories.map((cat) => ({
      label: cat,
      icon: cat === app.category ? ICON.check : '',
      onClick: () => patchApp(app, { category: cat }),
    }));
    showMenu([
      { label: '打开', icon: ICON.arrow, kbd: 'Enter', onClick: () => launch(app, tileEl(app.id)) },
      { label: app.pinned ? '取消固定' : '固定到常用', icon: ICON.star, kbd: 'P', onClick: () => patchApp(app, { pinned: !app.pinned }) },
      { sep: true },
      { label: '重命名…', icon: ICON.pencil, onClick: () => renameApp(app) },
      { label: '修改分类', icon: ICON.tag, submenu: catItems },
      { label: '打开文件位置', icon: ICON.folder, onClick: () => openLocation(app) },
      { sep: true },
      { label: '隐藏此应用', icon: ICON.eyeOff, danger: true, onClick: () => patchApp(app, { hidden: true }) },
    ], x, y);
  }

  function tileEl(id) {
    return $('#grid .tile[data-id="' + id + '"]');
  }

  async function patchApp(app, patch) {
    try {
      const r = await api('/api/app/' + app.id, { method: 'PATCH', body: patch });
      if (r.app) Object.assign(app, r.app);
      renderAll();
      if (patch.hidden) {
        toast('已隐藏「' + app.name + '」', 'ok', {
          label: '撤销',
          onClick: () => patchApp(app, { hidden: false }),
        });
      } else if ('pinned' in patch) {
        toast(patch.pinned ? '已固定到常用' : '已取消固定');
      } else if (patch.category) {
        toast('分类已改为「' + patch.category + '」');
      }
    } catch (e) {
      toast('操作失败：' + e.message, 'err');
    }
  }

  async function renameApp(app) {
    const name = window.prompt('给「' + app.name + '」起个新名字（留空恢复原名）', app.name);
    if (name == null) return;
    await patchApp(app, { name: name.trim() });
  }

  async function openLocation(app) {
    try {
      await api('/api/open-location', { method: 'POST', body: { id: app.id } });
    } catch (e) {
      toast('打开位置失败：' + e.message, 'err');
    }
  }

  /* ------------------------------------------------------------ 搜索 */
  function openSearch() {
    const modal = $('#searchModal');
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    const input = $('#searchInput');
    input.value = '';
    S.searchIndex = 0;
    renderSearch('');
    setTimeout(() => input.focus(), 30);
  }

  function closeSearch() {
    const modal = $('#searchModal');
    if (modal.hidden) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }

  function searchApps(query) {
    const q = query.trim().toLowerCase();
    let list = visibleApps();
    if (!q) {
      return list.slice().sort((a, b) => b.lastLaunch - a.lastLaunch || b.launchCount - a.launchCount).slice(0, 12);
    }
    const scored = [];
    list.forEach((app) => {
      const name = app.name.toLowerCase();
      const raw = (app.rawName || '').toLowerCase();
      const cat = app.category.toLowerCase();
      const path = (app.path || '').toLowerCase();
      let score = 0;
      if (name === q) score = 100;
      else if (name.startsWith(q)) score = 80;
      else if (name.includes(q)) score = 60;
      else if (raw.includes(q)) score = 50;
      else if (cat.includes(q)) score = 30;
      else if (path.includes(q)) score = 20;
      if (score) scored.push({ app, score });
    });
    return scored.sort((a, b) => b.score - a.score || a.app.name.localeCompare(b.app.name, 'zh-Hans-CN'))
      .slice(0, 40).map((x) => x.app);
  }

  function renderSearch(query) {
    S.searchResults = searchApps(query);
    S.searchIndex = Math.min(S.searchIndex, Math.max(0, S.searchResults.length - 1));
    const box = $('#searchList');
    if (!S.searchResults.length) {
      box.innerHTML = '<div class="search-empty">没有找到匹配的应用</div>';
      return;
    }
    box.innerHTML = S.searchResults.map((a, i) => (
      '<div class="search-item' + (i === S.searchIndex ? ' is-active' : '') + '" data-id="' + a.id + '">'
      + (a.cover ? '<img src="' + a.cover + '" alt="">' : '<div class="si-cover"></div>')
      + '<div class="si-text"><div class="si-name">' + esc(a.name) + '</div>'
      + '<div class="si-meta">' + esc(searchMeta(a)) + '</div></div>'
      + (i === S.searchIndex ? '<span class="si-enter">Enter</span>' : '')
      + '</div>'
    )).join('');
    const active = box.querySelector('.is-active');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }

  function searchMeta(app) {
    const parts = [app.category, subtitleOf(app)].filter(Boolean);
    return parts.join(' · ');
  }

  function moveSearch(delta) {
    if (!S.searchResults.length) return;
    S.searchIndex = (S.searchIndex + delta + S.searchResults.length) % S.searchResults.length;
    renderSearch($('#searchInput').value);
  }

  function launchFromSearch() {
    const app = S.searchResults[S.searchIndex];
    if (!app) return;
    closeSearch();
    launch(app, tileEl(app.id));
  }

  /* ------------------------------------------------------------ 抽屉 */
  function openDrawer() {
    $('#drawer').classList.add('is-open');
    $('#drawer').setAttribute('aria-hidden', 'false');
    $('#drawerMask').hidden = false;
  }

  function closeDrawer() {
    $('#drawer').classList.remove('is-open');
    $('#drawer').setAttribute('aria-hidden', 'true');
    $('#drawerMask').hidden = true;
  }

  /* ------------------------------------------------------------ 焦点 / 键盘 */
  function focusTile(id) {
    const tile = tileEl(id);
    if (!tile) return;
    S.focusId = id;
    tile.focus({ preventScroll: true });
    tile.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function moveFocus(key) {
    if (!S.visible.length) return;
    let index = S.visible.findIndex((a) => a.id === S.focusId);
    if (index < 0) index = 0;
    else if (key === 'ArrowLeft') index -= 1;
    else if (key === 'ArrowRight') index += 1;
    else if (key === 'ArrowUp') index -= S.cols;
    else if (key === 'ArrowDown') index += S.cols;
    index = Math.max(0, Math.min(S.visible.length - 1, index));
    focusTile(S.visible[index].id);
  }

  /* ------------------------------------------------------------ Toast */
  function toast(message, type, action) {
    const wrap = $('#toasts');
    const node = document.createElement('div');
    node.className = 'toast' + (type === 'err' ? ' err' : '');
    node.innerHTML = '<span>' + esc(message) + '</span>'
      + (action ? '<button class="toast-action">' + esc(action.label) + '</button>' : '');
    if (action) {
      node.style.pointerEvents = 'auto';
      node.querySelector('.toast-action').addEventListener('click', () => {
        action.onClick();
        hideToast(node);
      });
    }
    wrap.appendChild(node);
    setTimeout(() => hideToast(node), action ? 6000 : 2800);
  }

  function hideToast(node) {
    if (!node || !node.parentNode) return;
    node.classList.add('hide');
    setTimeout(() => node.remove(), 260);
  }

  /* ------------------------------------------------------------ 拖拽排序 */
  function dragCleanup() {
    S.dragging = null;
    $$('#grid .tile').forEach((t) => t.classList.remove('is-dragging', 'is-drop-target'));
  }

  async function reorder(fromId, toId) {
    if (!fromId || !toId || fromId === toId) return;
    const ids = visibleApps().map((a) => a.id);
    const from = ids.indexOf(fromId);
    const to = ids.indexOf(toId);
    if (from < 0 || to < 0) return;
    ids.splice(from, 1);
    ids.splice(to, 0, fromId);
    const map = new Map(S.apps.map((a) => [a.id, a]));
    S.apps = ids.map((id) => map.get(id)).filter(Boolean)
      .concat(S.apps.filter((a) => !ids.includes(a.id)));
    renderGrid();
    try {
      await api('/api/order', { method: 'POST', body: { ids } });
    } catch (e) {
      toast('保存顺序失败：' + e.message, 'err');
    }
  }

  /* ------------------------------------------------------------ 事件绑定 */
  function bind() {
    $('#railNav').addEventListener('click', (e) => {
      const btn = e.target.closest('.rail-item');
      if (btn) setView(btn.dataset.view);
    });

    $('#chips').addEventListener('click', (e) => {
      const chip = e.target.closest('.chip');
      if (!chip) return;
      S.category = chip.dataset.cat;
      renderChepsSafe();
    });

    function renderChepsSafe() {
      renderChips();
      renderHeader();
      renderGrid();
    }

    $('#layoutSeg').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-layout]');
      if (btn) updateSetting('layout', btn.dataset.layout);
    });

    $('#btnSort').addEventListener('click', (e) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const items = Object.keys(SORT_LABEL).map((key) => ({
        label: SORT_LABEL[key],
        icon: key === (S.settings.sort || 'custom') ? ICON.check : '',
        onClick: () => updateSetting('sort', key),
      }));
      showMenu(items, rect.left, rect.bottom + 6);
    });

    $('#btnSearch').addEventListener('click', openSearch);
    $('#btnRefresh').addEventListener('click', () => rescan(false));
    $('#btnSettings').addEventListener('click', openDrawer);
    const openedBox = $('#openedList');
    openedBox.addEventListener('click', (e) => {
      const item = e.target.closest('.opened-icon');
      if (!item) return;
      const app = appById(item.dataset.id);
      if (app) launch(app, tileEl(app.id));
    });
    openedBox.addEventListener('contextmenu', (e) => {
      const item = e.target.closest('.opened-icon');
      if (!item) return;
      e.preventDefault();
      const app = appById(item.dataset.id);
      if (app) openAppMenu(app, e.clientX, e.clientY);
    });
    $('#recentCard').addEventListener('click', () => {
      const app = S.recentId ? appById(S.recentId) : null;
      if (app) launch(app, tileEl(app.id));
      else if (S.apps.length) openSearch();
      else rescan(false);
    });
    $('#btnFullscreen').addEventListener('click', toggleFullscreen);
    $('#btnQuit').addEventListener('click', quitApp);
    $('#drawerClose').addEventListener('click', closeDrawer);
    $('#drawerMask').addEventListener('click', closeDrawer);
    $('#avatar').addEventListener('click', () => toast('本地用户 · ' + (S.user || '你')));

    $('#setLayout').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-value]');
      if (btn) updateSetting('layout', btn.dataset.value);
    });
    $('#setColumns').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-value]');
      if (btn) updateSetting('columns', Number(btn.dataset.value));
    });
    $('#setBg').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-value]');
      if (btn) updateSetting('background', btn.dataset.value);
    });
    $('#setLaunch').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-value]');
      if (btn) updateSetting('launchMode', btn.dataset.value);
    });
    $$('.switch[data-key]').forEach((sw) => {
      sw.addEventListener('click', () => updateSetting(sw.dataset.key, !S.settings[sw.dataset.key]));
    });
    $('#switchAutostart').addEventListener('click', async () => {
      const next = !S.settings.autostart;
      try {
        const r = await api('/api/autostart', { method: 'POST', body: { enabled: next } });
        S.settings.autostart = !!r.enabled;
        syncSettings();
        toast(r.enabled ? '已设置开机自启' : '已关闭开机自启');
      } catch (e) {
        toast('设置失败：' + e.message, 'err');
      }
    });
    $('#btnRescan').addEventListener('click', () => rescan(false));
    $('#btnRebuild').addEventListener('click', () => rescan(true));
    $('#btnOpenData').addEventListener('click', async () => {
      try { await api('/api/open-data', { method: 'POST' }); } catch (e) { toast('打开失败：' + e.message, 'err'); }
    });
    $('#btnQuit2').addEventListener('click', quitApp);

    // 网格交互
    const grid = $('#grid');
    grid.addEventListener('click', (e) => {
      const tile = e.target.closest('.tile');
      if (!tile) return;
      const app = appById(tile.dataset.id);
      if (!app) return;
      S.focusId = app.id;
      if (S.settings.launchMode === 'double') return;
      launch(app, tile);
    });
    grid.addEventListener('dblclick', (e) => {
      if (S.settings.launchMode !== 'double') return;
      const tile = e.target.closest('.tile');
      if (!tile) return;
      launch(appById(tile.dataset.id), tile);
    });
    grid.addEventListener('contextmenu', (e) => {
      const tile = e.target.closest('.tile');
      if (!tile) return;
      e.preventDefault();
      const app = appById(tile.dataset.id);
      if (!app) return;
      S.focusId = app.id;
      openAppMenu(app, e.clientX, e.clientY);
    });
    grid.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const tile = e.target.closest('.tile');
        if (tile) {
          e.preventDefault();
          launch(appById(tile.dataset.id), tile);
        }
      } else if (e.key === ' ') {
        const tile = e.target.closest('.tile');
        if (tile) { e.preventDefault(); S.focusId = tile.dataset.id; }
      }
    });
    grid.addEventListener('dragstart', (e) => {
      const tile = e.target.closest('.tile');
      if (!tile || !canReorder()) { e.preventDefault(); return; }
      S.dragging = tile.dataset.id;
      tile.classList.add('is-dragging');
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', tile.dataset.id); } catch (err) { /* ignore */ }
    });
    grid.addEventListener('dragover', (e) => {
      if (!S.dragging) return;
      e.preventDefault();
      $$('#grid .tile').forEach((t) => t.classList.remove('is-drop-target'));
      const tile = e.target.closest('.tile');
      if (tile && tile.dataset.id !== S.dragging) tile.classList.add('is-drop-target');
      e.dataTransfer.dropEffect = 'move';
    });
    grid.addEventListener('drop', (e) => {
      if (!S.dragging) return;
      e.preventDefault();
      const tile = e.target.closest('.tile');
      const from = S.dragging;
      const to = tile ? tile.dataset.id : null;
      dragCleanup();
      reorder(from, to);
    });
    grid.addEventListener('dragend', dragCleanup);

    // 搜索
    const input = $('#searchInput');
    input.addEventListener('input', () => { S.searchIndex = 0; renderSearch(input.value); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); moveSearch(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); moveSearch(-1); }
      else if (e.key === 'Enter') { e.preventDefault(); launchFromSearch(); }
      else if (e.key === 'Escape') { e.preventDefault(); closeSearch(); }
    });
    $('#searchList').addEventListener('click', (e) => {
      const item = e.target.closest('.search-item');
      if (!item) return;
      const app = appById(item.dataset.id);
      closeSearch();
      launch(app, tileEl(app.id));
    });
    $('#searchList').addEventListener('mousemove', (e) => {
      const item = e.target.closest('.search-item');
      if (!item) return;
      const idx = S.searchResults.findIndex((a) => a.id === item.dataset.id);
      if (idx >= 0 && idx !== S.searchIndex) {
        S.searchIndex = idx;
        renderSearch(input.value);
      }
    });
    $$('[data-close]').forEach((node) => node.addEventListener('click', closeSearch));

    // 全局键盘
    document.addEventListener('keydown', (e) => {
      const active = document.activeElement;
      const typing = active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA');
      if (e.key === 'Escape') {
        if (!$('#searchModal').hidden) { closeSearch(); return; }
        if ($('#drawer').classList.contains('is-open')) { closeDrawer(); return; }
        hideMenu();
        return;
      }
      if (typing) return;
      if (e.key === '/' && $('#searchModal').hidden) {
        e.preventDefault();
        openSearch();
        return;
      }
      if (!$('#searchModal').hidden || $('#drawer').classList.contains('is-open')) return;
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
        e.preventDefault();
        moveFocus(e.key);
        return;
      }
      if (e.key === 'Enter' && S.focusId) {
        const app = appById(S.focusId);
        if (app) launch(app, tileEl(app.id));
        return;
      }
      if ((e.key === 'p' || e.key === 'P') && S.focusId) {
        const app = appById(S.focusId);
        if (app) patchApp(app, { pinned: !app.pinned });
      }
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#ctxMenu') && !e.target.closest('#btnSort')) hideMenu();
    });

    window.addEventListener('resize', debounce(() => {
      applyLayout();
      updateGridFade();
    }, 120));
    $('#gridWrap').addEventListener('scroll', updateGridFade, { passive: true });
    // 元素尺寸变化（含高 DPI 窗口初始化、最大化）也要重新算列宽
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(debounce(() => {
        applyLayout();
        updateGridFade();
      }, 60));
      ro.observe($('#gridWrap'));
    }
    // 关闭窗口时立即通知服务退出；刷新页面会重新发心跳，服务不会误退
    window.addEventListener('pagehide', () => {
      try { navigator.sendBeacon('/api/bye'); } catch (e) { /* ignore */ }
    });
    // 启动窗口设置
    $('#setWindow').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-value]');
      if (btn) updateSetting('windowMode', btn.dataset.value);
    });

    $('#drawer').addEventListener('click', (e) => e.stopPropagation());
  }
})();
