/* ═══════════════════════════════════════════════════════════════
   Portfolio Tracker — front-end logic
   Flow: Upload → Review → Dashboard
═══════════════════════════════════════════════════════════════ */

'use strict';

// ── State ────────────────────────────────────────────────────────
let holdings = [];   // [{ticker, shares, avg_cost}]
let charts   = {};   // Chart.js instances keyed by name

const PALETTE = [
  '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6',
  '#a855f7','#eab308','#6366f1','#22d3ee','#fb923c',
];

// ── Boot ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initDropZones();
  initManualEntry();
  initReview();
  initDashboard();
  document.getElementById('btn-reset').addEventListener('click', reset);
});

// ── Tab switching ────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.tab;
      document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + key).classList.add('active');
    });
  });
}

// ── Drop zones ───────────────────────────────────────────────────
function initDropZones() {
  setupDrop('drop-csv',        'file-csv',        handleCsv);
  setupDrop('drop-screenshot', 'file-screenshot', handleScreenshot);
  document.getElementById('btn-template').addEventListener('click', downloadTemplate);
}

function setupDrop(zoneId, inputId, handler) {
  const zone  = document.getElementById(zoneId);
  const input = document.getElementById(inputId);

  zone.addEventListener('click', () => input.click());

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', ()  => zone.classList.remove('over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('over');
    const file = e.dataTransfer.files[0];
    if (file) handler(file);
  });
  input.addEventListener('change', () => { if (input.files[0]) handler(input.files[0]); });
}

// ── CSV handler ──────────────────────────────────────────────────
async function handleCsv(file) {
  setUploadLoading(true);
  clearMsg('upload-msg');

  const fd = new FormData();
  fd.append('file', file);

  try {
    const data = await post('/api/parse/csv', fd, true);
    if (data.error) throw new Error(data.error);
    holdings = data.holdings;
    goReview();
  } catch (e) {
    showMsg('upload-msg', e.message);
  } finally {
    setUploadLoading(false);
  }
}

// ── Screenshot handler ───────────────────────────────────────────
async function handleScreenshot(file) {
  setUploadLoading(true);
  clearMsg('upload-msg');

  const fd = new FormData();
  fd.append('file', file);

  try {
    const data = await post('/api/parse/screenshot', fd, true);
    if (data.error) throw new Error(data.error);
    holdings = data.holdings || [];
    if (data.note) showMsg('ocr-note', data.note, 'info');
    goReview();
  } catch (e) {
    showMsg('upload-msg', e.message);
  } finally {
    setUploadLoading(false);
  }
}

// ── Manual entry ─────────────────────────────────────────────────
let manualItems = [];

function initManualEntry() {
  document.getElementById('btn-manual-add').addEventListener('click', addManualRow);
  document.getElementById('btn-manual-continue').addEventListener('click', () => {
    if (!manualItems.length) return showMsg('upload-msg', 'Add at least one position.');
    holdings = manualItems.map(i => ({ ...i }));
    goReview();
  });
  document.getElementById('m-ticker').addEventListener('keydown', e => {
    if (e.key === 'Enter') addManualRow();
  });
  document.getElementById('m-ticker').addEventListener('input', e => {
    e.target.value = e.target.value.toUpperCase();
  });
}

function addManualRow() {
  const ticker = document.getElementById('m-ticker').value.trim().toUpperCase();
  const shares = parseFloat(document.getElementById('m-shares').value);
  const cost   = parseFloat(document.getElementById('m-cost').value);

  if (!ticker || isNaN(shares) || shares <= 0) {
    return showMsg('upload-msg', 'Enter a valid ticker and share count.');
  }
  clearMsg('upload-msg');

  manualItems.push({ ticker, shares, avg_cost: isNaN(cost) ? null : cost });

  // Clear inputs
  ['m-ticker','m-shares','m-cost'].forEach(id => { document.getElementById(id).value = ''; });
  document.getElementById('m-ticker').focus();

  renderManualList();
  document.getElementById('btn-manual-continue').style.display = 'inline-block';
}

