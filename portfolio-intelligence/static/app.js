/* ═══════════════════════════════════════════════════════════════
   Portfolio Intelligence — front end
   Flow: Upload (any files) → Review (one row per purchase, with dates)
         → Story (one dashboard at a time, explained as you scroll)
═══════════════════════════════════════════════════════════════ */
'use strict';

// ── State ────────────────────────────────────────────────────────
let files = [];          // File objects waiting to be read
let holdings = [];       // [{ticker, name, shares, avg_cost, acquired, source}]
let manualItems = [];
let notes = [];
const charts = {};

const C = {
  forest: '#2f6b4f', leaf: '#5fa36a', sage: '#9cc5a1', mint: '#d6ecd9', sky: '#6aa6c8',
  sun: '#e9b949', sand: '#d9c7a0', clay: '#c97b5a', plum: '#8e7cc3', ink: '#1f3a2e', soft: '#7d9087', line: '#e3eadb',
};
const PALETTE = ['#2f6b4f', '#6aa6c8', '#e9b949', '#9cc5a1', '#c97b5a', '#8e7cc3', '#5fa36a', '#d9a066', '#4f8fa8', '#b7c96a', '#a88bb8', '#7fb7a4', '#e2a55c', '#6d8f5f'];

if (window.Chart) {
  Chart.defaults.font.family = "'Nunito', system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = C.soft;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.tooltip.backgroundColor = '#1f3a2e';
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 10;
  Chart.defaults.animation.duration = 900;
}

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ── Boot ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initUpload();
  initManual();
  initReview();
  $('btn-reset').addEventListener('click', reset);
});

// ══════════════════════════════════════════════════════════════════
//  1. Upload
// ══════════════════════════════════════════════════════════════════
function initUpload() {
  const zone = $('drop'), input = $('file-input');
  zone.addEventListener('click', (e) => { if (e.target.tagName !== 'LABEL') input.click(); });
  zone.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.click(); });
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', (e) => { e.preventDefault(); zone.classList.remove('over'); addFiles(e.dataTransfer.files); });
  input.addEventListener('change', () => { addFiles(input.files); input.value = ''; });
  $('sheet-url').addEventListener('input', updateReadButton);
  $('btn-read').addEventListener('click', readAll);
  $('btn-template').addEventListener('click', downloadTemplate);
}

function addFiles(list) {
  for (const f of list) if (!files.some((x) => x.name === f.name && x.size === f.size)) files.push(f);
  renderFileChips();
}

function renderFileChips() {
  $('file-chips').innerHTML = files.map((f, i) =>
    `<span class="file-chip">${esc(f.name)} <button title="Remove" onclick="removeFile(${i})">×</button></span>`).join('');
  updateReadButton();
}
window.removeFile = (i) => { files.splice(i, 1); renderFileChips(); };
function updateReadButton() { $('btn-read').disabled = !files.length && !$('sheet-url').value.trim(); }

async function readAll() {
  clearMsg('upload-msg');
  $('upload-loading').style.display = 'block';
  $('btn-read').disabled = true;
  const fd = new FormData();
  files.forEach((f) => fd.append('files', f));
  if ($('sheet-url').value.trim()) fd.append('sheet_url', $('sheet-url').value.trim());
  try {
    const res = await fetch('/api/parse', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    holdings = data.holdings.map((h) => ({ ...h }));
    notes = [...(data.notes || []), ...(data.errors || []).map((e) => '⚠️ ' + e)];
    goReview();
  } catch (e) {
    showMsg('upload-msg', e.message);
  } finally {
    $('upload-loading').style.display = 'none';
    updateReadButton();
  }
}

function downloadTemplate() {
  const csv = 'Symbol,Shares,Avg Cost,Date of Acquisition\nAAPL,10,150.00,2024-03-01\nMSFT,5,280.00,2025-01-15\nNVDA,2,120.00,2023-11-20\n';
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob([csv], { type: 'text/csv' })), download: 'holdings_template.csv' });
  a.click();
}

// ── Manual entry ────────────────────────────────────────────────
function initManual() {
  $('btn-manual-add').addEventListener('click', addManual);
  $('m-ticker').addEventListener('input', (e) => { e.target.value = e.target.value.toUpperCase(); });
  $('btn-manual-continue').addEventListener('click', () => {
    holdings = manualItems.map((m) => ({ ...m, source: 'typed in' }));
    notes = [];
    goReview();
  });
}
function addManual() {
  const ticker = $('m-ticker').value.trim().toUpperCase();
  const shares = parseFloat($('m-shares').value);
  const cost = parseFloat($('m-cost').value);
  const acquired = $('m-date').value || null;
  if (!ticker || !(shares > 0)) return showMsg('upload-msg', 'Enter a ticker and a share count.');
  clearMsg('upload-msg');
  manualItems.push({ ticker, shares, avg_cost: isNaN(cost) ? null : cost, acquired, name: null });
  ['m-ticker', 'm-shares', 'm-cost', 'm-date'].forEach((id) => { $(id).value = ''; });
  $('m-ticker').focus();
  renderManual();
}
window.removeManual = (i) => { manualItems.splice(i, 1); renderManual(); };
function renderManual() {
  $('manual-list').innerHTML = manualItems.map((h, i) => `<div class="manual-item"><span><b>${esc(h.ticker)}</b> · ${h.shares} shares${h.avg_cost != null ? ` @ $${h.avg_cost.toFixed(2)}` : ''}${h.acquired ? ` · bought ${h.acquired}` : ''}</span><button class="btn-del" onclick="removeManual(${i})">×</button></div>`).join('');
  $('btn-manual-continue').style.display = manualItems.length ? 'inline-flex' : 'none';
}

// ══════════════════════════════════════════════════════════════════
//  2. Review
// ══════════════════════════════════════════════════════════════════
function initReview() {
  $('btn-add-row').addEventListener('click', () => { holdings.push({ ticker: '', shares: null, avg_cost: null, acquired: null, source: 'typed in' }); renderReview(); });
  $('btn-analyze').addEventListener('click', runAnalyze);
}

function goReview() {
  showView('view-review');
  $('btn-reset').style.display = 'inline-flex';
  $('review-notes').innerHTML = notes.map((n) => `<div class="msg info">${esc(n)}</div>`).join('');
  renderReview();
}

function renderReview() {
  const tbody = $('tbody-review');
  tbody.innerHTML = holdings.map((h, i) => `
    <tr class="${h.acquired ? '' : 'missing-date'}">
      <td><input type="text" value="${esc(h.ticker)}" data-i="${i}" data-f="ticker" maxlength="10" style="width:90px;text-transform:uppercase" /></td>
      <td><span class="sub">${esc(h.name || '')}</span></td>
      <td><input type="number" value="${h.shares ?? ''}" data-i="${i}" data-f="shares" step="any" min="0" style="width:110px" /></td>
      <td><input type="number" value="${h.avg_cost ?? ''}" data-i="${i}" data-f="avg_cost" step="any" min="0" placeholder="optional" style="width:120px" /></td>
      <td><input type="date" value="${h.acquired || ''}" data-i="${i}" data-f="acquired" style="width:160px" /></td>
      <td><span class="src" title="${esc(h.source || '')}">${esc(h.source || '')}</span></td>
      <td><button class="btn-del" data-del="${i}" title="Remove">×</button></td>
    </tr>`).join('');
  tbody.querySelectorAll('input').forEach((inp) => inp.addEventListener('change', (e) => {
    const i = +e.target.dataset.i, f = e.target.dataset.f;
    let v = e.target.value;
    if (f === 'ticker') v = v.toUpperCase().trim();
    else if (f === 'acquired') v = v || null;
    else v = v === '' ? null : +v;
    holdings[i][f] = v;
    if (f === 'acquired') e.target.closest('tr').classList.toggle('missing-date', !v);
    updateSummary();
  }));
  tbody.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => { holdings.splice(+b.dataset.del, 1); renderReview(); }));
  updateSummary();
}

