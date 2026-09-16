/* ==========================================================================
   农家乐.cn — 站点公共脚本 + 表单提交（对接飞书群机器人，零后端）
   ========================================================================== */
(function () {
  'use strict';

  var CFG = window.__NJ_CFG__ || {};
  var WEBHOOK = (CFG.webhook || '').trim();
  var KEYWORD = (CFG.keyword || '询单').trim();
  var SITE = CFG.site || '农家乐.cn';

  /* ---------------------------------------------------------------- 工具 */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
    });
  }

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  function nowStr() {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
           ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function val(form, name) {
    var el = form.querySelector('[name="' + name + '"]');
    return el ? String(el.value || '').trim() : '';
  }

  function looksLikePhone(s) {
    var digits = String(s).replace(/\D/g, '');
    return digits.length >= 7 && digits.length <= 13;
  }

  /* ------------------------------------------------------------ 卡片构造 */
  // 关键词必须同时出现在 header.title 和 note 里 —— 飞书只校验文本参数值，
  // 两处兜底才不会因为改文案把校验搞挂。
  function buildCard(title, fields) {
    var lines = fields.filter(function (f) { return f[1]; })
                      .map(function (f) { return '**' + f[0] + '**：' + esc(f[1]); });
    var noteText = '来源：' + title + ' · ' + nowStr() + ' · 类型：' + KEYWORD;
    return {
      msg_type: 'interactive',
      card: {
        config: { wide_screen_mode: true },
        header: {
          template: 'blue',
          title: { tag: 'plain_text', content: '🔔 新' + KEYWORD + ' · ' + title + ' · ' + SITE }
        },
        elements: [
          { tag: 'div', text: { tag: 'lark_md', content: lines.join('\n') || '（未填写）' } },
          { tag: 'hr' },
          { tag: 'note', elements: [{ tag: 'plain_text', content: noteText }] }
        ]
      }
    };
  }

  /* ------------------------------------------------------------ 状态提示 */
  function setStatus(form, ok, msg) {
    var box = form.querySelector('.form-status');
    if (!box) return;
    box.className = 'form-status ' + (ok ? 'is-ok' : 'is-err');
    box.textContent = msg;
    box.style.display = 'block';
  }

  function markBad(form, name, bad) {
    var el = form.querySelector('[name="' + name + '"]');
    if (!el) return;
    // 表单区有 .field 包裹，预订卡里的小表单是裸 input，两种都要能标红
    var f = el.closest('.field') || el;
    f.classList.toggle('is-bad', !!bad);
  }

  /* 演示模式：没配接收端时，不把数据发给任何地方，给用户一份可复制的文本 */
  function demoMode(form, payload) {
    var text = payload.title + '\n' +
      payload.fields.filter(function (f) { return f[1]; })
                    .map(function (f) { return f[0] + '：' + f[1]; }).join('\n');
    setStatus(form, true,
      '表单已填写完整，但接收端还没配置（演示模式）。内容没有发送给任何人。\n' + text);
  }

  /* -------------------------------------------------------------- 提交 */
  function submit(form) {
    var kind = form.getAttribute('data-form') || 'join';
    var isJoin = kind === 'join';
    var title = isJoin ? '商家入驻申请' : '价格咨询';

    // 第 2 层防刷：蜜罐。命中就假装成功，不发送，避免被脚本探测出拦截规则
    if (val(form, 'company_url')) {
      setStatus(form, true, '提交成功，我们会尽快联系你。');
      form.reset();
      return;
    }

    var name = val(form, 'name');
    var phone = val(form, 'phone');

    var ok = true;
    if (!name) { markBad(form, 'name', true); ok = false; } else { markBad(form, 'name', false); }
    if (!phone || !looksLikePhone(phone)) { markBad(form, 'phone', true); ok = false; }
    else { markBad(form, 'phone', false); }

    if (isJoin) {
      var city = val(form, 'city');
      if (!city) { markBad(form, 'city', true); ok = false; } else { markBad(form, 'city', false); }
    }

    if (!ok) {
      setStatus(form, false, '请把标红的必填项补齐再提交。');
      return;
    }

    var fields = isJoin
      ? [['名称', name], ['城市', val(form, 'city')], ['电话', phone],
         ['类型', val(form, 'type')], ['人均', val(form, 'price')], ['说明', val(form, 'note')]]
      : [['称呼', name], ['电话', phone], ['咨询对象', form.getAttribute('data-shop') || ''],
         ['页面', location.pathname]];

    var payload = buildCard(title, fields);

    if (!WEBHOOK) { demoMode(form, payload); return; }

    var btn = form.querySelector('button[type="submit"]');
    if (btn) { btn.disabled = true; }

    fetch(WEBHOOK, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        // 飞书 HTTP 状态码恒为 200，成败在响应体的 code 里
        if (j && (j.code === 0 || j.StatusCode === 0)) {
          setStatus(form, true, isJoin
            ? '提交成功。我们会在 1 个工作日内核验并联系你。'
            : '提交成功，商家会尽快回拨你的电话。');
          form.reset();
        } else {
          var m = (j && (j.msg || j.StatusMessage)) || '未知错误';
          setStatus(form, false, '提交失败：' + m);
        }
      })
      .catch(function () {
        setStatus(form, false, '提交失败：网络异常，或接收端被拦截。请稍后重试，或直接打电话给我们。');
      })
      .then(function () { if (btn) { btn.disabled = false; } });
  }

  /* -------------------------------------------------------------- 绑定 */
  document.querySelectorAll('form[data-form]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      submit(form);
    });
  });

  /* 移动端导航：点了链接就把折叠菜单收起来 */
  var navToggle = document.getElementById('navToggle');
  if (navToggle) {
    document.querySelectorAll('.nav-links a').forEach(function (a) {
      a.addEventListener('click', function () { navToggle.checked = false; });
    });
  }
})();