function renderManualList() {
  const el = document.getElementById('manual-list');
  el.innerHTML = manualItems.map((h, i) => `
    <div class="manual-item">
      <span><strong>${h.ticker}</strong> &nbsp; ${h.shares} shares
        ${h.avg_cost != null ? `@ $${h.avg_cost.toFixed(2)}` : ''}
      </span>
      <button class="btn-del" onclick="removeManual(${i})">×</button>
    </div>`).join('');
}

window.removeManual = function(i) {
  manualItems.splice(i, 1);
  renderManualList();
  if (!manualItems.length) document.getElementById('btn-manual-continue').style.display = 'none';
};

// ── CSV template download ─────────────────────────────────────────
function downloadTemplate() {
  const csv = 'ticker,shares,avg_cost\nAAPL,10,150.00\nMSFT,5,280.00\nNVDA,2,120.00\n';
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(new Blob([csv], { type: 'text/csv' })),
    download: 'portfolio_template.csv',
  });
  a.click();
}

// ── Review table ─────────────────────────────────────────────────
function initReview() {
  document.getElementById('btn-add-row').addEventListener('click', () => {
    holdings.push({ ticker: '', shares: 0, avg_cost: null });
    renderReview();
  });
  document.getElementById('btn-analyze').addEventListener('click', runAnalyze);
}

function goReview() {
  showView('view-review');
  document.getElementById('btn-reset').style.display = 'block';
  renderReview();
}