function updateSummary() {
  const n = holdings.length, dated = holdings.filter((h) => h.acquired).length;
  const tickers = new Set(holdings.map((h) => h.ticker).filter(Boolean)).size;
  $('review-summary').textContent = `${n} purchase${n === 1 ? '' : 's'} across ${tickers} ticker${tickers === 1 ? '' : 's'} · ${dated} with an acquisition date` + (dated < n ? ' (rows highlighted in yellow need a date for the “since you bought” views)' : '');
}

async function runAnalyze() {
  const valid = holdings.filter((h) => h.ticker && +h.shares > 0);
  if (!valid.length) return showMsg('analyze-msg', 'Add at least one position with a ticker and shares.');
  clearMsg('analyze-msg');
  $('analyze-loading').style.display = 'block';
  $('btn-analyze').disabled = true;
  try {
    const res = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ holdings: valid }) });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    buildStory(data);
    showView('view-story');
  } catch (e) {
    showMsg('analyze-msg', e.message);
  } finally {
    $('analyze-loading').style.display = 'none';
    $('btn-analyze').disabled = false;
  }
}

// ══════════════════════════════════════════════════════════════════
//  3. Story — one dashboard per chapter, explained as you scroll
// ══════════════════════════════════════════════════════════════════
let observer = null;

function buildStory(d) {
  Object.keys(charts).forEach(destroy);
  window._data = d;
  const chapters = [
    chToday(d), chJourney(d), chPositions(d), chPeaks(d), chAllocation(d),
    chYear(d), chRisk(d), chSuggest(d), chTable(d),
  ].filter(Boolean);

  $('story').innerHTML = chapters.map((c, i) => `
    <section class="chapter${c.wide ? ' wide' : ''}" id="ch-${c.id}" data-i="${i}">
      <div class="explain">
        <span class="step">${i + 1} of ${chapters.length} · ${esc(c.rail)}</span>
        <h2>${c.title}</h2>
        <p class="what">${c.what}</p>
        ${c.how ? `<h4>How to read it</h4><ul>${c.how.map((x) => `<li>${x}</li>`).join('')}</ul>` : ''}
        ${c.takeaway && c.takeaway.length ? `<div class="takeaway"><div class="label">🌿 What it means for you</div>${c.takeaway.map((t) => `<p>${t}</p>`).join('')}</div>` : ''}
        ${c.caveat ? `<p class="caveat">${c.caveat}</p>` : ''}
        ${i < chapters.length - 1 ? `<button class="btn next" onclick="document.getElementById('ch-${chapters[i + 1].id}').scrollIntoView({behavior:'smooth'})">Next: ${esc(chapters[i + 1].rail)} ↓</button>` : ''}
      </div>
      <div class="visual">${c.visual}</div>
    </section>`).join('') + `
    <section class="closing">
      <h2>🌱 That’s your portfolio’s story</h2>
      <p class="sub">Change any purchase and run it again, or start over with new files.</p>
      <p style="margin-top:16px"><button class="btn" onclick="showView('view-review')">← Edit holdings</button> <button class="btn btn-primary" onclick="window.scrollTo({top:0,behavior:'smooth'})">Back to the top ↑</button></p>
    </section>`;

  $('rail').innerHTML = `<div class="rail-title">Your story</div>` + chapters.map((c) => `<a href="#ch-${c.id}" data-id="${c.id}"><span class="dot"></span>${esc(c.rail)}</a>`).join('');

  if (!$('progress')) document.body.insertAdjacentHTML('beforeend', '<div id="progress" class="progress"></div>');

  const drawn = new Set();
  const byId = Object.fromEntries(chapters.map((c) => [c.id, c]));
  if (observer) observer.disconnect();
  observer = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const id = e.target.id.slice(3);
      if (e.isIntersecting) {
        e.target.classList.add('in-view');
        if (!drawn.has(id) && byId[id].draw) { drawn.add(id); setTimeout(() => byId[id].draw(), 150); }
      }
    }
    updateActive();
  }, { threshold: [0, 0.15, 0.35, 0.6, 0.85], rootMargin: '-60px 0px 0px 0px' });
  document.querySelectorAll('.chapter').forEach((s) => observer.observe(s));

  window.onscroll = () => {
    const h = document.documentElement;
    const p = h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight);
    const bar = $('progress');
    if (bar) bar.style.width = `${Math.min(100, p * 100)}%`;
    // Keep the "active" highlight in step with slow scrolling too.
    updateActive();
  };
  window.scrollTo({ top: 0 });
}

function updateActive() {
  const mid = window.innerHeight * 0.45;
  let best = null, bestDist = Infinity;
  document.querySelectorAll('.chapter').forEach((s) => {
    const r = s.getBoundingClientRect();
    const dist = r.top <= mid && r.bottom >= mid ? 0 : Math.min(Math.abs(r.top - mid), Math.abs(r.bottom - mid));
    if (dist < bestDist) { bestDist = dist; best = s; }
  });
  if (!best) return;
  document.querySelectorAll('.chapter').forEach((s) => s.classList.toggle('dim', s !== best && s.classList.contains('in-view')));
  const activeIdx = +best.dataset.i;
  document.querySelectorAll('#rail a').forEach((a, i) => { a.classList.toggle('active', i === activeIdx); a.classList.toggle('done', i < activeIdx); });
}

