/* ==========================================================================
   农家乐.cn — 列表页筛选与排序
   商家卡由构建脚本服务端渲染（便于爬虫抓取），这里只做前端筛选与重排。
   ========================================================================== */
(function () {
  'use strict';

  var list = document.getElementById('shopList');
  if (!list) return;

  var rows = Array.prototype.slice.call(list.querySelectorAll('.shop-row'));
  var emptyBox = document.getElementById('emptyBox');
  var countNum = document.getElementById('countNum');
  var params = new URLSearchParams(location.search);

  // 构建时注入的两张表：
  //   openCities —— 已开通城市（slug → 名称），判断「城市没开通」用
  //   allCities  —— 全量 337 城（slug → 中文名），把 URL 里的 slug 还原成城市名用
  function readMap(id) {
    var el = document.getElementById(id);
    if (!el) return {};
    try { return JSON.parse(el.textContent) || {}; } catch (e) { return {}; }
  }
  var openCities = readMap('openCitiesData');
  var allCities = readMap('allCitiesData');

  var state = {
    q: (params.get('q') || '').trim().toLowerCase(),
    city: params.get('city') || '',
    tag: params.get('tag') || '',
    price: '',
    distance: '',
    sort: 'default'
  };

  // 外链/手输可能带的是中文城市名而不是 slug（?city=杭州）。先归一化成 slug，
  // 否则既认不出是哪座城市，也匹配不上任何商家。
  (function normalizeCity() {
    if (!state.city || allCities[state.city]) return;
    var hit = Object.keys(allCities).filter(function (k) {
      return allCities[k] === state.city;
    })[0];
    if (hit) state.city = hit;
  })();

  /* ------------------------------------------------------------ 数据读取 */
  rows.forEach(function (el) {
    el.__d = {
      slug: el.getAttribute('data-slug') || '',
      name: el.getAttribute('data-name') || '',
      city: el.getAttribute('data-city') || '',
      price: parseFloat(el.getAttribute('data-price')) || 0,
      distance: parseFloat(el.getAttribute('data-distance')) || 0,
      score: parseFloat(el.getAttribute('data-score')) || 0,
      tags: (el.getAttribute('data-tags') || '').split(',').filter(Boolean),
      text: el.getAttribute('data-text') || ''
    };
  });

  function inRange(v, range) {
    if (!range) return true;
    var p = range.split('-');
    return v >= parseFloat(p[0]) && v <= parseFloat(p[1]);
  }

  function match(d) {
    if (state.city && d.city !== state.city) return false;
    if (state.tag && d.tags.indexOf(state.tag) === -1) return false;
    if (!inRange(d.price, state.price)) return false;
    if (!inRange(d.distance, state.distance)) return false;
    if (state.q) {
      var hit = d.text.indexOf(state.q) !== -1;
      if (!hit) return false;
    }
    return true;
  }

  function sortRows(arr) {
    var s = state.sort;
    if (s === 'price-asc') return arr.slice().sort(function (a, b) { return a.__d.price - b.__d.price; });
    if (s === 'score')     return arr.slice().sort(function (a, b) { return b.__d.score - a.__d.score; });
    if (s === 'distance')  return arr.slice().sort(function (a, b) { return a.__d.distance - b.__d.distance; });
    // 综合排序：评分优先，评价量与价格次之
    return arr.slice().sort(function (a, b) {
      if (b.__d.score !== a.__d.score) return b.__d.score - a.__d.score;
      return a.__d.price - b.__d.price;
    });
  }

  /* -------------------------------------------------------------- 渲染 */
  function render() {
    var hits = [], miss = [];
    rows.forEach(function (el) { (match(el.__d) ? hits : miss).push(el); });

    var ordered = sortRows(hits).concat(miss);
    ordered.forEach(function (el) { list.appendChild(el); });
    miss.forEach(function (el) { el.hidden = true; });
    hits.forEach(function (el) { el.hidden = false; });

    if (countNum) countNum.textContent = hits.length;
    if (emptyBox) emptyBox.hidden = hits.length !== 0;
    list.hidden = hits.length === 0;
    showEmptyReason(hits.length === 0);

    // 同步筛选按钮与快捷标签的选中态
    document.querySelectorAll('.filter-opts').forEach(function (box) {
      var key = box.getAttribute('data-filter');
      if (!key || !(key in state)) return;
      box.querySelectorAll('.filter-opt').forEach(function (btn) {
        btn.classList.toggle('is-on', (btn.getAttribute('data-value') || '') === (state[key] || ''));
      });
    });
    document.querySelectorAll('[data-chip]').forEach(function (chip) {
      var kind = chip.getAttribute('data-chip');
      var v = chip.getAttribute('data-value') || '';
      var cur = kind === 'tag' ? state.tag : state.city;
      chip.classList.toggle('is-on', v === cur);
    });
    document.querySelectorAll('.sort-btn').forEach(function (b) {
      b.classList.toggle('is-on', b.getAttribute('data-sort') === state.sort);
    });
  }

  /* 空结果的原因不止一种，出口也不该只有「清空筛选」。
     URL 里带的城市如果不在已开通名单里，说明是这座城市还没有商家 ——
     这时候提示「放宽价格或距离」是答非所问：用户根本没设过这些条件。
     直接给入驻入口，并把城市名一起带过去。 */
  function showEmptyReason(isEmpty) {
    var cityGate = document.getElementById('emptyCityGate');
    var filterGate = document.getElementById('emptyFilterGate');
    if (!isEmpty || !cityGate || !filterGate) return;

    var city = state.city;
    // 认得出这是哪座城市、但它还没开通 —— 才是「城市引导」。
    // 认不出的参数值按普通筛选失败处理，别硬说「这城市没商家」。
    var name = openCities[city] || allCities[city] || '';
    var notOpen = !!name && !openCities[city];

    if (notOpen) {
      var nameEl = document.getElementById('emptyCityName');
      var joinEl = document.getElementById('emptyJoinLink');
      if (nameEl) nameEl.textContent = name;
      if (joinEl) joinEl.href = '/join/?city=' + encodeURIComponent(name);
    }

    cityGate.hidden = !notOpen;
    filterGate.hidden = notOpen;
  }

  /* ------------------------------------------------------------ 地址同步 */
  function syncUrl() {
    var p = new URLSearchParams();
    if (state.q) p.set('q', state.q);
    if (state.city) p.set('city', state.city);
    if (state.tag) p.set('tag', state.tag);
    var qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
  }

  /* -------------------------------------------------------------- 事件 */
  document.querySelectorAll('.filter-opts').forEach(function (box) {
    var key = box.getAttribute('data-filter');
    if (!key || !(key in state)) return;
    box.addEventListener('click', function (e) {
      var btn = e.target.closest('.filter-opt');
      if (!btn) return;
      state[key] = btn.getAttribute('data-value') || '';
      render();
    });
  });

  document.querySelectorAll('.sort-btn').forEach(function (b) {
    b.addEventListener('click', function () {
      state.sort = b.getAttribute('data-sort') || 'default';
      render();
    });
  });

  // 城市 / 玩法快捷标签：不整页跳转，直接改状态
  document.querySelectorAll('[data-chip]').forEach(function (chip) {
    chip.addEventListener('click', function (e) {
      e.preventDefault();
      var kind = chip.getAttribute('data-chip');
      var v = chip.getAttribute('data-value') || '';
      if (kind === 'tag') state.tag = (state.tag === v ? '' : v);
      else state.city = (state.city === v ? '' : v);
      syncUrl();
      render();
    });
  });

  function resetAll() {
    state.q = ''; state.city = ''; state.tag = '';
    state.price = ''; state.distance = ''; state.sort = 'default';
    syncUrl();
    render();
  }
  var r1 = document.getElementById('filterReset');
  var r2 = document.getElementById('emptyReset');
  if (r1) r1.addEventListener('click', resetAll);
  if (r2) r2.addEventListener('click', resetAll);

  var searchInput = document.querySelector('.list-search input');
  if (searchInput) {
    if (state.q) searchInput.value = state.q;
    var timer = null;
    searchInput.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = searchInput.value.trim().toLowerCase();
        syncUrl();
        render();
      }, 160);
    });
  }

  render();
})();