function renderReview() {
  const tbody = document.getElementById('tbody-review');
  tbody.innerHTML = '';

  holdings.forEach((h, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text"   class="uc" value="${h.ticker}"
           data-i="${i}" data-f="ticker" placeholder="AAPL" maxlength="5" /></td>
      <td><input type="number" value="${h.shares || ''}"
           data-i="${i}" data-f="shares" placeholder="0" step="any" min="0" /></td>
      <td><input type="number" value="${h.avg_cost != null ? h.avg_cost : ''}"
           data-i="${i}" data-f="avg_cost" placeholder="Optional" step="any" min="0" /></td>
      <td><button class="btn-del" data-i="${i}">×</button></td>`;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('input').forEach(inp => {
    if (inp.classList.contains('uc'))
      inp.addEventListener('input', e => { e.target.value = e.target.value.toUpperCase(); });

    inp.addEventListener('change', e => {
      const idx = +e.target.dataset.i;
      const fld = e.target.dataset.f;
      let v = e.target.value;
      if (fld === 'ticker') v = v.toUpperCase().trim();
      else v = v === '' ? null : +v;
      holdings[idx][fld] = v;
    });
  });

  tbody.querySelectorAll('.btn-del').forEach(btn => {
    btn.addEventListener('click', e => {
      holdings.splice(+e.currentTarget.dataset.i, 1);
      renderReview();
    });
  });
}

// ── Analyze ──────────────────────────────────────────────────────
async function runAnalyze() {
  const valid = holdings.filter(h => h.ticker && +h.shares > 0);
  if (!valid.length) return showMsg('analyze-msg', 'Add at least one position with a ticker and shares.');

  clearMsg('analyze-msg');
  setAnalyzeLoading(true);
  document.getElementById('btn-analyze').disabled = true;

  try {
    const data = await post('/api/analyze', JSON.stringify({ holdings: valid }), false);
    if (data.error) throw new Error(data.error);
    renderDashboard(data);
    showView('view-dashboard');
  } catch (e) {
    showMsg('analyze-msg', e.message);
  } finally {
    setAnalyzeLoading(false);
    document.getElementById('btn-analyze').disabled = false;
  }
}

// ── Dashboard ────────────────────────────────────────────────────
function initDashboard() {
  document.getElementById('sort-by').addEventListener('change', e => {
    if (window._dash) renderHoldingsTable(window._dash.holdings, e.target.value);
  });
}

function renderDashboard(data) {
  window._dash = data;
  const { summary, holdings: h, sector_allocation, performance } = data;

  // KPIs
  document.getElementById('kpi-value').textContent = fmtUSD(summary.total_value);
  document.getElementById('kpi-cost').textContent  = fmtUSD(summary.total_cost);
  document.getElementById('kpi-count').textContent = h.length;

  const gainEl    = document.getElementById('kpi-gain');
  const gainPctEl = document.getElementById('kpi-gain-pct');
  gainEl.textContent    = fmtGain(summary.total_gain);
  gainEl.className      = 'kpi-val ' + colorCls(summary.total_gain);
  gainPctEl.textContent = fmtPct(summary.total_gain_pct);
  gainPctEl.className   = 'kpi-sub ' + colorCls(summary.total_gain_pct);

  document.getElementById('dash-timestamp').textContent =
    'Live · updated ' + new Date().toLocaleTimeString();

  drawSector(sector_allocation);
  drawWeight(h);
  drawPerf(performance);
  drawPnl(h);
  renderHoldingsTable(h, 'value');

  // Tickers with no price history still appear in the table at cost basis, but
  // they are excluded from the optimizer and PRISM — say so rather than letting
  // the numbers quietly disagree with the holdings list.
  const dropped = (data.meta && data.meta.dropped_tickers) || [];
  const noteEl = document.getElementById('dash-note');
  if (dropped.length) {
    noteEl.style.display = 'block';
    noteEl.textContent =
      `No price history for ${dropped.join(', ')}. ` +
      `${dropped.length > 1 ? 'These are' : 'This is'} shown at cost basis and ` +
      `excluded from optimization and PRISM.`;
  } else {
    noteEl.style.display = 'none';
  }

  renderOptimization(data.optimization);
  renderPrism(data.prism);
}

// ── Chart: Sector doughnut ───────────────────────────────────────
function drawSector(alloc) {
  destroyChart('sector');
  const labels = Object.keys(alloc);
  const values = Object.values(alloc);
  const total  = values.reduce((a, b) => a + b, 0);

  charts.sector = new Chart(ctx('chart-sector'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: PALETTE, borderColor: '#0e1320', borderWidth: 2 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { color: '#94a3b8', font: { size: 11 }, padding: 10 } },
        tooltip: {
          callbacks: {
            label: c => ` ${c.label}: ${((c.raw / total) * 100).toFixed(1)}%  (${fmtUSD(c.raw)})`,
          },
        },
      },
    },
  });
}

// ── Chart: Weight horizontal bar ─────────────────────────────────
function drawWeight(h) {
  destroyChart('weight');
  const top = h.slice(0, 12);

  charts.weight = new Chart(ctx('chart-weight'), {
    type: 'bar',
    data: {
      labels: top.map(x => x.ticker),
      datasets: [{
        data: top.map(x => x.weight),
        backgroundColor: top.map((_, i) => PALETTE[i % PALETTE.length]),
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: c => ` ${c.raw.toFixed(2)}%` } },
      },
      scales: {
        x: { grid: { color: '#1c2d45' }, ticks: { color: '#94a3b8', callback: v => v + '%' } },
        y: { grid: { display: false }, ticks: { color: '#e2e8f0', font: { weight: '600' } } },
      },
    },
  });
}

// ── Chart: Actual Performance vs SPY ─────────────────────────────
function drawPerf(perf) {
  destroyChart('perf');
  destroyChart('perfDollar');
  if (!perf?.dates?.length) return;

  const step = Math.max(1, Math.floor(perf.dates.length / 60));
  const sample = arr => arr.filter((_, i) => i % step === 0);
  const dates  = sample(perf.dates);
  const port   = sample(perf.portfolio);
  const spy    = sample(perf.spy);
  const dateLabels = dates.map(d => {
    const dt = new Date(d);
    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  });

  // P&L percentage chart
  charts.perf = new Chart(ctx('chart-perf'), {
    type: 'line',
    data: {
      labels: dateLabels,
      datasets: [
        {
          label: 'My Portfolio P&L',
          data: port,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,.08)',
          fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2.5,
        },
        {
          label: 'SPY (Same Investment)',
          data: spy,
          borderColor: '#94a3b8',
          borderDash: [5, 4],
          fill: false, tension: 0.3, pointRadius: 0, borderWidth: 1.5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#94a3b8', font: { size: 12 }, boxWidth: 16 } },
        tooltip: {
          callbacks: {
            label: c => ` ${c.dataset.label}: ${c.raw >= 0 ? '+' : ''}${c.raw.toFixed(2)}%`,
          },
        },
      },
      scales: {
        x: { grid: { color: '#1c2d45' }, ticks: { color: '#94a3b8', maxTicksLimit: 8 } },
        y: {
          grid: { color: '#1c2d45' },
          ticks: { color: '#94a3b8', callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%' },
        },
      },
    },
  });

  // Dollar value chart (if data available)
  if (perf.portfolio_value?.length) {
    const portVal = sample(perf.portfolio_value);
    const spyVal  = sample(perf.spy_value);
    const costLine = portVal.map(() => perf.total_cost);

    charts.perfDollar = new Chart(ctx('chart-perf-dollar'), {
      type: 'line',
      data: {
        labels: dateLabels,
        datasets: [
          {
            label: 'Portfolio Value',
            data: portVal,
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59,130,246,.08)',
            fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2.5,
          },
          {
            label: 'If Invested in SPY',
            data: spyVal,
            borderColor: '#f59e0b',
            borderDash: [5, 4],
            fill: false, tension: 0.3, pointRadius: 0, borderWidth: 1.5,
          },
          {
            label: 'Cost Basis',
            data: costLine,
            borderColor: '#ef4444',
            borderDash: [2, 3],
            fill: false, tension: 0, pointRadius: 0, borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#94a3b8', font: { size: 12 }, boxWidth: 16 } },
          tooltip: {
            callbacks: {
              label: c => ` ${c.dataset.label}: ${fmtUSD(c.raw)}`,
            },
          },
        },
        scales: {
          x: { grid: { color: '#1c2d45' }, ticks: { color: '#94a3b8', maxTicksLimit: 8 } },
          y: {
            grid: { color: '#1c2d45' },
            ticks: { color: '#94a3b8', callback: v => '$' + v.toLocaleString() },
          },
        },
      },
    });
  }
}

// ── Chart: P&L horizontal bar ────────────────────────────────────
function drawPnl(h) {
  destroyChart('pnl');
  const sorted = [...h].sort((a, b) => b.gain_pct - a.gain_pct).slice(0, 14);

  charts.pnl = new Chart(ctx('chart-pnl'), {
    type: 'bar',
    data: {
      labels: sorted.map(x => x.ticker),
      datasets: [{
        data: sorted.map(x => x.gain_pct),
        backgroundColor: sorted.map(x => x.gain_pct >= 0 ? 'rgba(16,185,129,.65)' : 'rgba(239,68,68,.65)'),
        borderColor:     sorted.map(x => x.gain_pct >= 0 ? '#10b981' : '#ef4444'),
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: c => ` ${c.raw >= 0 ? '+' : ''}${c.raw.toFixed(2)}%` } },
      },
      scales: {
        x: {
          grid: { color: '#1c2d45' },
          ticks: { color: '#94a3b8', callback: v => v + '%' },
        },
        y: { grid: { display: false }, ticks: { color: '#e2e8f0', font: { weight: '600' } } },
      },
    },
  });
}

// ── Holdings table ───────────────────────────────────────────────
function renderHoldingsTable(h, sortKey) {
  const sorted = [...h].sort((a, b) =>
    sortKey === 'ticker' ? a.ticker.localeCompare(b.ticker) : b[sortKey] - a[sortKey]
  );
  const tbody = document.getElementById('tbody-dash');
  tbody.innerHTML = sorted.map(p => `
    <tr>
      <td><strong>${p.ticker}</strong></td>
      <td><span class="sect">${p.sector}</span></td>
      <td>${p.shares}</td>
      <td>${fmtUSD(p.avg_cost)}</td>
      <td>${fmtUSD(p.current_price)}</td>
      <td>${fmtUSD(p.value)}</td>
      <td class="${colorCls(p.gain)}">${fmtGain(p.gain)}</td>
      <td class="${colorCls(p.gain_pct)}">${fmtPct(p.gain_pct)}</td>
      <td>${p.weight.toFixed(2)}%</td>
    </tr>`).join('');
}

// ── Helpers ──────────────────────────────────────────────────────
function fmtUSD(n) {
  if (n == null) return '—';
  return '$' + (+n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtGain(n) {
  const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (n >= 0 ? '+$' : '-$') + abs;
}
function fmtPct(n) { return (n >= 0 ? '+' : '') + (+n).toFixed(2) + '%'; }
function colorCls(n) { return n >= 0 ? 'green' : 'red'; }

function ctx(id) { return document.getElementById(id).getContext('2d'); }

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

// ── View switching ───────────────────────────────────────────────
function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function reset() {
  holdings = [];
  manualItems = [];
  window._dash = null;
  Object.keys(charts).forEach(k => destroyChart(k));
  document.getElementById('btn-reset').style.display = 'none';
  document.getElementById('manual-list').innerHTML = '';
  document.getElementById('btn-manual-continue').style.display = 'none';
  clearMsg('upload-msg');
  clearMsg('ocr-note');
  showView('view-upload');
}

// ── UI state helpers ─────────────────────────────────────────────
function showMsg(id, text, type = 'error') {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className   = 'msg ' + type;
  el.style.display = 'block';
}
function clearMsg(id) { document.getElementById(id).style.display = 'none'; }

function setUploadLoading(show) {
  document.getElementById('upload-loading').style.display = show ? 'block' : 'none';
}
function setAnalyzeLoading(show) {
  document.getElementById('analyze-loading').style.display = show ? 'block' : 'none';
}

// ── Fetch wrappers ───────────────────────────────────────────────
async function post(url, body, isFormData) {
  const opts = { method: 'POST', body };
  if (!isFormData) opts.headers = { 'Content-Type': 'application/json' };
  const res = await fetch(url, opts);
  return res.json();
}


// ═══════════════════════════════════════════════════════════════════
//  Optimization  (max-Sharpe allocation, 1y window)
// ═══════════════════════════════════════════════════════════════════

const STRATEGY_LABELS = {
  current: 'Current',
  optimal: 'Optimal',
  equal_weight: 'Equal Weight',
};

function renderOptimization(opt) {
  const body = document.getElementById('opt-body');
  const note = document.getElementById('opt-unavailable');

  if (!opt || !opt.available) {
    body.style.display = 'none';
    note.style.display = 'block';
    note.textContent = (opt && opt.reason) || 'Optimization unavailable.';
    return;
  }

  body.style.display = '';
  note.style.display = 'none';

  // KPI row: one card per strategy.
  const kpis = document.getElementById('opt-kpis');
  kpis.innerHTML = '';
  ['current', 'optimal', 'equal_weight'].forEach(key => {
    const s = opt.strategies[key];
    const card = document.createElement('div');
    card.className = 'card kpi' + (key === 'optimal' ? ' kpi-accent' : '');
    card.innerHTML = `
      <div class="kpi-label">${STRATEGY_LABELS[key]}</div>
      <div class="kpi-val">${s.sharpe.toFixed(2)}</div>
      <div class="kpi-sub">Sharpe · ${s.annual_return.toFixed(1)}% return · ${s.annual_risk.toFixed(1)}% vol</div>`;
    kpis.appendChild(card);
  });

  if (opt.sharpe_improvement) {
    const card = document.createElement('div');
    card.className = 'card kpi';
    const cls = opt.sharpe_improvement >= 0 ? 'green' : 'red';
    card.innerHTML = `
      <div class="kpi-label">Sharpe Headroom</div>
      <div class="kpi-val ${cls}">${fmtPct(opt.sharpe_improvement)}</div>
      <div class="kpi-sub">optimal vs current · cap ${opt.max_position_pct}% per name</div>`;
    kpis.appendChild(card);
  }

  drawAllocation(opt);
  drawSensitivity(opt.sensitivity);
  drawScatter(opt.scatter);
}

function drawAllocation(opt) {
  destroyChart('alloc');
  const current = opt.strategies.current.weights;
  const optimal = opt.strategies.optimal.weights;

  // Order by optimal weight so the biggest recommended positions read first.
  const tickers = [...opt.tickers].sort((a, b) => (optimal[b] || 0) - (optimal[a] || 0)).slice(0, 12);

  charts.alloc = new Chart(ctx('chart-alloc'), {
    type: 'bar',
    data: {
      labels: tickers,
      datasets: [
        { label: 'Current', data: tickers.map(t => current[t] || 0), backgroundColor: '#64748b' },
        { label: 'Optimal', data: tickers.map(t => optimal[t] || 0), backgroundColor: '#38bdf8' },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#94a3b8', font: { size: 11 } } },
        tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${c.raw.toFixed(2)}%` } },
      },
      scales: {
        x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
        y: {
          ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => v + '%' },
          grid: { color: 'rgba(148,163,184,.12)' },
        },
      },
    },
  });
}

