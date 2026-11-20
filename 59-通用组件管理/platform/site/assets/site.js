/* 59 通用组件管理 · 站点脚本（无外部依赖） */
(function () {
  'use strict';

  var DOWNLOAD_URL = 'https://skillhub.cn/dashboard';
  var BEACON_URL = '/api/beacon';
  var MAX_MD_BYTES = 200 * 1024;
  var MAX_FILE_BYTES = 1024 * 1024;

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function bytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(2) + ' MB';
  }

  function showNotice(el, kind, html) {
    if (!el) return;
    el.className = 'notice show ' + kind;
    el.innerHTML = html;
  }
  function hideNotice(el) { if (el) el.className = 'notice'; }

  /* ---------------- 最小埋点（无 PII，失败静默） ---------------- */

  function beacon(event) {
    if (!event || !navigator.sendBeacon) return;
    try {
      var refHost = '';
      if (document.referrer) {
        try { refHost = new URL(document.referrer).hostname; } catch (_) {}
      }
      var payload = JSON.stringify({ event: event, page: location.pathname, ref_host: refHost });
      navigator.sendBeacon(BEACON_URL, new Blob([payload], { type: 'application/json' }));
    } catch (_) {}
  }

  function initBeacon() {
    beacon('page_view');
    if (/\/guide\.html$/.test(location.pathname)) beacon('guide_view');
    document.addEventListener('click', function (ev) {
      var node = ev.target;
      while (node && node !== document) {
        if (node.tagName === 'A' && /skillhub\.cn/.test(node.href || '')) {
          beacon('cta_skillhub');
          break;
        }
        node = node.parentNode;
      }
    }, true);
  }

  /* ---------------- ZIP 解析（仅提取 SKILL.md 与文件清单） ---------------- */

  function readU16(dv, o) { return dv.getUint16(o, true); }
  function readU32(dv, o) { return dv.getUint32(o, true); }

  function findEOCD(dv) {
    for (var i = dv.byteLength - 22; i >= 0 && i > dv.byteLength - 65558; i--) {
      if (readU32(dv, i) === 0x06054b50) return i;
    }
    return -1;
  }

  async function inflateRaw(raw) {
    if (typeof DecompressionStream === 'undefined') {
      throw new Error('当前浏览器不支持解压，请改为粘贴 SKILL.md 内容');
    }
    var stream = new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  async function parseZip(arrayBuffer) {
    var dv = new DataView(arrayBuffer);
    var eocd = findEOCD(dv);
    if (eocd < 0) throw new Error('不是有效的 zip 文件');
    var total = readU16(dv, eocd + 10);
    var offset = readU32(dv, eocd + 16);
    var files = [];
    var skillMd = null;

    for (var i = 0; i < total; i++) {
      if (readU32(dv, offset) !== 0x02014b50) break;
      var method = readU16(dv, offset + 10);
      var compSize = readU32(dv, offset + 20);
      var rawSize = readU32(dv, offset + 24);
      var nameLen = readU16(dv, offset + 28);
      var extraLen = readU16(dv, offset + 30);
      var commentLen = readU16(dv, offset + 32);
      var localOff = readU32(dv, offset + 42);
      var name = new TextDecoder('utf-8').decode(new Uint8Array(arrayBuffer, offset + 46, nameLen));

      if (!/\/$/.test(name)) files.push({ path: name, size: rawSize });

      if (/(^|\/)SKILL\.md$/i.test(name)) {
        var lNameLen = readU16(dv, localOff + 26);
        var lExtraLen = readU16(dv, localOff + 28);
        var dataStart = localOff + 30 + lNameLen + lExtraLen;
        var raw = new Uint8Array(arrayBuffer, dataStart, compSize);
        var out = method === 0 ? raw : await inflateRaw(raw);
        skillMd = new TextDecoder('utf-8').decode(out);
      }
      offset += 46 + nameLen + extraLen + commentLen;
    }

    if (!skillMd) throw new Error('zip 中没有找到 SKILL.md');
    return { skillMd: skillMd, files: files };
  }

  /* ---------------- 免费额度徽标 ---------------- */

  function quotaKey() {
    return 'trial_remaining_' + new Date().toISOString().slice(0, 10);
  }

  function renderQuota(el, remaining, quota) {
    if (!el) return;
    if (typeof remaining !== 'number') {
      el.className = 'quota-badge';
      el.innerHTML = '今日免费额度 <b>—</b>';
      return;
    }
    var cls = remaining <= 0 ? 'out' : remaining <= 1 ? 'low' : '';
    el.className = 'quota-badge' + (cls ? ' ' + cls : '');
    el.innerHTML = remaining <= 0
      ? '今日免费额度 <b>已用完</b>'
      : '今日剩余 <b>' + remaining + '</b>' + (quota ? ' / ' + quota : '') + ' 次';
  }

  /* ---------------- 试用页 ---------------- */

  function initTrial() {
    var form = $('#trial-submit');
    if (!form) return;

    var mdEl = $('#skill-md');
    var fileEl = $('#skill-file');
    var dropzone = $('#dropzone');
    var chip = $('#file-chip');
    var chipName = $('#file-name');
    var chipSize = $('#file-size');
    var chipRemove = $('#file-remove');
    var mdCount = $('#md-count');
    var submit = $('#trial-submit');
    var clearBtn = $('#trial-clear');
    var notice = $('#trial-notice');
    var resultEl = $('#trial-result');
    var quotaEl = $('#quota-badge');

    var state = {
      skillMd: '',
      files: null,
      source: '',
      report: null,
      remaining: null,
      quota: null,
      filter: 'issue',
      order: null
    };

    var saved = localStorage.getItem(quotaKey());
    if (saved !== null && saved !== '') {
      state.remaining = Number(saved);
      renderQuota(quotaEl, state.remaining, null);
    }

    /* -- 标签切换 -- */
    $$('.trial-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        $$('.trial-tab').forEach(function (t) { t.classList.toggle('active', t === tab); });
        var mode = tab.getAttribute('data-mode');
        $$('.trial-pane').forEach(function (pane) {
          pane.classList.toggle('active', pane.getAttribute('data-pane') === mode);
        });
        if (mode === 'paste') mdEl.focus();
      });
    });

    /* -- 文本计数 -- */
    function updateCount() {
      var text = mdEl.value || '';
      var size = new Blob([text]).size;
      var over = size > MAX_MD_BYTES;
      mdCount.className = 'hint' + (over ? ' over-limit' : '');
      mdCount.textContent = text.length + ' 字符 · ' + bytes(size) +
        (over ? '（超出 200KB 上限）' : '');
    }
    mdEl.addEventListener('input', function () {
      state.skillMd = mdEl.value;
      state.files = null;
      updateCount();
      hideNotice(notice);
    });

    /* -- 文件选择与拖拽 -- */
    function setChip(name, size, extra) {
      chipName.textContent = name;
      chipSize.textContent = size + (extra ? ' · ' + extra : '');
      chip.classList.add('show');
    }
    function resetChip() {
      chip.classList.remove('show');
      chipName.textContent = '—';
      chipSize.textContent = '';
    }

    async function loadFile(file) {
      if (!file) return;
      if (file.size > MAX_FILE_BYTES) {
        showNotice(notice, 'err', '文件超过 1MB 上限，请移除 node_modules 等无关目录后重试。');
        return;
      }
      hideNotice(notice);
      state.source = file.name;
      try {
        if (/\.zip$/i.test(file.name)) {
          var parsed = await parseZip(await file.arrayBuffer());
          state.skillMd = parsed.skillMd;
          state.files = parsed.files;
          mdEl.value = parsed.skillMd;
          updateCount();
          setChip(file.name, bytes(file.size), parsed.files.length + ' 个文件');
          showNotice(notice, 'info', '已从 ' + esc(file.name) + ' 读取 SKILL.md，识别 ' + parsed.files.length + ' 个文件。');
        } else {
          var text = await file.text();
          state.skillMd = text;
          state.files = [{ path: file.name, size: file.size }];
          mdEl.value = text;
          updateCount();
          setChip(file.name, bytes(file.size));
          showNotice(notice, 'info', '已读取 ' + esc(file.name) + '，可直接微调后体检。');
        }
      } catch (err) {
        resetChip();
        state.skillMd = '';
        state.files = null;
        showNotice(notice, 'err', esc(err.message || String(err)));
      }
    }

    fileEl.addEventListener('change', function () {
      loadFile(fileEl.files && fileEl.files[0]);
    });

    chipRemove.addEventListener('click', function (ev) {
      ev.preventDefault();
      fileEl.value = '';
      state.files = null;
      state.source = '';
      resetChip();
      hideNotice(notice);
    });

    ['dragenter', 'dragover'].forEach(function (type) {
      dropzone.addEventListener(type, function (ev) {
        ev.preventDefault();
        dropzone.classList.add('drag');
      });
    });
    ['dragleave', 'dragend'].forEach(function (type) {
      dropzone.addEventListener(type, function () { dropzone.classList.remove('drag'); });
    });
    dropzone.addEventListener('drop', function (ev) {
      ev.preventDefault();
      dropzone.classList.remove('drag');
      var file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
      loadFile(file);
    });

    /* -- 提交 -- */
    function currentContent() {
      return (state.skillMd || mdEl.value || '').trim();
    }

    function setLoading(loading) {
      submit.classList.toggle('loading', loading);
      submit.innerHTML = loading
        ? '<span class="spinner"></span>体检中…'
        : '开始免费体检';
    }

    function showSkeleton() {
      resultEl.innerHTML =
        '<div class="result-card" style="padding:24px">' +
          '<div class="skeleton" style="width:40%"></div>' +
          '<div class="skeleton" style="width:75%"></div>' +
          '<div class="skeleton" style="width:60%"></div>' +
          '<div class="skeleton" style="width:85%"></div>' +
          '<div class="skeleton" style="width:50%;margin-bottom:0"></div>' +
        '</div>';
      resultEl.classList.add('show');
    }

    async function submitTrial() {
      var skillMd = currentContent();
      if (!skillMd) {
        showNotice(notice, 'err', '请先上传 Skill 包，或粘贴 SKILL.md 内容。');
        mdEl.focus();
        return;
      }
      if (new Blob([skillMd]).size > MAX_MD_BYTES) {
        showNotice(notice, 'err', 'SKILL.md 超过 200KB 上限，请精简后再提交。');
        return;
      }

      hideNotice(notice);
      setLoading(true);
      showSkeleton();
      beacon('trial_submit');
      try {
        var res = await fetch('/api/trial', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ skill_md: skillMd, files: state.files || undefined })
        });
        var data = await res.json().catch(function () { return {}; });

        if (res.status === 429) {
          state.remaining = 0;
          localStorage.setItem(quotaKey(), '0');
          renderQuota(quotaEl, 0, state.quota);
          resultEl.classList.remove('show');
          showNotice(notice, 'err',
            '今日免费体检次数已用完。可到 <a href="' + DOWNLOAD_URL + '" target="_blank" rel="noopener">SkillHub 控制台</a> 下载组件，' +
            '或点击下方按钮按次付费获取完整报告（' + esc(data.price || '0.99') + ' 元/次）。 ' +
            '<button class="btn btn-outline" type="button" id="notice-pay" style="margin-left:10px;padding:6px 14px">获取完整报告</button>');
          var noticePay = $('#notice-pay');
          if (noticePay) noticePay.addEventListener('click', payFullReport);
          return;
        }

        if (!res.ok) {
          resultEl.classList.remove('show');
          showNotice(notice, 'err', esc(data.message || ('体检失败：HTTP ' + res.status)));
          return;
        }

        state.report = data.report || {};
        state.filter = hasIssues(state.report) ? 'issue' : 'all';
        beacon('trial_success');
        if (typeof data.remaining === 'number') {
          state.remaining = data.remaining;
          state.quota = data.daily_quota || null;
          localStorage.setItem(quotaKey(), String(data.remaining));
          renderQuota(quotaEl, state.remaining, state.quota);
        }
        renderResult();
      } catch (err) {
        resultEl.classList.remove('show');
        showNotice(notice, 'err', '请求失败：' + esc(err.message || String(err)));
      } finally {
        setLoading(false);
      }
    }

    submit.addEventListener('click', submitTrial);

    document.addEventListener('keydown', function (ev) {
      if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter' && !submit.classList.contains('loading')) {
        ev.preventDefault();
        submitTrial();
      }
    });

    /* -- 结果渲染 -- */
    function verdictTextOf(verdict) {
      return { pass: '通过', needs_work: '建议修改', fail: '存在阻断项' }[verdict] || verdict;
    }

    function hasIssues(report) {
      return (report.checks || []).some(function (c) { return c.status !== 'pass'; });
    }

    function reportToMarkdown(report) {
      var lines = [
        '# Skill 上架体检报告',
        '',
        '- 结论：' + verdictTextOf(report.verdict) + '（' + report.score + ' 分）',
        '- 阻断项：' + (report.counts ? report.counts.error : '-') +
          ' · 建议项：' + (report.counts ? report.counts.warning : '-') +
          ' · 检查项：' + (report.counts ? report.counts.total : '-'),
        '',
        '## 检查明细'
      ];
      (report.checks || []).forEach(function (c) {
        lines.push('- [' + c.status + '] ' + c.id + ' ' + c.title + '：' + c.detail);
      });
      if (report.disclaimer) lines.push('', '> ' + report.disclaimer);
      return lines.join('\n');
    }

    function copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
      }
      var ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand && document.execCommand('copy');
      document.body.removeChild(ta);
      return ok ? Promise.resolve() : Promise.reject(new Error('copy failed'));
    }

    function renderChecks() {
      var report = state.report || {};
      var all = report.checks || [];
      var issues = all.filter(function (c) { return c.status !== 'pass'; });
      var passed = all.filter(function (c) { return c.status === 'pass'; });
      var list = state.filter === 'issue' ? issues : state.filter === 'pass' ? passed : all;

      $$('.filter-btn', resultEl).forEach(function (btn) {
        btn.classList.toggle('active', btn.getAttribute('data-filter') === state.filter);
      });

      var listEl = $('#check-list');
      if (!listEl) return;
      listEl.innerHTML = list.length
        ? list.map(function (c) {
            return '<div class="check-item">' +
              '<i class="dot ' + esc(c.status) + '"></i>' +
              '<div><span class="cid">' + esc(c.id) + '</span><b>' + esc(c.title) + '</b><br>' +
              '<span>' + esc(c.detail) + '</span></div>' +
            '</div>';
          }).join('')
        : '<div class="check-empty">该分类下没有检查项</div>';
    }

    function renderResult() {
      var report = state.report || {};
      var pct = Math.max(0, Math.min(100, Number(report.score) || 0));
      var counts = report.counts || {};
      var verdict = report.verdict || 'unknown';
      var checks = report.checks || [];
      var issues = checks.filter(function (c) { return c.status !== 'pass'; });
      var passed = checks.filter(function (c) { return c.status === 'pass'; });

      resultEl.innerHTML =
        '<div class="result-card">' +
          '<div class="result-head">' +
            '<div class="score" style="--pct:' + pct + '%"><div>' + pct + '</div></div>' +
            '<div class="result-meta">' +
              '<span class="pill ' + esc(verdict) + '">' + esc(verdictTextOf(verdict)) + '</span>' +
              '<p>' + esc(report.summary || '') + '</p>' +
              '<div class="count-chips">' +
                '<span class="chip bad">阻断项 ' + (counts.error != null ? counts.error : '-') + '</span>' +
                '<span class="chip warn">建议项 ' + (counts.warning != null ? counts.warning : '-') + '</span>' +
                '<span class="chip ok">通过项 ' + (passed.length) + '</span>' +
                '<span class="chip">检查项 ' + (counts.total != null ? counts.total : checks.length) + '</span>' +
                (report.hidden_checks ? '<span class="chip">另有 ' + report.hidden_checks + ' 项需完整报告</span>' : '') +
              '</div>' +
            '</div>' +
            '<div class="result-actions">' +
              '<button class="btn btn-plain" type="button" id="copy-report">复制报告</button>' +
              '<button class="btn btn-outline" type="button" id="pay-report">完整报告</button>' +
              '<a class="btn btn-primary" target="_blank" rel="noopener" href="' + DOWNLOAD_URL + '">去下载</a>' +
            '</div>' +
          '</div>' +
          '<div class="result-filters">' +
            '<button class="filter-btn" type="button" data-filter="issue">问题项 ' + issues.length + '</button>' +
            '<button class="filter-btn" type="button" data-filter="all">全部 ' + checks.length + '</button>' +
            '<button class="filter-btn" type="button" data-filter="pass">通过 ' + passed.length + '</button>' +
          '</div>' +
          '<div class="check-list" id="check-list"></div>' +
          '<div class="result-foot">' +
            '<span>' + esc(report.disclaimer || '体检结果不替代平台官方审核。') + '</span>' +
            '<span class="spacer"></span>' +
            '<span>体检时间 ' + esc(report.audited_at ? String(report.audited_at).replace('T', ' ').slice(0, 19) : '-') + '</span>' +
          '</div>' +
        '</div>';

      resultEl.classList.add('show');
      renderChecks();

      $$('.filter-btn', resultEl).forEach(function (btn) {
        btn.addEventListener('click', function () {
          state.filter = btn.getAttribute('data-filter');
          renderChecks();
        });
      });

      var copyBtn = $('#copy-report');
      if (copyBtn) {
        copyBtn.addEventListener('click', function () {
          copyText(reportToMarkdown(report))
            .then(function () {
              copyBtn.textContent = '已复制';
              setTimeout(function () { copyBtn.textContent = '复制报告'; }, 1600);
            })
            .catch(function () { showNotice(notice, 'err', '复制失败，请手动选择文本。'); });
        });
      }

      var payBtn = $('#pay-report');
      if (payBtn) payBtn.addEventListener('click', payFullReport);

      resultEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /* -- 付费获取完整报告 -- */
    async function payFullReport() {
      var skillMd = currentContent();
      if (!skillMd) {
        showNotice(notice, 'err', '请先提交体检内容。');
        return;
      }
      var btn = $('#pay-report') || $('#notice-pay');
      if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = '下单中…'; }

      try {
        var res = await fetch('/api/audit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ skill_md: skillMd, files: state.files || undefined })
        });
        var data = await res.json().catch(function () { return {}; });

        if (res.status === 402) {
          state.order = data;
          showNotice(notice, 'info',
            '<b>完整报告需要按次付费</b>' +
            '<div class="order-card">' +
              '<div>金额：<b>' + esc(data.amount) + ' ' + esc(data.currency) + '</b> · ' + esc(data.goods_name) + '</div>' +
              '<div class="order-row">' +
                '<span>订单号</span><code id="order-no">' + esc(data.out_trade_no) + '</code>' +
                '<button class="btn btn-plain" type="button" id="order-copy" style="padding:4px 10px;font-size:12px">复制</button>' +
              '</div>' +
              '<div class="order-row">支付截止 <b>' + esc(data.pay_before) + '</b></div>' +
              '<div class="order-row">支付完成后，携带 <code>Payment-Proof</code> 重新提交即可取回结果，重复提交不会重复扣费。</div>' +
            '</div>');
          var copyOrder = $('#order-copy');
          if (copyOrder) {
            copyOrder.addEventListener('click', function () {
              copyText(String(data.out_trade_no || '')).then(function () {
                copyOrder.textContent = '已复制';
                setTimeout(function () { copyOrder.textContent = '复制'; }, 1500);
              });
            });
          }
          return;
        }

        if (res.ok && data.content) {
          state.report = data.content;
          state.filter = hasIssues(state.report) ? 'issue' : 'all';
          renderResult();
          showNotice(notice, 'ok', '已取回完整报告（订单 ' + esc(data.out_trade_no || '-') + '）。');
          return;
        }

        showNotice(notice, 'err', esc(data.message || ('请求失败：HTTP ' + res.status)));
      } catch (err) {
        showNotice(notice, 'err', '请求失败：' + esc(err.message || String(err)));
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || '完整报告'; }
      }
    }

    /* -- 清空 -- */
    clearBtn.addEventListener('click', function () {
      state.skillMd = '';
      state.files = null;
      state.source = '';
      state.report = null;
      state.order = null;
      mdEl.value = '';
      fileEl.value = '';
      updateCount();
      resetChip();
      hideNotice(notice);
      resultEl.classList.remove('show');
      resultEl.innerHTML = '';
      mdEl.focus();
    });

    updateCount();
  }

  /* ---------------- 管理后台（只读） ---------------- */

  function initAdmin() {
    var root = $('#admin');
    if (!root) return;

    var compBody = $('#admin-components');
    var healthBox = $('#admin-health');
    var metaBox = $('#admin-meta');

    fetch('data/registry.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        if (metaBox) {
          metaBox.textContent = '生成时间 ' + (data.generated_at || '-') + ' · 组件 ' + (data.components || []).length + ' 个';
        }
        compBody.innerHTML = (data.components || []).map(function (c) {
          return '<tr>' +
            '<td><b>' + esc(c.display_name || c.name) + '</b><div class="hint">' + esc(c.name) + '</div></td>' +
            '<td>' + esc(c.version) + '</td>' +
            '<td><span class="pill ' + (c.lifecycle === 'active' ? 'pass' : 'warn') + '">' + esc(c.lifecycle) + '</span></td>' +
            '<td>' + esc(c.family || '-') + '</td>' +
            '<td class="hint">' + (c.entrypoints || []).map(esc).join('<br>') + '</td>' +
          '</tr>';
        }).join('') || '<tr><td colspan="5">暂无组件登记</td></tr>';
      })
      .catch(function (err) {
        compBody.innerHTML = '<tr><td colspan="5">读取 data/registry.json 失败：' + esc(err.message) + '</td></tr>';
      });

    fetch('/api/health', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (h) {
        healthBox.innerHTML =
          '<div class="grid grid-3">' +
            '<div class="card"><div class="kpi"><b>' + (h.status === 'ok' ? '正常' : esc(h.status)) + '</b><span>audit-api</span></div>' +
              '<p style="margin-top:6px">价格 ' + esc(h.price) + ' ' + esc(h.currency) + ' / 次</p></div>' +
            '<div class="card"><div class="kpi"><b>v' + esc(h.rules_version != null ? h.rules_version : '-') + '</b><span>规则版本</span></div>' +
              '<p style="margin-top:6px">计分 ' + esc(h.score_formula_version || '-') + ' · 限流 ' + esc(h.rate_limit_mode || '-') + '</p></div>' +
            '<div class="card"><div class="kpi"><b>' + ((h.resources || []).length) + '</b><span>在售资源</span></div>' +
              '<p style="margin-top:6px">' + esc((h.resources || []).map(function (r) { return r.path; }).join(' · ')) + '</p></div>' +
          '</div>';
      })
      .catch(function (err) {
        healthBox.innerHTML = '<div class="notice show err">健康检查失败：' + esc(err.message) + '</div>';
      });

    var statsBox = $('#admin-stats');
    if (!statsBox) return;

    fetch('/api/stats', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (s) {
        var trial = s.trial || {};
        var events = s.events || {};
        var orders = s.orders || {};
        var versions = s.reports_by_rules_version || {};
        var build = s.build || {};
        var versionText = Object.keys(versions).map(function (k) { return 'v' + k + '：' + versions[k]; }).join(' · ') || '-';
        statsBox.innerHTML =
          '<div class="grid grid-3">' +
            '<div class="card"><div class="kpi"><b>' + esc(trial.today != null ? trial.today : '-') + ' / ' + esc(trial.limit != null ? trial.limit : '-') + '</b><span>今日免费体检</span></div>' +
              '<p style="margin-top:6px">独立 IP ' + esc(trial.unique_ips != null ? trial.unique_ips : '-') +
              (trial.global_cap_hit ? ' · <b>已触发全站上限</b>' : '') + '</p></div>' +
            '<div class="card"><div class="kpi"><b>' + esc(orders.total != null ? orders.total : '-') + '</b><span>订单总数</span></div>' +
              '<p style="margin-top:6px">已履约 ' + esc(orders.fulfilled != null ? orders.fulfilled : '-') + ' · 近 7 天待支付 ' + esc(orders.pending_7d != null ? orders.pending_7d : '-') + '</p></div>' +
            '<div class="card"><div class="kpi"><b>' + esc(events.trial_submit || 0) + '</b><span>今日体检提交</span></div>' +
              '<p style="margin-top:6px">浏览 ' + esc(events.page_view || 0) + ' · 下载点击 ' + esc(events.cta_skillhub || 0) + '</p></div>' +
          '</div>' +
          '<div class="panel" style="margin-top:16px">' +
            '<div><b>按规则版本的报告：</b>' + esc(versionText) + '</div>' +
            '<div class="hint" style="margin-top:6px">public.json ' + esc(build.public_json || '-') +
            ' · 规则 v' + esc(build.rules_version != null ? build.rules_version : '-') +
            ' · registry ' + esc(build.registry_check || '-') +
            ' · 限流 ' + esc((s.limits || {}).rate_limit_mode || '-') + '</div>' +
          '</div>';
      })
      .catch(function (err) {
        statsBox.innerHTML = '<div class="notice show err">统计读取失败：' + esc(err.message) + '</div>';
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initBeacon();
    initTrial();
    initAdmin();
  });
})();
