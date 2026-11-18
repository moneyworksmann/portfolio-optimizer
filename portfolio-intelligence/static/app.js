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
    saveForStress(data);
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
    chYear(d), chRisk(d), chOutcomes(d), chStress(d), chSignals(d), chSuggest(d), chTable(d),
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
function _prismMaxHtml(d) {
  const pm = d.prism_max;
  if (!pm?.available) return '';
  const pr = d.prism;
  const tone = (v) => (v >= 70 ? C.leaf : v >= 40 ? C.sun : C.clay);
  const dims = [['F', 'Diversification'], ['I', 'Independence'], ['N', 'Calm'], ['E', 'Balance']];
  const gap = pm.max_score - pr.prism_score;
  const pct = (v) => Math.min(100, Math.max(0, v));

  return `<div class="panel" style="margin-top:16px">
    <h3>Path to your best score</h3>
    <p class="hint">The highest PRISM score achievable by rebalancing your current holdings</p>
    <div class="score-path">
      <div class="score-path-row">
        <span class="score-path-label">Now</span>
        <div class="bar-track" style="position:relative;flex:1">
          <div class="bar-fill" style="width:${pct(pr.prism_score)}%;background:${tone(pr.prism_score)}"></div>
          <div class="bar-fill" style="width:${pct(pm.max_score)}%;background:${tone(pm.max_score)};opacity:0.25;position:absolute;top:0;left:0;height:100%;border-radius:6px"></div>
        </div>
        <span class="num" style="min-width:80px;text-align:right"><b>${pr.prism_score.toFixed(0)}</b> → <b style="color:${tone(pm.max_score)}">${pm.max_score.toFixed(0)}</b></span>
      </div>
    </div>
    ${gap >= 1 ? `<p style="margin:10px 0 0;font-size:.92em;color:${C.forest}"><b>+${gap.toFixed(0)} points</b> available through rebalancing alone</p>` : `<p style="margin:10px 0 0;font-size:.92em;color:${C.leaf}">Your weights are already near-optimal for these holdings.</p>`}
    ${dims.map(([k, n]) => {
      const cur = pr.sub_scores[k], best = pm.max_sub_scores[k], diff = best - cur;
      return diff >= 1 ? `<div class="bar-row" style="margin-top:6px"><span style="min-width:110px"><b>${n}</b></span><div class="bar-track"><div class="bar-fill" style="width:${pct(cur)}%;background:${tone(cur)}"></div></div><span class="num">${cur.toFixed(0)} → <b style="color:${tone(best)}">${best.toFixed(0)}</b></span></div>` : '';
    }).join('')}
    ${pm.improvements?.length ? `<div style="margin-top:14px"><b style="font-size:.93em">How to get there:</b><ul class="prism-tips">${pm.improvements.map((t) => `<li>${esc(t)}</li>`).join('')}</ul></div>` : ''}
    <p class="hint" style="margin-top:12px;font-size:.85em;border-top:1px solid ${C.line};padding-top:10px"><b>What would a perfect 100 look like?</b> ${esc(pm.perfect_score_description)}</p>
  </div>`;
}

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
      <div class="panel"><h3>Do your holdings move together?</h3><p class="hint">Correlation of daily returns, 5 years</p><div style="overflow-x:auto">${matrix(pr.correlation_matrix)}</div></div></div>
    ${_prismMaxHtml(d)}`,
  };
}

// ── Chapter: range of outcomes (Monte Carlo) ─────────────────────
function chOutcomes(d) {
  const m = d.monte_carlo;
  if (!m?.available || !m.results?.current) return null;
  const cur = m.results.current, opt = m.results.optimal;
  const p = cur.percentiles_pct;
  const months = (day) => (day === 0 ? 'Today' : `Month ${Math.round(day / 21)}`);
  const lossOdds = Math.round(cur.prob_loss * 100);
  const oneIn = cur.prob_loss > 0 ? Math.max(1, Math.round(1 / cur.prob_loss)) : null;
  const usd0 = (n) => '$' + Math.round(n).toLocaleString('en-US');
  const loss = (r) => (r.var_95_dollars != null ? usd0(r.var_95_dollars) : plainPct(r.var_95_pct));
  const years = Math.max(1, Math.round(m.lookback_days / 252));
  return {
    id: 'outcomes', rail: 'Range of outcomes', title: 'What the next year could look like',
    what: `Instead of one forecast, we replayed the next year ${m.paths.toLocaleString()} times using how your holdings have moved, alone and together, over the past ${years} year${years === 1 ? '' : 's'}. This shows how often each outcome came up.`,
    how: [
      'The fan shows the middle path (dark line), the middle half of outcomes (inner band) and 9 in 10 outcomes (outer band), starting from $1.',
      'The bars show how often each 12-month return came up across all the replays.',
      '<b>Bad-year loss</b> is the loss only 1 replay in 20 did worse than (95% VaR). <b>Average in those years</b> is what those worst replays lost on average (CVaR).',
    ],
    takeaway: [
      `In the middle case your portfolio is <b>${pct(cur.median_return_pct)}</b> after a year, and 9 in 10 replays land between <b>${pct(p.p5)}</b> and <b>${pct(p.p95)}</b>.`,
      `<b>${lossOdds}%</b> of replays ended the year down${oneIn ? `, roughly 1 year in ${oneIn}` : ''}. In a 1-in-20 bad year you’d lose about <b class="down">${loss(cur)}</b>.`,
      ...(opt ? [`With the suggested mix: middle case <b>${pct(opt.median_return_pct)}</b>, ${Math.round(opt.prob_loss * 100)}% chance of a down year, 1-in-20 loss ${loss(opt)}.`] : []),
    ],
    caveat: `${m.unsimulated_weight_pct > 0 ? `${plainPct(m.unsimulated_weight_pct)} of your portfolio had no price history and is left out. ` : ''}These are odds built from past prices, not a prediction. Not financial advice.`,
    visual: `
      <div class="grid g4">
        ${kpi('Middle case', pct(cur.median_return_pct), cur.value_percentiles ? `${usd0(cur.value_percentiles.p50)} in a year` : 'after 12 months', C.mint)}
        ${kpi('Chance of a down year', `${lossOdds}%`, `${Math.round((cur.prob_below['-10'] ?? 0) * 100)}% chance of −10% or worse`, '#f7efd9')}
        ${kpi('Bad-year loss (1 in 20)', loss(cur), `${plainPct(cur.var_95_pct)} of value`, '#f3e0d6')}
        ${kpi('Average in those years', cur.cvar_95_dollars != null ? usd0(cur.cvar_95_dollars) : plainPct(cur.cvar_95_pct), `deepest dip ${plainPct(cur.max_drawdown_p95_pct)}`, '#ece6f6')}
      </div>
      <div class="grid g2" style="margin-top:16px">
        <div class="panel"><h3>Growth of $1, next 12 months</h3><p class="hint">Middle path with 50% and 90% ranges</p><div class="chart-box"><canvas id="c-fan"></canvas></div></div>
        <div class="panel"><h3>How often each return came up</h3><p class="hint">% of replays by 12-month return</p><div class="chart-box"><canvas id="c-hist"></canvas></div></div>
      </div>
      ${opt ? `<div class="panel" style="margin-top:16px"><h3>Your mix vs the suggested mix</h3><p class="hint">Same replays, same history</p>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th class="num">Bad case (5%)</th><th class="num">Middle</th><th class="num">Good case (95%)</th><th class="num">Chance of loss</th><th class="num">1-in-20 loss</th><th class="num">Deepest dip (1 in 20)</th></tr></thead><tbody>
        ${[['Your mix', cur], ['Suggested mix', opt]].map(([n, r]) => `<tr><td><b>${n}</b></td><td class="num">${pct(r.percentiles_pct.p5)}</td><td class="num">${pct(r.median_return_pct)}</td><td class="num">${pct(r.percentiles_pct.p95)}</td><td class="num">${Math.round(r.prob_loss * 100)}%</td><td class="num">${loss(r)}</td><td class="num">${plainPct(r.max_drawdown_p95_pct)}</td></tr>`).join('')}
        </tbody></table></div></div>` : ''}`,
    draw: () => {
      const f = cur.fan;
      const band = (label, key, fill, bg) => ({ label, data: f.map((x) => x[key]), borderColor: 'transparent', backgroundColor: bg || 'transparent', fill, pointRadius: 0, tension: 0.3 });
      mk('fan', 'c-fan', {
        type: 'line',
        data: {
          labels: f.map((x) => months(x.day)),
          datasets: [
            band('95th', 'p95', '+4', 'rgba(156,197,161,.25)'),
            band('75th', 'p75', '+2', 'rgba(95,163,106,.30)'),
            line('Middle', f.map((x) => x.p50), C.forest),
            band('25th', 'p25', false),
            band('5th', 'p5', false),
          ],
        },
        options: { interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: $${c.raw.toFixed(3)}` } } }, scales: { x: { grid: { display: false } }, y: { grid: { color: C.line }, ticks: { callback: (v) => '$' + v.toFixed(2) } } } },
      });
      const h = cur.histogram;
      const mid = (b) => (b.from_pct + b.to_pct) / 2;
      mk('hist', 'c-hist', {
        type: 'bar',
        data: { labels: h.map((b) => `${mid(b).toFixed(0)}%`), datasets: [{ label: 'Replays', data: h.map((b) => b.probability * 100), backgroundColor: h.map((b) => (mid(b) < 0 ? C.clay : C.leaf)), borderRadius: 3, categoryPercentage: 1, barPercentage: 0.95 }] },
        options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: (c) => `${h[c[0].dataIndex].from_pct.toFixed(1)}% to ${h[c[0].dataIndex].to_pct.toFixed(1)}%`, label: (c) => ` ${c.raw.toFixed(1)}% of replays` } } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { grid: { color: C.line }, ticks: { callback: (v) => v + '%' } } } },
      });
    },
  };
}