function drawSensitivity(sensitivity) {
  destroyChart('sensitivity');
  const labels = Object.keys(sensitivity);

  charts.sensitivity = new Chart(ctx('chart-sensitivity'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: labels.map(k => sensitivity[k]),
        backgroundColor: labels.map(k => (k === 'Optimal' ? '#38bdf8' : '#64748b')),
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: c => ` ${c.raw.toFixed(2)}% expected annual return` } },
      },
      scales: {
        x: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { display: false } },
        y: {
          ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => v + '%' },
          grid: { color: 'rgba(148,163,184,.12)' },
        },
      },
    },
  });
}

function drawScatter(points) {
  destroyChart('scatter');
  if (!points || !points.length) return;

  charts.scatter = new Chart(ctx('chart-scatter'), {
    type: 'scatter',
    data: {
      datasets: [{
        data: points.map(p => ({ x: p.risk, y: p.ret, ticker: p.ticker, weight: p.weight })),
        backgroundColor: '#38bdf8',
        // Bubble size tracks position weight, so concentration is visible.
        pointRadius: c => Math.max(4, Math.min(16, (c.raw.weight || 0) / 2 + 4)),
        pointHoverRadius: c => Math.max(6, Math.min(18, (c.raw.weight || 0) / 2 + 6)),
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: c => ` ${c.raw.ticker}: ${c.raw.y.toFixed(1)}% return, ` +
                        `${c.raw.x.toFixed(1)}% vol, ${c.raw.weight.toFixed(1)}% weight`,
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: 'Annualised volatility %', color: '#94a3b8', font: { size: 10 } },
          ticks: { color: '#94a3b8', font: { size: 10 } },
          grid: { color: 'rgba(148,163,184,.12)' },
        },
        y: {
          title: { display: true, text: 'Annualised return %', color: '#94a3b8', font: { size: 10 } },
          ticks: { color: '#94a3b8', font: { size: 10 } },
          grid: { color: 'rgba(148,163,184,.12)' },
        },
      },
    },
  });
}