// ── Chapter 1: today ────────────────────────────────────────────
function chToday(d) {
  const s = d.summary, h = d.hindsight;
  const up = s.total_gain >= 0;
  const best = [...d.holdings].sort((a, b) => b.gain_pct - a.gain_pct)[0];
  const takeaway = [
    `Your ${s.positions} holdings are worth <b>${usd(s.total_value)}</b> today, ${up ? 'up' : 'down'} <b class="${up ? 'up' : 'down'}">${usd(Math.abs(s.total_gain))} (${pct(s.total_gain_pct)})</b> on what you paid.`,
  ];
  if (best) takeaway.push(`Your strongest holding so far is <b>${esc(best.ticker)}</b> at ${pct(best.gain_pct)}.`);
  if (d.meta?.dropped_tickers?.length) takeaway.push(`We couldn’t find price history for ${d.meta.dropped_tickers.map(esc).join(', ')}, so ${d.meta.dropped_tickers.length > 1 ? 'they are' : 'it is'} shown at cost and left out of the charts.`);
  return {
    id: 'today', rail: 'Where you stand', title: 'Where you stand today',
    what: 'A snapshot: what your holdings are worth right now, what you paid for them, and the difference.',
    how: ['<b>Value</b> uses the latest closing price.', '<b>Invested</b> is shares × your average cost.', 'The chart shows how much of your money sits in each holding.'],
    takeaway,
    visual: `
      <div class="grid g4">
        ${kpi('Value today', usd(s.total_value), `${s.positions} holdings`, C.mint)}
        ${kpi('Invested', usd(s.total_cost), 'what you paid', '#e8eef6')}
        ${kpi('Gain', `<span class="${up ? 'up' : 'down'}">${signUsd(s.total_gain)}</span>`, pct(s.total_gain_pct), up ? C.mint : '#f6e3da')}
        ${kpi('Since your first buy', h?.available ? `${daysBetween(h.first_date, h.as_of)} days` : '—', h?.available ? `from ${fmtDate(h.first_date)}` : 'add dates to see', '#f7efd9')}
      </div>
      <div class="panel" style="margin-top:16px"><h3>Your holdings by value</h3><p class="hint">Share of today’s portfolio value</p><div class="chart-box tall"><canvas id="c-weights"></canvas></div></div>`,
    draw: () => {
      const top = d.holdings.slice(0, 16);
      mk('weights', 'c-weights', {
        type: 'bar',
        data: { labels: top.map((x) => x.ticker), datasets: [{ data: top.map((x) => x.weight), backgroundColor: top.map((_, i) => PALETTE[i % PALETTE.length]), borderRadius: 8 }] },
        options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${c.raw.toFixed(1)}% · ${usd(top[c.dataIndex].value)}` } } }, scales: { x: { grid: { color: C.line }, ticks: { callback: (v) => v + '%' } }, y: { grid: { display: false }, ticks: { color: C.ink, font: { weight: 700 } } } } },
      });
    },
  };
}

// ── Chapter 2: journey since day one ─────────────────────────────
function chJourney(d) {
  const h = d.hindsight;
  if (!h?.available) return noDates('journey', 'Your journey', 'Your journey since day one', h);
  const t = h.totals;
  const beat = t.vs_spy >= 0;
  return {
    id: 'journey', rail: 'Your journey', title: 'Your journey since day one',
    what: `Starting from your first purchase on ${fmtDate(h.first_date)}, this follows your whole portfolio day by day, adding each holding on the day you bought it.`,
    how: ['<b>Green line</b>: what your holdings were worth each day.', '<b>Dashed line</b>: money you had put in so far. Each step up is a new purchase.', '<b>Blue line</b>: the same money, on the same days, put into the S&P 500 (SPY) instead.'],
    takeaway: [
      `You put in <b>${usd(t.cost)}</b>; it is worth <b>${usd(t.value_now)}</b> now, a ${t.gain_now >= 0 ? 'gain' : 'loss'} of <b class="${t.gain_now >= 0 ? 'up' : 'down'}">${pct(t.return_pct)}</b>.`,
      beat ? `That is <b class="up">${usd(t.vs_spy)} more</b> than the same purchases in the S&P 500 would have made. Your picks have earned their keep. 🌿` : `The same purchases in the S&P 500 would have made <b>${usd(-t.vs_spy)} more</b>. Worth asking whether each pick is adding something an index fund doesn’t.`,
      `Your portfolio’s best day was <b>${fmtDate(t.portfolio_peak_date)}</b>, when it was worth ${usd(t.portfolio_peak_value)}.`,
    ],
    visual: `
      <div class="grid g3">
        ${kpi('Put in', usd(t.cost), `${h.lots.length} purchases`, '#e8eef6')}
        ${kpi('Worth now', usd(t.value_now), pct(t.return_pct), C.mint)}
        ${kpi('vs S&P 500', `<span class="${beat ? 'up' : 'down'}">${signUsd(t.vs_spy)}</span>`, `SPY twin: ${usd(t.spy_value)}`, '#dcebf3')}
      </div>
      <div class="panel" style="margin-top:16px"><h3>Portfolio value since ${fmtDate(h.first_date)}</h3><p class="hint">Daily, in dollars</p><div class="chart-box tall"><canvas id="c-journey"></canvas></div></div>`,
    draw: () => {
      const tl = h.timeline;
      mk('journey', 'c-journey', {
        type: 'line',
        data: { labels: tl.dates.map(shortDate), datasets: [
          area('Your portfolio', tl.value, C.forest, 'rgba(95,163,106,.18)'),
          line('Money put in', tl.invested, C.soft, [6, 5], 'stepped'),
          line('Same money in SPY', tl.spy, C.sky),
        ] },
        options: moneyOpts(),
      });
    },
  };
}

// ── Chapter 3: each position since purchase ──────────────────────
function chPositions(d) {
  const h = d.hindsight;
  if (!h?.available) return null;
  const lots = [...h.lots].sort((a, b) => b.return_pct - a.return_pct);
  const winners = lots.filter((l) => l.return_pct >= 0).length;
  const best = lots[0], worst = lots[lots.length - 1];
  const longest = [...lots].sort((a, b) => b.days_held - a.days_held)[0];
  return {
    id: 'positions', rail: 'Each purchase', title: 'How each purchase has done',
    what: 'Every purchase, measured from its own acquisition date to today.',
    how: ['Bars to the right grew; bars to the left are below what you paid.', 'Hover for the yearly pace (only shown for purchases held 60+ days, since short holds give misleading yearly numbers).'],
    takeaway: [
      `<b>${winners} of ${lots.length}</b> purchases are above what you paid.`,
      `Best: <b>${esc(best.ticker)}</b> ${pct(best.return_pct)} since ${fmtDate(best.acquired)}.${worst && worst !== best ? ` Toughest: <b>${esc(worst.ticker)}</b> ${pct(worst.return_pct)}.` : ''}`,
      `Your longest-held purchase is ${esc(longest.ticker)} (${longest.days_held} days).`,
    ],
    visual: `<div class="panel"><h3>Return since each purchase</h3><p class="hint">% change from your cost to today</p><div class="chart-box" style="height:${Math.max(300, lots.length * 26 + 60)}px"><canvas id="c-positions"></canvas></div></div>`,
    draw: () => mk('positions', 'c-positions', {
      type: 'bar',
      data: { labels: lots.map((l) => `${l.ticker} · ${shortDate(l.acquired)}`), datasets: [{ data: lots.map((l) => l.return_pct), backgroundColor: lots.map((l) => (l.return_pct >= 0 ? C.leaf : C.clay)), borderRadius: 6 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => { const l = lots[c.dataIndex]; return [` ${pct(l.return_pct)} · ${usd(l.cost)} → ${usd(l.value_now)}`, ` held ${l.days_held} days${l.annualised_pct != null ? ` · ${pct(l.annualised_pct)} a year` : ''}`]; } } } }, scales: { x: { grid: { color: C.line }, ticks: { callback: (v) => v + '%' } }, y: { grid: { display: false }, ticks: { color: C.ink, font: { weight: 700 } } } } },
    }),
  };
}

// ── Chapter 4: best exits (hindsight) ────────────────────────────
function chPeaks(d) {
  const h = d.hindsight;
  if (!h?.available) return null;
  const t = h.totals;
  const lots = h.lots.slice(0, 14);
  const top = h.lots[0];
  return {
    id: 'peaks', rail: 'Best possible exits', title: 'What the highs could have given you',
    what: 'For every purchase we looked at every trading day since you bought it and found the highest price it reached. This is what you would have had if you had sold each one at its very best moment.',
    how: ['<b>Grey</b>: what you paid. <b>Green</b>: worth today. <b>Gold</b>: worth at its highest point since you bought.', 'The gap between gold and green is the gain the path offered that you haven’t kept (yet).', 'The line chart adds the gold “best exit” line to your journey.'],
    takeaway: [
      `Selling every purchase at its peak would have turned <b>${usd(t.cost)}</b> into <b>${usd(t.peak_exit_value)}</b> (${pct(t.peak_exit_return_pct)}).`,
      t.capture_pct != null ? `You are holding on to <b>${t.capture_pct.toFixed(0)}%</b> of that best-case gain today. ${t.capture_pct >= 70 ? 'That is a strong capture rate. 🌿' : 'Setting target prices or trailing stops is one way to keep more of the upside.'}` : '',
      top && top.missed > 0 ? `The biggest gap is <b>${esc(top.ticker)}</b>: it reached ${usd(top.peak_price)} on ${fmtDate(top.peak_date)}, ${usd(top.missed)} above today’s value.` : '',
    ].filter(Boolean),
    caveat: 'Hindsight, not a strategy: nobody can sell every top. Use it to see how much each position swung, not as a to-do list. Peaks use the day’s high, a price that actually traded.',
    visual: `
      <div class="grid g3">
        ${kpi('Best-exit value', usd(t.peak_exit_value), pct(t.peak_exit_return_pct), '#f7efd9')}
        ${kpi('Gain the highs offered', usd(t.missed), 'above today’s value', '#f6e3da')}
        ${kpi('Gain you kept', t.capture_pct != null ? `${t.capture_pct.toFixed(0)}%` : '—', 'of the best case', C.mint)}
      </div>
      <div class="panel" style="margin-top:16px"><h3>Paid · today · at the high</h3><p class="hint">Largest gaps first</p><div class="chart-box" style="height:${Math.max(300, lots.length * 34 + 60)}px"><canvas id="c-peaks"></canvas></div></div>
      <div class="panel" style="margin-top:16px"><h3>Your journey with the best-exit ceiling</h3><p class="hint">Gold: each holding valued at its best price so far</p><div class="chart-box"><canvas id="c-ceiling"></canvas></div></div>`,
    draw: () => {
      mk('peaks', 'c-peaks', {
        type: 'bar',
        data: { labels: lots.map((l) => lotLabel(l, h.lots)), datasets: [
          { label: 'Paid', data: lots.map((l) => l.cost), backgroundColor: '#d5dccf', borderRadius: 5 },
          { label: 'Today', data: lots.map((l) => l.value_now), backgroundColor: C.leaf, borderRadius: 5 },
          { label: 'At the high', data: lots.map((l) => l.peak_value), backgroundColor: C.sun, borderRadius: 5 },
        ] },
        options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${usd(c.raw)}`, afterBody: (items) => { const l = lots[items[0].dataIndex]; return [`High ${usd(l.peak_price)} on ${fmtDate(l.peak_date)}`, `Bought ${fmtDate(l.acquired)}`]; } } } }, scales: { x: { grid: { color: C.line }, ticks: { callback: (v) => usdShort(v) } }, y: { grid: { display: false }, ticks: { color: C.ink, font: { weight: 700 } } } } },
      });
      const tl = h.timeline;
      mk('ceiling', 'c-ceiling', {
        type: 'line',
        data: { labels: tl.dates.map(shortDate), datasets: [
          area('Best exit so far', tl.best_exit, C.sun, 'rgba(233,185,73,.14)'),
          area('Your portfolio', tl.value, C.forest, 'rgba(95,163,106,.18)'),
          line('Money put in', tl.invested, C.soft, [6, 5], 'stepped'),
        ] },
        options: moneyOpts(),
      });
    },
  };
}