// ── Chapter: stress test (opens its own page) ──────────────────
function chStress(d) {
  if (!d.holdings?.length) return null;
  return {
    id: 'stress', rail: 'Stress test', title: 'What if the world moves?',
    what: 'The stress test has its own page. Move sliders for the stock market, interest rates, oil, the dollar, market fear and each sector, and watch your portfolio’s value and its range of future outcomes update as you go.',
    how: ['Your holdings are carried over automatically.', 'Start with a ready-made scenario such as “Recession”, then adjust the sliders.'],
    takeaway: [],
    visual: `<div class="panel st-cta"><div class="st-cta-icon">🎛️</div><div><h3>Open the stress test</h3><p class="hint">Uses the ${d.holdings.length} holdings you just analysed. Opens in a new tab so this story stays here.</p></div><a class="btn btn-primary" href="/stress" target="_blank" rel="noopener">Open the stress test →</a></div>`,
  };
}

function saveForStress(d) {
  try {
    const dropped = d.meta?.dropped_tickers || [];
    const rows = d.holdings.filter((h) => !dropped.includes(h.ticker)).map((h) => ({ ticker: h.ticker, shares: h.shares, sector: h.sector, price: h.current_price }));
    localStorage.setItem('pi_portfolio', JSON.stringify({ saved: new Date().toISOString(), holdings: rows }));
  } catch (e) { /* storage blocked: the stress page lets you type holdings instead */ }
}