// ═══════════════════════════════════════════════════════════════════
//  PRISM  (risk health, 5y window)
// ═══════════════════════════════════════════════════════════════════

const PRISM_DIMENSIONS = [
  { key: 'F', label: 'Diversification', hint: 'spread across sectors' },
  { key: 'I', label: 'Correlation',     hint: 'do holdings move together' },
  { key: 'N', label: 'Volatility',      hint: 'annualised swing' },
  { key: 'E', label: 'Concentration',   hint: 'largest single position' },
];

function scoreColor(v) {
  if (v >= 70) return '#22c55e';
  if (v >= 40) return '#eab308';
  return '#ef4444';
}

function renderPrism(prism) {
  const body = document.getElementById('prism-body');
  const note = document.getElementById('prism-unavailable');

  if (!prism || !prism.available) {
    body.style.display = 'none';
    note.style.display = 'block';
    note.textContent = (prism && prism.reason) || 'PRISM unavailable.';
    return;
  }

  body.style.display = '';
  note.style.display = 'none';

  const scoreEl = document.getElementById('prism-score');
  scoreEl.textContent = prism.prism_score.toFixed(1);
  scoreEl.style.color = scoreColor(prism.prism_score);

  // Sub-score bars
  const bars = document.getElementById('prism-bars');
  bars.innerHTML = '';
  PRISM_DIMENSIONS.forEach(d => {
    const v = prism.sub_scores[d.key];
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `
      <div class="bar-label">${d.label}<span class="bar-hint">${d.hint}</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${v}%;background:${scoreColor(v)}"></div></div>
      <div class="bar-val">${v.toFixed(1)}</div>`;
    bars.appendChild(row);
  });

  // Benchmark comparison
  const bench = document.getElementById('prism-benchmarks');
  bench.innerHTML = '';
  Object.values(prism.benchmarks).forEach(b => {
    const delta = prism.prism_score - b.score;
    const cls = delta >= 0 ? 'green' : 'red';
    const row = document.createElement('div');
    row.className = 'bench-row';
    row.innerHTML = `
      <span class="bench-label">${b.label}</span>
      <span class="bench-score">${b.score.toFixed(1)}</span>
      <span class="bench-delta ${cls}">${fmtPct(delta).replace('%', '')}</span>`;
    bench.appendChild(row);
  });

  document.getElementById('prism-callout').textContent = prism.callout;

  renderCorrelation(prism.correlation_matrix);
  renderPrismStats(prism.backtest);
  drawPrismBacktest(prism.backtest);
}