// ── Chapter 5: allocation ────────────────────────────────────────
function chAllocation(d) {
  const sectors = Object.entries(d.sector_allocation).sort((a, b) => b[1] - a[1]);
  const total = sectors.reduce((s, [, v]) => s + v, 0) || 1;
  const [topName, topVal] = sectors[0] || ['—', 0];
  const share = topVal / total * 100;
  return {
    id: 'allocation', rail: 'Where it’s planted', title: 'Where your money is planted',
    what: 'How your portfolio is spread across sectors of the economy.',
    how: ['Each slice is a sector’s share of today’s value.', 'A healthy garden has several kinds of plants: if one sector struggles, the others can carry you.'],
    takeaway: [
      `Your biggest sector is <b>${esc(topName)}</b> at <b>${share.toFixed(0)}%</b> of the portfolio.`,
      share > 40 ? 'That is a lot in one place. Adding holdings from other sectors would soften the blow if it has a bad year.' : `You are spread across ${sectors.length} sectors, which is a sturdy base. 🌿`,
    ],
    visual: `<div class="grid g2">
      <div class="panel"><h3>By sector</h3><div class="chart-box tall"><canvas id="c-sector"></canvas></div></div>
      <div class="panel"><h3>Sector list</h3><div id="sector-list"></div></div></div>`,
    draw: () => {
      mk('sector', 'c-sector', {
        type: 'doughnut',
        data: { labels: sectors.map((s) => s[0]), datasets: [{ data: sectors.map((s) => s[1]), backgroundColor: sectors.map((_, i) => PALETTE[i % PALETTE.length]), borderColor: '#fff', borderWidth: 3 }] },
        options: { cutout: '58%', plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (c) => ` ${c.label}: ${(c.raw / total * 100).toFixed(1)}% · ${usd(c.raw)}` } } } },
      });
      $('sector-list').innerHTML = sectors.map(([n, v], i) => `<div class="bar-row"><span>${esc(n)}</span><div class="bar-track"><div class="bar-fill" style="width:${(v / total * 100).toFixed(1)}%;background:${PALETTE[i % PALETTE.length]}"></div></div><span class="num">${(v / total * 100).toFixed(0)}%</span></div>`).join('');
    },
  };
}