// ── News signals: the always-on loop on your saved portfolio ─────
// The owner key is the server's INTEL_TOKEN; it stays in this browser only.
function ownerKey() { try { return localStorage.getItem('pi_owner_key') || ''; } catch (e) { return ''; } }
function setOwnerKey(k) { try { k ? localStorage.setItem('pi_owner_key', k) : localStorage.removeItem('pi_owner_key'); } catch (e) { /* storage blocked */ } }

async function intelFetch(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const key = ownerKey();
  if (key) headers.Authorization = 'Bearer ' + key;
  if (opts.body) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { ...opts, headers });
  let data = {};
  try { data = await res.json(); } catch (e) { data = { error: `Server answered ${res.status}` }; }
  return { status: res.status, data };
}

function chSignals(d) {
  if (!d.holdings?.length) return null;
  return {
    id: 'signals', rail: 'News signals', title: 'What the news is saying',
    what: 'Save this portfolio and Portfolio Intelligence keeps reading the news and SEC filings for these stocks, every 30 minutes while the market is open. Claude scores each new story, scores fade over a few days, and only a strong, lasting signal can turn into a suggested trade.',
    how: [
      'Each stock gets a score: below zero is bad news, above zero good news. Under ±2 is noise, ±2 to ±4 is worth watching, ±4 or more can trigger a suggestion.',
      'A suggestion moves a stock by at most 5 points of your portfolio, and the rest are scaled to make room.',
      'It only looks at the stocks you save here, plus the watchlist below.',
    ],
    takeaway: ['For the first two weeks it runs in <b>shadow mode</b>: it shows what it <i>would</i> suggest, so you can judge it before trusting it. It never places trades.'],
    caveat: 'Scores come from headlines and summaries, not full articles. Not financial advice.',
    visual: `<div class="panel" id="intel-panel">
        <div class="intel-head">
          <div><h3>Watch this portfolio</h3><p class="hint" id="intel-saved">Not saved yet.</p></div>
          <div class="intel-actions">
            <button class="btn btn-primary" id="btn-watch">Watch this portfolio</button>
            <button class="btn" id="btn-intel-run" title="Run the news check now instead of waiting for the schedule">Check the news now</button>
          </div>
        </div>
        <div id="intel-key" class="intel-key" style="display:none">
          <p class="hint">This server needs your owner key (the <code>INTEL_TOKEN</code> you set in Vercel). It is kept in this browser only.</p>
          <div class="candidate-row"><input type="password" id="intel-key-input" placeholder="Owner key" autocomplete="off" /><button class="btn btn-primary" id="btn-intel-key">Save key</button></div>
        </div>
        <div id="intel-msg" class="msg" style="display:none"></div>
        <div id="intel-body"><p class="sub">Loading signals…</p></div>
      </div>`,
    draw: () => {
      $('btn-watch').onclick = watchPortfolio;
      $('btn-intel-run').onclick = runIntelNow;
      $('btn-intel-key').onclick = () => { setOwnerKey($('intel-key-input').value.trim()); $('intel-key').style.display = 'none'; loadIntel(); };
      loadIntel();
    },
  };
}

function intelError(status, data) {
  if (status === 401 && data.needs_key) { $('intel-key').style.display = 'block'; }
  showMsg('intel-msg', data.error || `Something went wrong (${status}).`);
}

async function watchPortfolio() {
  clearMsg('intel-msg');
  const valid = holdings.filter((h) => h.ticker && +h.shares > 0);
  $('btn-watch').disabled = true;
  try {
    const { status, data } = await intelFetch('/api/portfolio', { method: 'POST', body: JSON.stringify({ holdings: valid, candidates: candidateTickers }) });
    if (status !== 200) return intelError(status, data);
    showMsg('intel-msg', `Saved ${data.tickers} stocks${data.candidates.length ? ` and ${data.candidates.length} on the watchlist` : ''}. The news check will use exactly these.`, 'info');
    loadIntel();
  } finally { $('btn-watch').disabled = false; }
}

async function runIntelNow() {
  clearMsg('intel-msg');
  const btn = $('btn-intel-run');
  btn.disabled = true; btn.textContent = 'Checking…';
  try {
    const { status, data } = await intelFetch('/api/intel/run', { method: 'POST' });
    if (status !== 200) return intelError(status, data);
    const bits = [`${data.new_items} new stories, ${data.scored} scored`];
    if (data.deferred) bits.push(`${data.deferred} left for the next run`);
    if (data.errors?.length) bits.push(data.errors.join(' · '));
    showMsg('intel-msg', bits.join('. ') + '.', data.errors?.length ? 'error' : 'info');
    loadIntel();
  } finally { btn.disabled = false; btn.textContent = 'Check the news now'; }
}

const LEVEL = {
  candidate: ['pill-exit', 'Could act'], disagree: ['pill-trim', 'News vs price'],
  watch: ['pill-trim', 'Watch'], none: ['pill-keep', 'Quiet'],
};