function renderCorrelation(matrix) {
  const table = document.getElementById('tbl-corr');
  if (!matrix || !matrix.tickers.length) { table.innerHTML = ''; return; }

  const t = matrix.tickers;
  let html = '<thead><tr><th></th>' + t.map(x => `<th>${x}</th>`).join('') + '</tr></thead><tbody>';

  t.forEach((rowTicker, i) => {
    html += `<tr><th>${rowTicker}</th>`;
    t.forEach((_, j) => {
      const v = matrix.values[i][j];
      // Red = moves together, blue = moves apart. Opacity tracks magnitude.
      const alpha = Math.min(0.85, Math.abs(v) * 0.85);
      const rgb = v >= 0 ? '239,68,68' : '56,189,248';
      html += `<td style="background:rgba(${rgb},${alpha})" title="${rowTicker} vs ${t[j]}">${v.toFixed(2)}</td>`;
    });
    html += '</tr>';
  });

  table.innerHTML = html + '</tbody>';
}

function renderPrismStats(backtest) {
  const el = document.getElementById('prism-stats');
  el.innerHTML = '';
  if (!backtest || !backtest.stats || backtest.stats.portfolio_ann_return === undefined) {
    el.innerHTML = '<p class="sub">Not enough history for a 5-year comparison.</p>';
    return;
  }

  const s = backtest.stats;
  const rows = [
    ['Portfolio annualised', fmtPct(s.portfolio_ann_return), colorCls(s.portfolio_ann_return)],
    ['SPY annualised', fmtPct(s.spy_ann_return), colorCls(s.spy_ann_return)],
    ['Portfolio max drawdown', fmtPct(s.portfolio_max_drawdown), 'red'],
    ['SPY max drawdown', fmtPct(s.spy_max_drawdown), 'red'],
  ];

  rows.forEach(([label, value, cls]) => {
    const div = document.createElement('div');
    div.className = 'stat-cell';
    div.innerHTML = `<div class="kpi-label">${label}</div><div class="stat-val ${cls}">${value}</div>`;
    el.appendChild(div);
  });
}

function drawPrismBacktest(backtest) {
  destroyChart('prismBacktest');
  if (!backtest || !backtest.dates.length) return;

  charts.prismBacktest = new Chart(ctx('chart-prism-backtest'), {
    type: 'line',
    data: {
      labels: backtest.dates,
      datasets: [
        {
          label: 'Portfolio', data: backtest.portfolio, borderColor: '#38bdf8',
          backgroundColor: 'rgba(56,189,248,.12)', fill: true, tension: .3,
          pointRadius: 0, borderWidth: 2,
        },
        {
          label: 'SPY', data: backtest.spy, borderColor: '#94a3b8',
          borderDash: [5, 4], fill: false, tension: .3, pointRadius: 0, borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#94a3b8', font: { size: 11 } } },
        tooltip: { callbacks: { label: c => ` ${c.dataset.label}: $${c.raw.toFixed(2)} per $1` } },
      },
      scales: {
        x: { ticks: { color: '#94a3b8', font: { size: 9 }, maxTicksLimit: 10 }, grid: { display: false } },
        y: {
          ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => '$' + v.toFixed(1) },
          grid: { color: 'rgba(148,163,184,.12)' },
        },
      },
    },
  });
}