// ── Chapter 6: past year vs market ───────────────────────────────
function chYear(d) {
  const p = d.performance;
  if (!p?.dates?.length) return null;
  const mine = p.portfolio.at(-1), spy = p.spy.at(-1);
  const ahead = mine - spy;
  return {
    id: 'year', rail: 'The last 12 months', title: 'The last 12 months vs the market',
    what: 'Your current holdings over the past year, against the same amount of money in the S&P 500.',
    how: ['Both lines start from your total cost, so the comparison is dollar for dollar.', 'This view assumes you held today’s positions all year; the “journey” view uses your real purchase dates.'],
    takeaway: [
      `Over the last year these holdings moved <b>${pct(mine)}</b> while the S&P 500 moved <b>${pct(spy)}</b>.`,
      ahead >= 0 ? `You’re <b class="up">${Math.abs(ahead).toFixed(1)} points ahead</b> of the market. 🌿` : `You’re <b class="down">${Math.abs(ahead).toFixed(1)} points behind</b>; the suggested-changes view shows one way to close the gap.`,
    ],
    visual: `<div class="panel"><h3>Profit/loss vs S&P 500</h3><p class="hint">% of cost, last 12 months</p><div class="chart-box tall"><canvas id="c-year"></canvas></div></div>`,
    draw: () => mk('year', 'c-year', {
      type: 'line',
      data: { labels: p.dates.map(shortDate), datasets: [area('Your holdings', p.portfolio, C.forest, 'rgba(95,163,106,.18)'), line('S&P 500 (SPY)', p.spy, C.sky, [5, 4])] },
      options: { interaction: { mode: 'index', intersect: false }, plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${pct(c.raw)}` } } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { grid: { color: C.line }, ticks: { callback: (v) => v + '%' } } } },
    }),
  };
}

// ── Chapter 7: risk health (PRISM) ───────────────────────────────
function chRisk(d) {
  const pr = d.prism;
  if (!pr?.available) return null;
  const dims = [['F', 'Diversification', 'spread across sectors'], ['I', 'Independence', 'holdings not moving in lockstep'], ['N', 'Calm', 'how gently it swings'], ['E', 'Balance', 'no single name dominating']];
  const band = pr.prism_score >= 70 ? 'healthy' : pr.prism_score >= 40 ? 'growing, with a few weak spots' : 'fragile right now';
  const tone = (v) => (v >= 70 ? C.leaf : v >= 40 ? C.sun : C.clay);
  const weakest = dims.reduce((a, b) => (pr.sub_scores[b[0]] < pr.sub_scores[a[0]] ? b : a));
  return {
    id: 'risk', rail: 'Risk health', title: 'How sturdy is it?',
    what: 'The PRISM score rates how well the portfolio is built to weather bad days, from 0 to 100, using five years of prices.',
    how: ['Four parts, each 0–100: higher is healthier.', 'The grid shows how closely each pair of holdings moves together. Deep green means they move as one, so they protect each other less.'],
    takeaway: [`Your portfolio scores <b>${pr.prism_score.toFixed(0)}/100</b>: ${band}.`, `The area to strengthen first is <b>${weakest[1]}</b>. ${esc(pr.callout)}`],
    visual: `<div class="grid">
      <div class="panel"><div class="score-ring"><div class="score-num" style="color:${tone(pr.prism_score)}">${pr.prism_score.toFixed(0)}</div><div><b>PRISM score</b><div class="sub">out of 100</div></div></div>
        ${dims.map(([k, n, h]) => `<div class="bar-row"><span><b>${n}</b><br><span class="sub">${h}</span></span><div class="bar-track"><div class="bar-fill" style="width:${pr.sub_scores[k]}%;background:${tone(pr.sub_scores[k])}"></div></div><span class="num">${pr.sub_scores[k].toFixed(0)}</span></div>`).join('')}
        ${Object.values(pr.benchmarks).map((b) => `<div class="bench-row"><span>${esc(b.label)}</span><b>${b.score.toFixed(0)}</b></div>`).join('')}
      </div>
      <div class="panel"><h3>Do your holdings move together?</h3><p class="hint">Correlation of daily returns, 5 years</p><div style="overflow-x:auto">${matrix(pr.correlation_matrix)}</div></div></div>`,
  };
}

// ── Chapter 8: suggested changes (its own dashboard) ─────────────
let candidateTickers = [];

function chSuggest(d) {
  const o = d.optimization;
  if (!o?.available) return null;
  const im = o.impact;
  const moves = o.trades.filter((t) => t.action !== 'Keep');
  const extra = (im.dollars_per_year_after ?? 0) - (im.dollars_per_year_now ?? 0);
  return {
    id: 'suggest', rail: 'Suggested changes', title: 'A greener mix: suggested changes',
    what: `The same stocks you own, re-weighted to earn the most return for each unit of risk over the past year (no single holding above ${o.max_position_pct}%). Below: exactly what would change, and what it would have done to your returns.`,
    how: ['<b>Add</b>/<b>Trim</b>/<b>Exit</b> rows are the trades that turn today’s mix into the suggested one.', 'The growth chart replays the last year with each mix, starting from $1.', 'Expected returns are last year’s averages, a rough guide rather than a forecast.'],
    takeaway: [
      `Expected yearly return: <b>${pct(im.return_now_pct)}</b> now → <b class="up">${pct(im.return_after_pct)}</b> with the suggested mix${im.dollars_per_year_now != null ? `, about <b>${signUsd(extra)}</b> a year on your current value` : ''}.`,
      `Risk (yearly swing): ${plainPct(im.risk_now_pct)} → ${plainPct(im.risk_after_pct)}. Return per unit of risk (Sharpe): ${im.sharpe_now.toFixed(2)} → <b>${im.sharpe_after.toFixed(2)}</b>.`,
      `It would move about <b>${im.turnover_pct.toFixed(0)}%</b> of your portfolio across ${moves.length} trades. Mind taxes and trading costs before acting.`,
    ],
    caveat: 'Built from one year of history: it shows what would have worked, not what will. Not financial advice.',
    visual: `
      <div class="grid g4">
        ${kpi('Expected return', `${pct(im.return_after_pct)}`, `from ${pct(im.return_now_pct)} today`, C.mint)}
        ${kpi('Per year, in dollars', im.dollars_per_year_after != null ? usd(im.dollars_per_year_after) : '—', im.dollars_per_year_now != null ? `from ${usd(im.dollars_per_year_now)}` : '', '#f7efd9')}
        ${kpi('Yearly swing', plainPct(im.risk_after_pct), `from ${plainPct(im.risk_now_pct)}`, '#dcebf3')}
        ${kpi('Sharpe', im.sharpe_after.toFixed(2), `from ${im.sharpe_now.toFixed(2)}`, '#ece6f6')}
      </div>
      <div class="grid g2" style="margin-top:16px">
        <div class="panel"><h3>Growth of $1 over the past year</h3><p class="hint">Your mix vs the suggested mix vs S&P 500</p><div class="chart-box"><canvas id="c-growth"></canvas></div></div>
        <div class="panel"><h3>Today vs suggested weights</h3><p class="hint">% of portfolio</p><div class="chart-box"><canvas id="c-weights2"></canvas></div></div>
      </div>
      <div class="panel" style="margin-top:16px"><h3>The trades</h3><p class="hint">Dollar and share amounts use today’s value and prices</p>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Ticker</th><th>Action</th><th class="num">Now</th><th class="num">Suggested</th><th class="num">Change</th><th class="num">$ amount</th><th class="num">Shares</th><th class="num">Exp. return</th></tr></thead><tbody>
        ${o.trades.map((t) => `<tr><td><b>${esc(t.ticker)}</b></td><td><span class="pill pill-${t.action.toLowerCase()}">${t.action}</span></td><td class="num">${t.current_pct.toFixed(1)}%</td><td class="num">${t.target_pct.toFixed(1)}%</td><td class="num ${t.change_pct >= 0 ? 'up' : 'down'}">${t.change_pct >= 0 ? '+' : ''}${t.change_pct.toFixed(1)} pts</td><td class="num">${t.dollars != null ? signUsd(t.dollars) : '—'}</td><td class="num">${t.shares != null ? (t.shares >= 0 ? '+' : '') + t.shares.toFixed(3) : '—'}</td><td class="num">${pct(t.exp_return_pct)}</td></tr>`).join('')}
        </tbody></table></div></div>

      <div style="margin-top:16px;text-align:right">
        <button class="btn btn-primary" onclick="downloadReport()">&#8681; Download report</button>
      </div>

      <div class="panel candidate-panel" style="margin-top:24px">
        <h3>Considering new stocks?</h3>
        <p class="hint">Add tickers you are thinking about buying. We will re-run the optimizer with them in the mix and show how they would change your allocation and PRISM score.</p>
        <div class="candidate-row">
          <input type="text" id="candidate-input" placeholder="e.g. TSLA" maxlength="8" />
          <button id="btn-add-candidate" class="btn">+ Add</button>
          <button id="btn-reoptimize" class="btn btn-primary" style="display:none">Re-optimize with these &#8594;</button>
        </div>
        <div id="candidate-chips" class="file-chips"></div>
        <div id="reopt-loading" class="loading-wrap" style="display:none"><div class="spinner"></div><p>Running optimizer with new stocks&#8230;</p><p class="sub">Downloading price history for candidates</p></div>
        <div id="reopt-msg" class="msg" style="display:none"></div>
        <div id="reopt-results"></div>
      </div>`,
    draw: () => {
      const g = o.growth;
      if (g.dates.length) mk('growth', 'c-growth', {
        type: 'line',
        data: { labels: g.dates.map(shortDate), datasets: [line('Your mix', g.current, C.soft), area('Suggested mix', g.optimal, C.forest, 'rgba(95,163,106,.16)'), ...(g.spy.length ? [line('S&P 500', g.spy, C.sky, [5, 4])] : [])] },
        options: { interaction: { mode: 'index', intersect: false }, plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: $${c.raw.toFixed(3)}` } } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 7 } }, y: { grid: { color: C.line }, ticks: { callback: (v) => '$' + v.toFixed(2) } } } },
      });
      const tk = [...o.trades].sort((a, b) => b.target_pct - a.target_pct).slice(0, 14);
      mk('weights2', 'c-weights2', {
        type: 'bar',
        data: { labels: tk.map((t) => t.ticker), datasets: [{ label: 'Today', data: tk.map((t) => t.current_pct), backgroundColor: '#cfd8c8', borderRadius: 5 }, { label: 'Suggested', data: tk.map((t) => t.target_pct), backgroundColor: C.leaf, borderRadius: 5 }] },
        options: { plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${c.raw.toFixed(1)}%` } } }, scales: { x: { grid: { display: false } }, y: { grid: { color: C.line }, ticks: { callback: (v) => v + '%' } } } },
      });
      initCandidates();
    },
  };
}


function initCandidates() {
  const input = $('candidate-input'), addBtn = $('btn-add-candidate'), reoptBtn = $('btn-reoptimize');
  if (!input) return;
  input.addEventListener('input', function() { input.value = input.value.toUpperCase(); });
  input.addEventListener('keydown', function(e) { if (e.key === 'Enter') addCandidate(); });
  addBtn.addEventListener('click', addCandidate);
  reoptBtn.addEventListener('click', runReoptimize);
  renderCandidateChips();
}

function addCandidate() {
  var input = $('candidate-input');
  var ticker = input.value.trim().toUpperCase();
  if (!ticker) return;
  var existing = new Set(holdings.map(function(h) { return h.ticker; }));
  if (existing.has(ticker)) { showMsg('reopt-msg', ticker + ' is already in your portfolio.'); return; }
  if (candidateTickers.includes(ticker)) { showMsg('reopt-msg', ticker + ' is already added.'); return; }
  clearMsg('reopt-msg');
  candidateTickers.push(ticker);
  input.value = '';
  input.focus();
  renderCandidateChips();
}

window.removeCandidate = function(i) { candidateTickers.splice(i, 1); renderCandidateChips(); };

function renderCandidateChips() {
  var container = $('candidate-chips');
  if (!container) return;
  container.innerHTML = candidateTickers.map(function(t, i) {
    return '<span class="file-chip candidate-chip">' + esc(t) + ' <button title="Remove" onclick="removeCandidate(' + i + ')">x</button></span>';
  }).join('');
  var btn = $('btn-reoptimize');
  if (btn) btn.style.display = candidateTickers.length ? 'inline-flex' : 'none';
}

async function runReoptimize() {
  if (!candidateTickers.length) return;
  clearMsg('reopt-msg');
  $('reopt-loading').style.display = 'block';
  $('btn-reoptimize').disabled = true;
  $('reopt-results').innerHTML = '';

  var valid = holdings.filter(function(h) { return h.ticker && +h.shares > 0; });
  try {
    var res = await fetch('/api/reoptimize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ holdings: valid, candidates: candidateTickers }),
    });
    var data = await res.json();
    if (data.error) throw new Error(data.error);
    renderReoptResults(data);
  } catch (e) {
    showMsg('reopt-msg', e.message);
  } finally {
    $('reopt-loading').style.display = 'none';
    $('btn-reoptimize').disabled = false;
  }
}

function renderReoptResults(data) {
  var container = $('reopt-results');
  var o = data.optimization;
  var pc = data.prism_current;
  var ps = data.prism_suggested;

  if (!o || !o.available) {
    container.innerHTML = '<div class="msg info">' + esc(o && o.reason || 'Could not run optimizer.') + '</div>';
    return;
  }

  if (data.invalid_candidates && data.invalid_candidates.length) {
    showMsg('reopt-msg', 'Could not find price data for: ' + data.invalid_candidates.join(', '), 'info');
  }

  var im = o.impact;
  var moves = o.trades.filter(function(t) { return t.action !== 'Keep' || t.current_pct > 0; });
  var newPicks = o.trades.filter(function(t) { return t.current_pct === 0 && t.target_pct > 0.5; });
  var notUsed = data.candidates.filter(function(c) { return !newPicks.some(function(t) { return t.ticker === c; }); });

  var prismHtml = '';
  if (pc && pc.available && ps && ps.available) {
    var delta = ps.prism_score - pc.prism_score;
    var up = delta >= 0;
    var dims = [['F', 'Diversification'], ['I', 'Independence'], ['N', 'Calm'], ['E', 'Balance']];
    prismHtml = '<div class="panel" style="margin-top:16px">' +
      '<h3>PRISM score impact</h3>' +
      '<p class="hint">How the suggested mix (with new stocks) would change your risk health</p>' +
      '<div class="grid g3" style="margin-top:12px">' +
        kpi('Current PRISM', pc.prism_score.toFixed(0), 'your portfolio now', '#e8eef6') +
        kpi('Suggested PRISM', ps.prism_score.toFixed(0), 'with changes applied', up ? C.mint : '#f6e3da') +
        kpi('Change', '<span class="' + (up ? 'up' : 'down') + '">' + (delta >= 0 ? '+' : '') + delta.toFixed(1) + '</span>', up ? 'healthier' : 'riskier', up ? C.mint : '#f6e3da') +
      '</div>' +
      '<div style="margin-top:12px">' +
        dims.map(function(d) {
          var before = pc.sub_scores[d[0]], after = ps.sub_scores[d[0]], dd = after - before;
          return '<div class="bar-row"><span><b>' + d[1] + '</b></span><span class="num">' +
            before.toFixed(0) + ' → ' + after.toFixed(0) +
            ' <span class="' + (dd >= 0 ? 'up' : 'down') + '" style="font-size:0.85em">(' + (dd >= 0 ? '+' : '') + dd.toFixed(1) + ')</span></span></div>';
        }).join('') +
      '</div></div>';
  }

  var newPicksHtml = '';
  if (newPicks.length) {
    newPicksHtml = '<div style="margin-top:8px">' + newPicks.map(function(t) {
      return '<span class="file-chip" style="background:' + C.mint + ';border-color:' + C.leaf + '"><b>' +
        esc(t.ticker) + '</b> — ' + t.target_pct.toFixed(1) + '% suggested, exp. return ' + pct(t.exp_return_pct) + '</span>';
    }).join(' ') + '</div>';
  }
  if (notUsed.length) {
    newPicksHtml += '<p class="sub" style="margin-top:8px">The optimizer did not include ' +
      notUsed.map(esc).join(', ') + ' — their risk/return profile did not improve the mix.</p>';
  }

  container.innerHTML =
    '<div style="margin-top:16px;padding-top:16px;border-top:2px solid ' + C.line + '">' +
      '<h3>With ' + data.candidates.map(esc).join(', ') + ' in the mix</h3>' +
      newPicksHtml +
      '<div class="grid g4" style="margin-top:12px">' +
        kpi('Expected return', pct(im.return_after_pct), 'from ' + pct(im.return_now_pct), C.mint) +
        kpi('Per year', im.dollars_per_year_after != null ? usd(im.dollars_per_year_after) : '—', im.dollars_per_year_now != null ? 'from ' + usd(im.dollars_per_year_now) : '', '#f7efd9') +
        kpi('Yearly swing', plainPct(im.risk_after_pct), 'from ' + plainPct(im.risk_now_pct), '#dcebf3') +
        kpi('Sharpe', im.sharpe_after.toFixed(2), 'from ' + im.sharpe_now.toFixed(2), '#ece6f6') +
      '</div>' +
      prismHtml +
      '<div class="panel" style="margin-top:16px"><h3>Updated trades</h3>' +
        '<p class="hint">Includes your current holdings and the new candidates</p>' +
        '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
          '<th>Ticker</th><th>Action</th><th class="num">Now</th><th class="num">Suggested</th>' +
          '<th class="num">Change</th><th class="num">$ amount</th><th class="num">Exp. return</th>' +
        '</tr></thead><tbody>' +
        moves.map(function(t) {
          var isNew = t.current_pct === 0 && t.target_pct > 0;
          return '<tr' + (isNew ? ' style="background:rgba(95,163,106,.08)"' : '') + '>' +
            '<td><b>' + esc(t.ticker) + '</b>' + (isNew ? ' <span class="pill pill-add" style="font-size:0.7em">NEW</span>' : '') + '</td>' +
            '<td><span class="pill pill-' + t.action.toLowerCase() + '">' + t.action + '</span></td>' +
            '<td class="num">' + t.current_pct.toFixed(1) + '%</td>' +
            '<td class="num">' + t.target_pct.toFixed(1) + '%</td>' +
            '<td class="num ' + (t.change_pct >= 0 ? 'up' : 'down') + '">' + (t.change_pct >= 0 ? '+' : '') + t.change_pct.toFixed(1) + ' pts</td>' +
            '<td class="num">' + (t.dollars != null ? signUsd(t.dollars) : '—') + '</td>' +
            '<td class="num">' + pct(t.exp_return_pct) + '</td></tr>';
        }).join('') +
        '</tbody></table></div></div>' +
    '</div>';
}

function downloadReport() {
  var d = window._data;
  if (!d) return;
  var s = d.summary;
  var pr = d.prism;
  var o = d.optimization;
  if (!o || !o.available) return;
  var im = o.impact;
  var today = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

  var up = s.total_gain >= 0;
  var prismHtml = '';
  if (pr && pr.available) {
    var dims = [['F', 'Diversification'], ['I', 'Independence'], ['N', 'Calm'], ['E', 'Balance']];
    prismHtml = '<div class="section"><h2>PRISM Risk Health Score</h2>' +
      '<div class="score-big">' + pr.prism_score.toFixed(0) + '<span class="score-label"> / 100</span></div>' +
      '<p class="score-band">' + (pr.prism_score >= 70 ? 'Healthy' : pr.prism_score >= 40 ? 'Growing, with a few weak spots' : 'Fragile') + '</p>' +
      '<table><thead><tr><th>Dimension</th><th>Score</th><th>Bar</th></tr></thead><tbody>' +
      dims.map(function(dd) {
        var v = pr.sub_scores[dd[0]];
        var color = v >= 70 ? '#5fa36a' : v >= 40 ? '#e9b949' : '#c97b5a';
        return '<tr><td>' + dd[1] + '</td><td class="num">' + v.toFixed(0) + '</td>' +
          '<td><div class="bar-bg"><div class="bar-fg" style="width:' + v + '%;background:' + color + '"></div></div></td></tr>';
      }).join('') +
      '</tbody></table></div>';
  }

  var afterPrismHtml = '';
  if (pr && pr.available && o.strategies && o.strategies.optimal) {
    var optWeights = o.strategies.optimal.weights;
    afterPrismHtml = '<div class="section"><h2>Projected PRISM After Changes</h2>' +
      '<p class="hint">Based on the suggested optimal weights applied to 5-year price history</p>' +
      '<table><thead><tr><th>Metric</th><th>Current</th><th>After Changes</th><th>Change</th></tr></thead><tbody>' +
      '<tr><td><b>Expected Return</b></td><td>' + pct(im.return_now_pct) + '</td><td>' + pct(im.return_after_pct) + '</td>' +
        '<td class="' + (im.return_after_pct >= im.return_now_pct ? 'up' : 'dn') + '">' + (im.return_after_pct - im.return_now_pct >= 0 ? '+' : '') + (im.return_after_pct - im.return_now_pct).toFixed(1) + ' pts</td></tr>' +
      '<tr><td><b>Yearly Swing (Risk)</b></td><td>' + plainPct(im.risk_now_pct) + '</td><td>' + plainPct(im.risk_after_pct) + '</td>' +
        '<td class="' + (im.risk_after_pct <= im.risk_now_pct ? 'up' : 'dn') + '">' + (im.risk_after_pct - im.risk_now_pct >= 0 ? '+' : '') + (im.risk_after_pct - im.risk_now_pct).toFixed(1) + ' pts</td></tr>' +
      '<tr><td><b>Sharpe Ratio</b></td><td>' + im.sharpe_now.toFixed(2) + '</td><td>' + im.sharpe_after.toFixed(2) + '</td>' +
        '<td class="' + (im.sharpe_after >= im.sharpe_now ? 'up' : 'dn') + '">' + (im.sharpe_after - im.sharpe_now >= 0 ? '+' : '') + (im.sharpe_after - im.sharpe_now).toFixed(2) + '</td></tr>';
    if (im.dollars_per_year_now != null && im.dollars_per_year_after != null) {
      var dollarDelta = im.dollars_per_year_after - im.dollars_per_year_now;
      afterPrismHtml += '<tr><td><b>Est. Annual Income</b></td><td>' + usd(im.dollars_per_year_now) + '</td><td>' + usd(im.dollars_per_year_after) + '</td>' +
        '<td class="' + (dollarDelta >= 0 ? 'up' : 'dn') + '">' + signUsd(dollarDelta) + '</td></tr>';
    }
    afterPrismHtml += '</tbody></table></div>';
  }

  var tradesHtml = '<div class="section"><h2>Suggested Trades</h2>' +
    '<p class="hint">No single holding above ' + o.max_position_pct + '% — turnover ' + im.turnover_pct.toFixed(0) + '% of portfolio</p>' +
    '<table><thead><tr><th>Ticker</th><th>Action</th><th class="num">Now</th><th class="num">Suggested</th><th class="num">Change</th><th class="num">$ Amount</th><th class="num">Exp. Return</th></tr></thead><tbody>' +
    o.trades.map(function(t) {
      return '<tr><td><b>' + esc(t.ticker) + '</b></td>' +
        '<td><span class="pill pill-' + t.action.toLowerCase() + '">' + t.action + '</span></td>' +
        '<td class="num">' + t.current_pct.toFixed(1) + '%</td>' +
        '<td class="num">' + t.target_pct.toFixed(1) + '%</td>' +
        '<td class="num ' + (t.change_pct >= 0 ? 'up' : 'dn') + '">' + (t.change_pct >= 0 ? '+' : '') + t.change_pct.toFixed(1) + ' pts</td>' +
        '<td class="num">' + (t.dollars != null ? signUsd(t.dollars) : '') + '</td>' +
        '<td class="num">' + pct(t.exp_return_pct) + '</td></tr>';
    }).join('') +
    '</tbody></table></div>';

  var holdingsHtml = '<div class="section"><h2>Current Holdings</h2>' +
    '<table><thead><tr><th>Ticker</th><th>Sector</th><th class="num">Value</th><th class="num">Weight</th><th class="num">Gain</th></tr></thead><tbody>' +
    d.holdings.map(function(h) {
      return '<tr><td><b>' + esc(h.ticker) + '</b></td><td>' + esc(h.sector || '') + '</td>' +
        '<td class="num">' + usd(h.value) + '</td><td class="num">' + h.weight.toFixed(1) + '%</td>' +
        '<td class="num ' + (h.gain >= 0 ? 'up' : 'dn') + '">' + pct(h.gain_pct) + '</td></tr>';
    }).join('') +
    '</tbody></table></div>';

  var html = '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>Portfolio Intelligence Report</title><style>' +
    '*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }' +
    'body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: #1f3a2e; background: #fff; padding: 40px; max-width: 900px; margin: 0 auto; font-size: 14px; line-height: 1.5; }' +
    '.header { text-align: center; margin-bottom: 36px; padding-bottom: 24px; border-bottom: 2px solid #dfe7d6; }' +
    '.header h1 { font-size: 26px; color: #2f6b4f; margin-bottom: 4px; }' +
    '.header .date { color: #7d9087; font-size: 13px; }' +
    '.section { margin-bottom: 32px; }' +
    '.section h2 { font-size: 18px; color: #2f6b4f; border-bottom: 1px solid #dfe7d6; padding-bottom: 6px; margin-bottom: 14px; }' +
    '.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }' +
    '.kpi-box { background: #f5f7ef; border: 1px solid #dfe7d6; border-radius: 10px; padding: 14px 16px; }' +
    '.kpi-box .label { font-size: 11px; font-weight: 700; color: #7d9087; text-transform: uppercase; letter-spacing: .04em; }' +
    '.kpi-box .val { font-size: 22px; font-weight: 800; margin-top: 2px; }' +
    '.kpi-box .sub { font-size: 12px; color: #4d6558; }' +
    'table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 8px; }' +
    'th { text-align: left; font-size: 11px; font-weight: 700; color: #7d9087; text-transform: uppercase; letter-spacing: .04em; padding: 8px 10px; border-bottom: 2px solid #dfe7d6; }' +
    'td { padding: 6px 10px; border-bottom: 1px solid #eef3e6; }' +
    '.num { text-align: right; font-variant-numeric: tabular-nums; }' +
    '.up { color: #2f6b4f; }' +
    '.dn { color: #c97b5a; }' +
    '.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }' +
    '.pill-add { background: #d6ecd9; color: #2f6b4f; }' +
    '.pill-trim { background: #efe4cc; color: #8a6a1f; }' +
    '.pill-exit { background: #f6e3da; color: #c97b5a; }' +
    '.pill-keep { background: #eef3e6; color: #4d6558; }' +
    '.score-big { font-size: 48px; font-weight: 800; color: #2f6b4f; text-align: center; margin: 12px 0 4px; }' +
    '.score-label { font-size: 20px; font-weight: 400; color: #7d9087; }' +
    '.score-band { text-align: center; color: #4d6558; margin-bottom: 16px; }' +
    '.bar-bg { height: 8px; background: #eef3e6; border-radius: 99px; overflow: hidden; }' +
    '.bar-fg { height: 100%; border-radius: 99px; }' +
    '.hint { color: #7d9087; font-size: 12px; margin-bottom: 10px; }' +
    '.footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #dfe7d6; text-align: center; font-size: 11px; color: #7d9087; }' +
    '@media print { body { padding: 20px; } .section { break-inside: avoid; } }' +
    '</style></head><body>' +
    '<div class="header"><h1>Portfolio Intelligence Report</h1><p class="date">' + today + '</p></div>' +

    '<div class="section"><h2>Portfolio Snapshot</h2><div class="kpis">' +
      '<div class="kpi-box"><div class="label">Total Value</div><div class="val">' + usd(s.total_value) + '</div><div class="sub">' + s.positions + ' holdings</div></div>' +
      '<div class="kpi-box"><div class="label">Total Invested</div><div class="val">' + usd(s.total_cost) + '</div></div>' +
      '<div class="kpi-box"><div class="label">Total Gain</div><div class="val ' + (up ? 'up' : 'dn') + '">' + signUsd(s.total_gain) + '</div><div class="sub">' + pct(s.total_gain_pct) + '</div></div>' +
    '</div></div>' +

    holdingsHtml +
    prismHtml +
    afterPrismHtml +
    tradesHtml +

    '<div class="footer">Generated by Portfolio Intelligence. Built from historical data — not financial advice.</div>' +
    '</body></html>';

  var blob = new Blob([html], { type: 'text/html' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = 'portfolio-report-' + new Date().toISOString().slice(0, 10) + '.html';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}


// ── Chapter 9: every position ────────────────────────────────────
function chTable(d) {
  const h = d.hindsight;
  const lots = h?.available ? h.lots.slice().sort((a, b) => b.value_now - a.value_now) : null;
  return {
    id: 'table', rail: 'Every holding', title: 'Every holding, in one place', wide: true,
    what: 'The full detail behind the story, one row per purchase.',
    how: ['<b>High since buy</b> is the best price reached after you bought, with its date.', '<b>Kept</b> is the share of that best-case gain you still hold.'],
    takeaway: [],
    visual: `<div class="panel"><div class="tbl-wrap"><table class="tbl"><thead><tr>
      ${lots ? '<th>Ticker</th><th>Bought</th><th class="num">Shares</th><th class="num">Cost</th><th class="num">Value</th><th class="num">Return</th><th class="num">Per year</th><th class="num">High since buy</th><th class="num">Kept</th><th class="num">vs SPY</th>'
        : '<th>Ticker</th><th>Sector</th><th class="num">Shares</th><th class="num">Avg cost</th><th class="num">Price</th><th class="num">Value</th><th class="num">Gain</th><th class="num">Weight</th>'}
      </tr></thead><tbody>
      ${lots ? lots.map((l) => `<tr><td><b>${esc(l.ticker)}</b></td><td>${fmtDate(l.acquired)}</td><td class="num">${fmtNum(l.shares)}</td><td class="num">${usd(l.cost)}</td><td class="num">${usd(l.value_now)}</td><td class="num ${l.return_pct >= 0 ? 'up' : 'down'}">${pct(l.return_pct)}</td><td class="num">${l.annualised_pct != null ? pct(l.annualised_pct) : '—'}</td><td class="num">${usd(l.peak_price)}<div class="sub">${fmtDate(l.peak_date)}</div></td><td class="num">${l.capture_pct != null ? l.capture_pct.toFixed(0) + '%' : '—'}</td><td class="num ${l.vs_spy >= 0 ? 'up' : 'down'}">${l.vs_spy != null ? signUsd(l.vs_spy) : '—'}</td></tr>`).join('')
        : d.holdings.map((p) => `<tr><td><b>${esc(p.ticker)}</b></td><td>${esc(p.sector)}</td><td class="num">${fmtNum(p.shares)}</td><td class="num">${usd(p.avg_cost)}</td><td class="num">${usd(p.current_price)}</td><td class="num">${usd(p.value)}</td><td class="num ${p.gain >= 0 ? 'up' : 'down'}">${pct(p.gain_pct)}</td><td class="num">${p.weight.toFixed(1)}%</td></tr>`).join('')}
      </tbody></table></div></div>`,
  };
}

function noDates(id, rail, title, h) {
  return {
    id, rail, title,
    what: 'This view follows every purchase from the day you made it.',
    takeaway: [h?.reason || 'Add acquisition dates to your holdings to unlock it.'],
    visual: `<div class="panel"><p>📅 Go back to <a class="link" onclick="showView('view-review')">your holdings</a>, fill in the <b>Date acquired</b> column, and run it again.</p></div>`,
  };
}

// ══════════════════════════════════════════════════════════════════
//  Helpers
// ══════════════════════════════════════════════════════════════════
function kpi(label, val, sub, tint) {
  return `<div class="kpi" style="--k:${tint}"><div class="k-label">${label}</div><div class="k-val">${val}</div><div class="k-sub">${sub || ''}</div></div>`;
}
function matrix(m) {
  if (!m?.tickers?.length) return '';
  const t = m.tickers.slice(0, 14);
  let h = '<table class="matrix"><tr><th></th>' + t.map((x) => `<th>${esc(x)}</th>`).join('') + '</tr>';
  t.forEach((r, i) => {
    h += `<tr><th>${esc(r)}</th>` + t.map((_, j) => {
      const v = m.values[i][j];
      const a = Math.max(0, v);
      return `<td style="background:rgba(47,107,79,${(a * 0.8).toFixed(2)});color:${a > 0.55 ? '#fff' : C.ink}">${v.toFixed(2)}</td>`;
    }).join('') + '</tr>';
  });
  return h + '</table>';
}
function mk(key, id, cfg) {
  destroy(key);
  const el = $(id);
  if (!el) return;
  cfg.options = { responsive: true, maintainAspectRatio: false, ...(cfg.options || {}) };
  charts[key] = new Chart(el.getContext('2d'), cfg);
}
function destroy(key) { if (charts[key]) { charts[key].destroy(); delete charts[key]; } }
function area(label, data, color, fill) { return { label, data, borderColor: color, backgroundColor: fill, fill: true, tension: 0.25, pointRadius: 0, borderWidth: 2.5 }; }
function line(label, data, color, dash, stepped) { return { label, data, borderColor: color, borderDash: dash || [], fill: false, tension: stepped ? 0 : 0.25, stepped: stepped ? 'after' : false, pointRadius: 0, borderWidth: 2 }; }
function moneyOpts() {
  return { interaction: { mode: 'index', intersect: false }, plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${usd(c.raw)}` } } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { grid: { color: C.line }, ticks: { callback: (v) => usdShort(v) } } } };
}