async function loadIntel() {
  const { status, data } = await intelFetch('/api/intel');
  if (status !== 200) { $('intel-body').innerHTML = ''; return intelError(status, data); }
  const cfg = data.config;
  $('intel-saved').innerHTML = data.portfolio
    ? `Watching ${data.portfolio.tickers.length} stocks, saved ${fmtWhen(data.portfolio.saved_at)}. Last news check: ${data.last_run ? fmtWhen(data.last_run) : 'not yet'}. Mode: <b>${cfg.mode === 'live' ? 'live' : 'shadow'}</b>.`
    : 'Not saved yet. Save it to start the news checks on these stocks.';
  const missing = [];
  if (!cfg.claude) missing.push('ANTHROPIC_API_KEY (scoring)');
  if (!cfg.finnhub) missing.push('FINNHUB_API_KEY (news; Google News is used meanwhile)');
  if (!cfg.sec_user_agent) missing.push('SEC_USER_AGENT (filings)');
  if (cfg.store === 'none') missing.push('a Postgres database (saving)');

  const sig = Object.entries(data.signals || {}).sort((a, b) => Math.abs(b[1].score) - Math.abs(a[1].score));
  const sug = (data.suggestions || [])[0];
  $('intel-body').innerHTML = `
    ${missing.length ? `<p class="hint">Not set up on the server yet: ${missing.map(esc).join(', ')}.</p>` : ''}
    ${sug ? suggestionHtml(sug) : ''}
    ${sig.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Stock</th><th class="num">Score</th><th>Signal</th><th class="num">Stories</th><th class="num">Today</th><th>Biggest story</th></tr></thead><tbody>
      ${sig.map(([t, s]) => { const [cls, label] = LEVEL[s.level] || LEVEL.none; const top = s.top?.[0];
        return `<tr><td><b>${esc(t)}</b>${s.watchlist ? ' <span class="sub">watchlist</span>' : ''}</td><td class="num ${s.score > 0 ? 'up' : s.score < 0 ? 'down' : ''}">${s.score > 0 ? '+' : ''}${s.score.toFixed(1)}</td><td><span class="pill ${cls}">${label}</span></td><td class="num">${s.items}</td><td class="num">${s.day_move_pct == null ? '—' : pct(s.day_move_pct)}</td><td class="why">${top ? `${esc(top.reason)} <a href="${esc(top.url)}" target="_blank" rel="noopener">${esc(top.source || 'source')}</a>` : '<span class="sub">No scored stories</span>'}</td></tr>`; }).join('')}
      </tbody></table></div>` : (data.portfolio ? '<p class="sub">No signals yet. They appear after the first news check.</p>' : '')}`;
}

function suggestionHtml(s) {
  const shadow = s.mode !== 'live';
  const o = s.outcomes_1y_pct;
  return `<div class="intel-sug${shadow ? ' shadow' : ''}">
    <h3>${shadow ? 'Shadow suggestion (not acted on)' : 'News-driven suggestion'} · ${fmtWhen(s.created)}</h3>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Stock</th><th>Action</th><th class="num">Now</th><th class="num">Suggested</th><th class="num">$ amount</th><th class="num">Shares</th><th>Why</th></tr></thead><tbody>
    ${s.trades.map((t) => `<tr><td><b>${esc(t.ticker)}</b></td><td><span class="pill pill-${t.action === 'Add' ? 'add' : t.action === 'Trim' ? 'trim' : 'keep'}">${t.action}</span></td><td class="num">${t.current_pct.toFixed(1)}%</td><td class="num">${t.target_pct.toFixed(1)}%</td><td class="num">${signUsd(t.dollars)}</td><td class="num">${t.shares == null ? '—' : (t.shares >= 0 ? '+' : '') + t.shares.toFixed(2)}</td><td class="why">${esc(t.reason || '')}${t.source?.url ? ` <a href="${esc(t.source.url)}" target="_blank" rel="noopener">${esc(t.source.source || 'source')}</a>` : ''}</td></tr>`).join('')}
    </tbody></table></div>
    <p class="hint">Sharpe ${s.sharpe_before.toFixed(2)} → ${s.sharpe_after.toFixed(2)}${s.prism_before != null ? ` · PRISM ${s.prism_before} → ${s.prism_after}` : ''}${o ? ` · 1-year range (5th / median / 95th): ${pct(o.current.p5)} / ${pct(o.current.p50)} / ${pct(o.current.p95)} now, ${pct(o.suggested.p5)} / ${pct(o.suggested.p50)} / ${pct(o.suggested.p95)} after` : ''}. ${esc(s.note || '')}</p>
  </div>`;
}

function fmtWhen(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
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
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Ticker</th><th>Action</th><th class="num">Now</th><th class="num">Suggested</th><th class="num">Change</th><th class="num">$ amount</th><th class="num">Shares</th><th class="num">Exp. return</th><th>Reason</th></tr></thead><tbody>
        ${o.trades.map((t) => `<tr><td><b>${esc(t.ticker)}</b></td><td><span class="pill pill-${t.action.toLowerCase()}">${t.action}</span></td><td class="num">${t.current_pct.toFixed(1)}%</td><td class="num">${t.target_pct.toFixed(1)}%</td><td class="num ${t.change_pct >= 0 ? 'up' : 'down'}">${t.change_pct >= 0 ? '+' : ''}${t.change_pct.toFixed(1)} pts</td><td class="num">${t.dollars != null ? signUsd(t.dollars) : '—'}</td><td class="num">${t.shares != null ? (t.shares >= 0 ? '+' : '') + t.shares.toFixed(3) : '—'}</td><td class="num">${pct(t.exp_return_pct)}</td><td style="font-size:.85em;max-width:260px">${esc(t.reason || '')}</td></tr>`).join('')}
        </tbody></table></div></div>

      <div style="margin-top:16px;text-align:right">
        <button class="btn btn-primary" onclick="downloadReport()">&#8681; Download report</button>
      </div>

      <div class="panel candidate-panel" style="margin-top:24px">
        <h3>Considering new stocks?</h3>
        <p class="hint">Add tickers you are thinking about buying — type them in or upload a file (CSV, Excel, PDF, screenshot, etc). We will re-run the optimizer with them in the mix and show how they would change your allocation and PRISM score.</p>
        <div class="candidate-row">
          <input type="text" id="candidate-input" placeholder="e.g. TSLA" maxlength="8" />
          <button id="btn-add-candidate" class="btn">+ Add</button>
          <label for="candidate-file" class="btn" title="Upload a file with tickers">&#128206; Upload watchlist</label>
          <input type="file" id="candidate-file" multiple hidden
                 accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.ods,.json,.pdf,.docx,.png,.jpg,.jpeg,.webp,.heic,.gif,.bmp,.tif,.tiff" />
          <button id="btn-reoptimize" class="btn btn-primary" style="display:none">Re-optimize with these &#8594;</button>
        </div>
        <div id="candidate-file-status" class="sub" style="display:none"></div>
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
  var fileInput = $('candidate-file');
  if (fileInput) fileInput.addEventListener('change', function() { parseCandidateFiles(this.files); this.value = ''; });
  renderCandidateChips();
}

async function parseCandidateFiles(fileList) {
  if (!fileList || !fileList.length) return;
  var status = $('candidate-file-status');
  status.textContent = 'Reading ' + fileList.length + ' file' + (fileList.length > 1 ? 's' : '') + '...';
  status.style.display = 'block';
  clearMsg('reopt-msg');
  var fd = new FormData();
  for (var i = 0; i < fileList.length; i++) fd.append('files', fileList[i]);
  try {
    var res = await fetch('/api/parse', { method: 'POST', body: fd });
    var data = await res.json();
    if (data.error) throw new Error(data.error);
    var existing = new Set(holdings.map(function(h) { return h.ticker; }));
    var added = 0, skipped = 0;
    (data.holdings || []).forEach(function(h) {
      var t = (h.ticker || '').toUpperCase().trim();
      if (!t) return;
      if (existing.has(t)) { skipped++; return; }
      if (candidateTickers.includes(t)) { skipped++; return; }
      candidateTickers.push(t);
      added++;
    });
    var parts = [];
    if (added) parts.push('Added ' + added + ' ticker' + (added > 1 ? 's' : ''));
    if (skipped) parts.push(skipped + ' already in portfolio or list');
    if (data.notes && data.notes.length) parts.push(data.notes.join('; '));
    status.textContent = parts.join('. ') || 'No tickers found in file.';
    if (!added && !skipped) showMsg('reopt-msg', 'No tickers found in the uploaded file.', 'info');
    renderCandidateChips();
  } catch (e) {
    status.style.display = 'none';
    showMsg('reopt-msg', 'File error: ' + e.message);
  }
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
  window._reopt = data;
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
  var ps = d.prism_suggested;
  var o = d.optimization;
  if (!o || !o.available) return;
  var im = o.impact;
  var today = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  var up = s.total_gain >= 0;
  var dims = [['F', 'Diversification'], ['I', 'Independence'], ['N', 'Calm'], ['E', 'Balance']];
  var tone = function(v) { return v >= 70 ? '#5fa36a' : v >= 40 ? '#e9b949' : '#c97b5a'; };
  var band = function(v) { return v >= 70 ? 'Healthy' : v >= 40 ? 'Growing' : 'Fragile'; };

  var rptCss = '*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }' +
    'body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: #1f3a2e; background: #fff; padding: 40px; max-width: 960px; margin: 0 auto; font-size: 14px; line-height: 1.5; }' +
    '.header { text-align: center; margin-bottom: 36px; padding-bottom: 24px; border-bottom: 2px solid #dfe7d6; }' +
    '.header h1 { font-size: 26px; color: #2f6b4f; margin-bottom: 4px; }' +
    '.header .date { color: #7d9087; font-size: 13px; }' +
    '.part { margin-bottom: 40px; }' +
    '.part-title { font-size: 20px; font-weight: 800; color: #fff; background: #2f6b4f; padding: 10px 18px; border-radius: 10px; margin-bottom: 20px; }' +
    '.part-title.after { background: #6aa6c8; }' +
    '.section { margin-bottom: 28px; }' +
    '.section h3 { font-size: 16px; color: #2f6b4f; border-bottom: 1px solid #dfe7d6; padding-bottom: 6px; margin-bottom: 12px; }' +
    '.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px; }' +
    '.kpi-box { background: #f5f7ef; border: 1px solid #dfe7d6; border-radius: 10px; padding: 14px 16px; }' +
    '.kpi-box .label { font-size: 11px; font-weight: 700; color: #7d9087; text-transform: uppercase; letter-spacing: .04em; }' +
    '.kpi-box .val { font-size: 22px; font-weight: 800; margin-top: 2px; }' +
    '.kpi-box .sub { font-size: 12px; color: #4d6558; }' +
    'table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 8px; }' +
    'th { text-align: left; font-size: 11px; font-weight: 700; color: #7d9087; text-transform: uppercase; letter-spacing: .04em; padding: 8px 10px; border-bottom: 2px solid #dfe7d6; }' +
    'td { padding: 6px 10px; border-bottom: 1px solid #eef3e6; }' +
    '.num { text-align: right; font-variant-numeric: tabular-nums; }' +
    '.up { color: #2f6b4f; } .dn { color: #c97b5a; }' +
    '.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }' +
    '.pill-add { background: #d6ecd9; color: #2f6b4f; } .pill-trim { background: #efe4cc; color: #8a6a1f; } .pill-exit { background: #f6e3da; color: #c97b5a; } .pill-keep { background: #eef3e6; color: #4d6558; }' +
    '.score-row { display: flex; align-items: center; gap: 14px; margin: 10px 0 16px; }' +
    '.score-num { font-size: 44px; font-weight: 800; line-height: 1; }' +
    '.score-out { font-size: 16px; color: #7d9087; }' +
    '.bar-bg { height: 8px; background: #eef3e6; border-radius: 99px; overflow: hidden; }' +
    '.bar-fg { height: 100%; border-radius: 99px; }' +
    '.hint { color: #7d9087; font-size: 12px; margin-bottom: 10px; }' +
    '.divider { border: none; border-top: 3px solid #dfe7d6; margin: 36px 0; }' +
    '.compare { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }' +
    '.compare > div { padding: 16px; border-radius: 10px; }' +
    '.compare .now { background: #f5f7ef; border: 1px solid #dfe7d6; }' +
    '.compare .after { background: #e8f4f8; border: 1px solid #c3dfe9; }' +
    '.compare h4 { font-size: 13px; font-weight: 800; color: #7d9087; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 8px; }' +
    '.footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #dfe7d6; text-align: center; font-size: 11px; color: #7d9087; }' +
    '@media print { body { padding: 20px; } .part, .section { break-inside: avoid; } .compare { grid-template-columns: 1fr 1fr; } }' +
    '@media (max-width: 600px) { .compare { grid-template-columns: 1fr; } }';

  // ── PART 1: YOUR PORTFOLIO NOW ──
  var part1 = '<div class="part">' +
    '<div class="part-title">Part 1: Your Portfolio Now</div>' +

    '<div class="section"><h3>Portfolio Snapshot</h3><div class="kpis">' +
      '<div class="kpi-box"><div class="label">Total Value</div><div class="val">' + usd(s.total_value) + '</div><div class="sub">' + s.positions + ' holdings</div></div>' +
      '<div class="kpi-box"><div class="label">Total Invested</div><div class="val">' + usd(s.total_cost) + '</div></div>' +
      '<div class="kpi-box"><div class="label">Total Gain</div><div class="val ' + (up ? 'up' : 'dn') + '">' + signUsd(s.total_gain) + '</div><div class="sub">' + pct(s.total_gain_pct) + '</div></div>' +
      '<div class="kpi-box"><div class="label">Expected Return</div><div class="val">' + pct(im.return_now_pct) + '</div></div>' +
      '<div class="kpi-box"><div class="label">Risk (Swing)</div><div class="val">' + plainPct(im.risk_now_pct) + '</div></div>' +
      '<div class="kpi-box"><div class="label">Sharpe Ratio</div><div class="val">' + im.sharpe_now.toFixed(2) + '</div></div>' +
    '</div></div>' +

    '<div class="section"><h3>Current Holdings</h3>' +
    '<table><thead><tr><th>Ticker</th><th>Sector</th><th class="num">Value</th><th class="num">Weight</th><th class="num">Gain</th></tr></thead><tbody>' +
    d.holdings.map(function(h) {
      return '<tr><td><b>' + esc(h.ticker) + '</b></td><td>' + esc(h.sector || '') + '</td>' +
        '<td class="num">' + usd(h.value) + '</td><td class="num">' + h.weight.toFixed(1) + '%</td>' +
        '<td class="num ' + (h.gain >= 0 ? 'up' : 'dn') + '">' + pct(h.gain_pct) + '</td></tr>';
    }).join('') +
    '</tbody></table></div>';

  if (pr && pr.available) {
    part1 += '<div class="section"><h3>Current PRISM Score</h3>' +
      '<div class="score-row"><div class="score-num" style="color:' + tone(pr.prism_score) + '">' + pr.prism_score.toFixed(0) + '</div><div><b>PRISM</b> <span class="score-out">/ 100</span><br><span class="hint">' + band(pr.prism_score) + '</span></div></div>' +
      '<table><thead><tr><th>Dimension</th><th class="num">Score</th><th style="width:50%">Bar</th></tr></thead><tbody>' +
      dims.map(function(dd) {
        var v = pr.sub_scores[dd[0]];
        return '<tr><td>' + dd[1] + '</td><td class="num">' + v.toFixed(0) + '</td>' +
          '<td><div class="bar-bg"><div class="bar-fg" style="width:' + v + '%;background:' + tone(v) + '"></div></div></td></tr>';
      }).join('') +
      '</tbody></table></div>';
  }
  part1 += '</div>';

  // ── PART 2: AFTER SUGGESTED CHANGES ──
  var part2 = '<div class="part">' +
    '<div class="part-title after">Part 2: After Suggested Changes</div>';

  // Suggested KPIs
  part2 += '<div class="section"><h3>Projected Performance</h3><div class="kpis">' +
    '<div class="kpi-box"><div class="label">Expected Return</div><div class="val up">' + pct(im.return_after_pct) + '</div><div class="sub">from ' + pct(im.return_now_pct) + '</div></div>' +
    '<div class="kpi-box"><div class="label">Risk (Swing)</div><div class="val">' + plainPct(im.risk_after_pct) + '</div><div class="sub">from ' + plainPct(im.risk_now_pct) + '</div></div>' +
    '<div class="kpi-box"><div class="label">Sharpe Ratio</div><div class="val up">' + im.sharpe_after.toFixed(2) + '</div><div class="sub">from ' + im.sharpe_now.toFixed(2) + '</div></div>';
  if (im.dollars_per_year_after != null) {
    part2 += '<div class="kpi-box"><div class="label">Est. Annual $</div><div class="val">' + usd(im.dollars_per_year_after) + '</div><div class="sub">from ' + usd(im.dollars_per_year_now) + '</div></div>';
  }
  part2 += '</div></div>';

  // Suggested PRISM
  if (ps && ps.available && pr && pr.available) {
    var delta = ps.prism_score - pr.prism_score;
    var deltaUp = delta >= 0;
    part2 += '<div class="section"><h3>Projected PRISM Score</h3>' +
      '<div class="compare"><div class="now"><h4>Current</h4><div class="score-num" style="color:' + tone(pr.prism_score) + '">' + pr.prism_score.toFixed(0) + '</div></div>' +
      '<div class="after"><h4>After Changes</h4><div class="score-num" style="color:' + tone(ps.prism_score) + '">' + ps.prism_score.toFixed(0) + '</div>' +
      '<div class="hint ' + (deltaUp ? 'up' : 'dn') + '" style="font-weight:700;margin-top:4px">' + (deltaUp ? '+' : '') + delta.toFixed(1) + ' points</div></div></div>' +
      '<table><thead><tr><th>Dimension</th><th class="num">Current</th><th class="num">After</th><th class="num">Change</th></tr></thead><tbody>' +
      dims.map(function(dd) {
        var before = pr.sub_scores[dd[0]], after = ps.sub_scores[dd[0]], ch = after - before;
        return '<tr><td>' + dd[1] + '</td><td class="num">' + before.toFixed(0) + '</td><td class="num">' + after.toFixed(0) + '</td>' +
          '<td class="num ' + (ch >= 0 ? 'up' : 'dn') + '">' + (ch >= 0 ? '+' : '') + ch.toFixed(1) + '</td></tr>';
      }).join('') +
      '</tbody></table></div>';
  }

  // Suggested allocation
  part2 += '<div class="section"><h3>Suggested Holdings &amp; Weights</h3>' +
    '<p class="hint">How each position changes — sorted by suggested weight</p>' +
    '<table><thead><tr><th>Ticker</th><th>Sector</th><th class="num">Current</th><th class="num">Suggested</th><th class="num">Change</th><th>Action</th></tr></thead><tbody>' +
    o.trades.slice().sort(function(a, b) { return b.target_pct - a.target_pct; }).map(function(t) {
      var sector = '';
      var match = d.holdings.filter(function(h) { return h.ticker === t.ticker; });
      if (match.length) sector = match[0].sector || '';
      return '<tr><td><b>' + esc(t.ticker) + '</b></td><td>' + esc(sector) + '</td>' +
        '<td class="num">' + t.current_pct.toFixed(1) + '%</td>' +
        '<td class="num">' + t.target_pct.toFixed(1) + '%</td>' +
        '<td class="num ' + (t.change_pct >= 0 ? 'up' : 'dn') + '">' + (t.change_pct >= 0 ? '+' : '') + t.change_pct.toFixed(1) + ' pts</td>' +
        '<td><span class="pill pill-' + t.action.toLowerCase() + '">' + t.action + '</span></td></tr>';
    }).join('') +
    '</tbody></table></div>';

  // Trades to execute
  part2 += '<div class="section"><h3>Trades to Execute</h3>' +
    '<p class="hint">Turnover: ' + im.turnover_pct.toFixed(0) + '% of portfolio. Dollar and share amounts use today&#39;s prices.</p>' +
    '<table><thead><tr><th>Ticker</th><th>Action</th><th class="num">Now</th><th class="num">Target</th><th class="num">$ Amount</th><th class="num">Shares</th><th class="num">Exp. Return</th></tr></thead><tbody>' +
    o.trades.filter(function(t) { return t.action !== 'Keep'; }).map(function(t) {
      return '<tr><td><b>' + esc(t.ticker) + '</b></td>' +
        '<td><span class="pill pill-' + t.action.toLowerCase() + '">' + t.action + '</span></td>' +
        '<td class="num">' + t.current_pct.toFixed(1) + '%</td>' +
        '<td class="num">' + t.target_pct.toFixed(1) + '%</td>' +
        '<td class="num">' + (t.dollars != null ? signUsd(t.dollars) : '') + '</td>' +
        '<td class="num">' + (t.shares != null ? (t.shares >= 0 ? '+' : '') + t.shares.toFixed(3) : '') + '</td>' +
        '<td class="num">' + pct(t.exp_return_pct) + '</td></tr>';
    }).join('') +
    '</tbody></table></div>';

  part2 += '</div>';

  // ── PART 3: WITH WATCHLIST STOCKS ──
  var part3 = '';
  var rd = window._reopt;
  if (rd && rd.optimization && rd.optimization.available) {
    var ro = rd.optimization;
    var rim = ro.impact;
    var rpc = rd.prism_current;
    var rps = rd.prism_suggested;
    var rMoves = ro.trades.filter(function(t) { return t.action !== 'Keep' || t.current_pct > 0; });
    var rNew = ro.trades.filter(function(t) { return t.current_pct === 0 && t.target_pct > 0.5; });
    var rNotUsed = (rd.candidates || []).filter(function(c) { return !rNew.some(function(t) { return t.ticker === c; }); });

    part3 = '<hr class="divider"><div class="part">' +
      '<div class="part-title" style="background:#8b5cf6">Part 3: With Watchlist Stocks</div>';

    // Which candidates made the cut
    if (rd.candidates && rd.candidates.length) {
      part3 += '<div class="section"><h3>Candidates Evaluated</h3>' +
        '<p class="hint">Stocks from your watchlist tested against your current holdings</p>';
      if (rNew.length) {
        part3 += '<p style="margin-bottom:8px">' + rNew.map(function(t) {
          return '<span class="pill pill-add" style="margin-right:6px"><b>' + esc(t.ticker) + '</b> — ' + t.target_pct.toFixed(1) + '% suggested</span>';
        }).join(' ') + '</p>';
      }
      if (rNotUsed.length) {
        part3 += '<p class="hint">Not included by optimizer: ' + rNotUsed.map(esc).join(', ') + ' — risk/return profile did not improve the mix.</p>';
      }
      part3 += '</div>';
    }

    // Performance KPIs
    part3 += '<div class="section"><h3>Projected Performance (with watchlist)</h3><div class="kpis">' +
      '<div class="kpi-box"><div class="label">Expected Return</div><div class="val up">' + pct(rim.return_after_pct) + '</div><div class="sub">from ' + pct(rim.return_now_pct) + '</div></div>' +
      '<div class="kpi-box"><div class="label">Risk (Swing)</div><div class="val">' + plainPct(rim.risk_after_pct) + '</div><div class="sub">from ' + plainPct(rim.risk_now_pct) + '</div></div>' +
      '<div class="kpi-box"><div class="label">Sharpe Ratio</div><div class="val up">' + rim.sharpe_after.toFixed(2) + '</div><div class="sub">from ' + rim.sharpe_now.toFixed(2) + '</div></div>';
    if (rim.dollars_per_year_after != null) {
      part3 += '<div class="kpi-box"><div class="label">Est. Annual $</div><div class="val">' + usd(rim.dollars_per_year_after) + '</div><div class="sub">from ' + usd(rim.dollars_per_year_now) + '</div></div>';
    }
    part3 += '</div></div>';

    // PRISM comparison
    if (rpc && rpc.available && rps && rps.available) {
      var rDelta = rps.prism_score - rpc.prism_score;
      var rDeltaUp = rDelta >= 0;
      part3 += '<div class="section"><h3>PRISM Score (with watchlist)</h3>' +
        '<div class="compare"><div class="now"><h4>Current</h4><div class="score-num" style="color:' + tone(rpc.prism_score) + '">' + rpc.prism_score.toFixed(0) + '</div></div>' +
        '<div class="after" style="background:#f3eef8;border-color:#c4b5d9"><h4>With Watchlist</h4><div class="score-num" style="color:' + tone(rps.prism_score) + '">' + rps.prism_score.toFixed(0) + '</div>' +
        '<div class="hint ' + (rDeltaUp ? 'up' : 'dn') + '" style="font-weight:700;margin-top:4px">' + (rDeltaUp ? '+' : '') + rDelta.toFixed(1) + ' points</div></div></div>' +
        '<table><thead><tr><th>Dimension</th><th class="num">Current</th><th class="num">With Watchlist</th><th class="num">Change</th></tr></thead><tbody>' +
        dims.map(function(dd) {
          var before = rpc.sub_scores[dd[0]], after = rps.sub_scores[dd[0]], ch = after - before;
          return '<tr><td>' + dd[1] + '</td><td class="num">' + before.toFixed(0) + '</td><td class="num">' + after.toFixed(0) + '</td>' +
            '<td class="num ' + (ch >= 0 ? 'up' : 'dn') + '">' + (ch >= 0 ? '+' : '') + ch.toFixed(1) + '</td></tr>';
        }).join('') +
        '</tbody></table></div>';
    }

    // Full suggested portfolio table
    part3 += '<div class="section"><h3>Suggested Portfolio (with watchlist)</h3>' +
      '<p class="hint">Complete allocation including watchlist stocks — sorted by suggested weight</p>' +
      '<table><thead><tr><th>Ticker</th><th>Sector</th><th class="num">Current</th><th class="num">Suggested</th><th class="num">Change</th><th>Action</th></tr></thead><tbody>' +
      ro.trades.slice().sort(function(a, b) { return b.target_pct - a.target_pct; }).map(function(t) {
        var sector = '';
        var match = d.holdings.filter(function(h) { return h.ticker === t.ticker; });
        if (match.length) sector = match[0].sector || '';
        var isNew = t.current_pct === 0 && t.target_pct > 0;
        return '<tr' + (isNew ? ' style="background:#f3eef8"' : '') + '>' +
          '<td><b>' + esc(t.ticker) + '</b>' + (isNew ? ' <span class="pill" style="background:#ede5f5;color:#7c3aed;font-size:10px">NEW</span>' : '') + '</td>' +
          '<td>' + esc(sector) + '</td>' +
          '<td class="num">' + t.current_pct.toFixed(1) + '%</td>' +
          '<td class="num">' + t.target_pct.toFixed(1) + '%</td>' +
          '<td class="num ' + (t.change_pct >= 0 ? 'up' : 'dn') + '">' + (t.change_pct >= 0 ? '+' : '') + t.change_pct.toFixed(1) + ' pts</td>' +
          '<td><span class="pill pill-' + t.action.toLowerCase() + '">' + t.action + '</span></td></tr>';
      }).join('') +
      '</tbody></table></div>';

    // Trades to execute
    part3 += '<div class="section"><h3>Trades to Execute (with watchlist)</h3>' +
      '<p class="hint">Turnover: ' + rim.turnover_pct.toFixed(0) + '% of portfolio. Dollar and share amounts use today&#39;s prices.</p>' +
      '<table><thead><tr><th>Ticker</th><th>Action</th><th class="num">Now</th><th class="num">Target</th><th class="num">$ Amount</th><th class="num">Shares</th><th class="num">Exp. Return</th></tr></thead><tbody>' +
      ro.trades.filter(function(t) { return t.action !== 'Keep'; }).map(function(t) {
        var isNew = t.current_pct === 0 && t.target_pct > 0;
        return '<tr' + (isNew ? ' style="background:#f3eef8"' : '') + '>' +
          '<td><b>' + esc(t.ticker) + '</b>' + (isNew ? ' <span class="pill" style="background:#ede5f5;color:#7c3aed;font-size:10px">NEW</span>' : '') + '</td>' +
          '<td><span class="pill pill-' + t.action.toLowerCase() + '">' + t.action + '</span></td>' +
          '<td class="num">' + t.current_pct.toFixed(1) + '%</td>' +
          '<td class="num">' + t.target_pct.toFixed(1) + '%</td>' +
          '<td class="num">' + (t.dollars != null ? signUsd(t.dollars) : '') + '</td>' +
          '<td class="num">' + (t.shares != null ? (t.shares >= 0 ? '+' : '') + t.shares.toFixed(3) : '') + '</td>' +
          '<td class="num">' + pct(t.exp_return_pct) + '</td></tr>';
      }).join('') +
      '</tbody></table></div>';

    part3 += '</div>';
  }

  var html = '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>Portfolio Intelligence Report</title><style>' + rptCss + '</style></head><body>' +
    '<div class="header"><h1>Portfolio Intelligence Report</h1><p class="date">' + today + '</p></div>' +
    part1 + '<hr class="divider">' + part2 + part3 +
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
  files = []; holdings = []; manualItems = []; notes = []; candidateTickers = []; window._reopt = null;
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