function usd(n) { if (n == null || isNaN(n)) return '—'; return '$' + (+n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function signUsd(n) { return (n >= 0 ? '+' : '−') + usd(Math.abs(n)); }
function usdShort(v) { const a = Math.abs(v); return (v < 0 ? '-' : '') + '$' + (a >= 1e6 ? (a / 1e6).toFixed(1) + 'M' : a >= 1e3 ? (a / 1e3).toFixed(1) + 'K' : a.toFixed(0)); }
function pct(n) { if (n == null || isNaN(n)) return '—'; return (n >= 0 ? '+' : '') + (+n).toFixed(1) + '%'; }
function plainPct(n) { return n == null || isNaN(n) ? '—' : (+n).toFixed(1) + '%'; }
function lotLabel(l, all) { return all.filter((x) => x.ticker === l.ticker).length > 1 ? `${l.ticker} · ${shortDate(l.acquired)}` : l.ticker; }
function fmtNum(n) { return n == null ? '—' : (+n).toLocaleString('en-US', { maximumFractionDigits: 4 }); }
function fmtDate(s) { if (!s) return '—'; const d = new Date(s + 'T00:00:00'); return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
function shortDate(s) { const d = new Date(s + 'T00:00:00'); return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' }); }
function daysBetween(a, b) { return Math.round((new Date(b) - new Date(a)) / 86400000); }

function showView(id) {
  document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
  $(id).classList.add('active');
  if (id !== 'view-story' && $('progress')) $('progress').style.width = '0';
  window.scrollTo({ top: 0 });
}
window.showView = showView;

function reset() {
  files = []; holdings = []; manualItems = []; notes = []; candidateTickers = [];
  Object.keys(charts).forEach(destroy);
  renderFileChips();
  $('sheet-url').value = '';
  $('manual-list').innerHTML = '';
  $('btn-manual-continue').style.display = 'none';
  $('btn-reset').style.display = 'none';
  clearMsg('upload-msg');
  showView('view-upload');
}
function showMsg(id, text, type = 'error') { const el = $(id); el.textContent = text; el.className = 'msg ' + (type === 'info' ? 'info' : ''); el.style.display = 'block'; }
function clearMsg(id) { $(id).style.display = 'none'; }
