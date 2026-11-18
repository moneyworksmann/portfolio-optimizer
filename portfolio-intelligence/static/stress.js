/* ═══════════════════════════════════════════════════════════════
   Portfolio Intelligence — Stress test page
   1. Holdings (carried over from the story page via localStorage, or typed)
   2. /api/sensitivity/model once: how each holding reacts to six factors
   3. Every slider move: /api/sensitivity/simulate (debounced, newest wins)
═══════════════════════════════════════════════════════════════ */
'use strict';

const C = { forest: '#2f6b4f', leaf: '#5fa36a', mint: '#d6ecd9', sky: '#6aa6c8', clay: '#c97b5a', ink: '#1f3a2e', soft: '#7d9087', line: '#e3eadb' };
if (window.Chart) {
  Chart.defaults.font.family = "'Nunito', system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = C.soft;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.tooltip.backgroundColor = C.ink;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 10;
}

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const usd0 = (n) => (n == null || isNaN(n) ? '—' : '$' + Math.round(+n).toLocaleString('en-US'));
const signUsd0 = (n) => (n < 0 ? '−' : '+') + usd0(Math.abs(n));
const usdShort = (v) => { const a = Math.abs(v); return (v < 0 ? '-' : '') + '$' + (a >= 1e6 ? (a / 1e6).toFixed(1) + 'M' : a >= 1e3 ? (a / 1e3).toFixed(1) + 'K' : a.toFixed(0)); };
const pct = (n) => (n == null || isNaN(n) ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(+n).toFixed(1) + '%');
const fmtDate = (s) => (s ? new Date(s + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', year: 'numeric' }) : '—');
const kpi = (label, val, sub, tint) => `<div class="kpi" style="--k:${tint}"><div class="k-label">${label}</div><div class="k-val">${val}</div><div class="k-sub">${sub || ''}</div></div>`;

// Plain-language names and one-line explainers for each factor.
const FACTOR_TEXT = {
  market: { name: 'Stock market (S&P 500)', help: 'A sudden rise or fall in the overall market. −20% is a typical bear market; −34% was the 2020 crash.' },
  rates: { name: 'Interest rates (10-year Treasury)', help: '100 bp = 1 percentage point. Rising rates tend to hurt bonds and fast-growing companies; banks can benefit.' },
  curve: { name: 'Long vs short rates (yield-curve gap)', help: 'Positive widens the gap between 10-year and 3-month rates. A negative gap has often come before recessions.' },
  vol: { name: 'Market fear (VIX)', help: 'The market’s fear gauge. +10 points is a nervous market; +30 is a panic like March 2020.' },
  oil: { name: 'Oil price', help: 'Energy stocks usually rise with oil; airlines, transport and shoppers usually lose.' },
  usd: { name: 'US dollar', help: 'A stronger dollar tends to hurt US companies that earn a lot abroad, and helps importers.' },
};
const SHORT = { market: 'the stock market', rates: 'interest rates', curve: 'the yield-curve gap', vol: 'market fear', oil: 'oil', usd: 'the dollar', sector: 'your sector shocks' };

const ST = {
  holdings: [], model: null, values: {}, shares: {}, prices: {}, shocks: {}, sectors: {}, timer: null, seq: 0, ctrl: null, last: null, charts: {},
  opts: { horizon_months: 12, market_return: 7, vol_mult: 1, target_return: 5, linked: true, fat_tails: true },
};

// ── 1. Holdings ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem('pi_portfolio') || 'null'); } catch (e) { saved = null; }
  if (saved?.holdings?.length) {
    ST.holdings = saved.holdings.map((h) => ({ ticker: h.ticker, shares: +h.shares, sector: h.sector, price: +h.price || null }));
    $('sp-source').innerHTML = `Carried over from your portfolio story (${new Date(saved.saved).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}). Edit anything, then run.`;
  } else {
    ST.holdings = [{ ticker: '', shares: '' }, { ticker: '', shares: '' }, { ticker: '', shares: '' }];
    $('sp-source').innerHTML = 'No portfolio found from this browser yet. Type your holdings below, or <a class="link" href="/">upload them on the main page</a> first and come back.';
  }
  renderHoldings();
  $('sp-add').addEventListener('click', () => { readHoldings(); ST.holdings.push({ ticker: '', shares: '' }); renderHoldings(); });
  $('sp-go').addEventListener('click', loadModel);
  if (saved?.holdings?.length) loadModel();
});

function renderHoldings() {
  $('sp-rows').innerHTML = ST.holdings.map((h, i) => `<tr>
    <td><input type="text" class="sp-t" data-i="${i}" value="${esc(h.ticker)}" placeholder="e.g. AAPL" maxlength="10" style="text-transform:uppercase;width:120px;min-width:0" /></td>
    <td class="num"><input type="number" class="sp-s" data-i="${i}" value="${h.shares === '' ? '' : +h.shares}" placeholder="Shares" min="0" step="any" style="width:120px;min-width:0" /></td>
    <td><button class="btn-del" data-i="${i}" title="Remove">×</button></td></tr>`).join('');
  $('sp-rows').querySelectorAll('.btn-del').forEach((b) => b.addEventListener('click', () => { readHoldings(); ST.holdings.splice(+b.dataset.i, 1); renderHoldings(); }));
}

function readHoldings() {
  ST.holdings = ST.holdings.map((h, i) => {
    const t = document.querySelector(`.sp-t[data-i="${i}"]`), s = document.querySelector(`.sp-s[data-i="${i}"]`);
    const ticker = (t?.value || '').toUpperCase().trim();
    return { ...h, ticker, shares: s?.value === '' ? '' : +s.value, ...(ticker !== h.ticker ? { sector: null, price: null } : {}) };
  });
}

async function loadModel() {
  readHoldings();
  const rows = ST.holdings.filter((h) => h.ticker && +h.shares > 0);
  const msg = $('sp-load-msg');
  msg.style.display = 'none';
  if (!rows.length) { msg.textContent = 'Add at least one ticker with a number of shares.'; msg.style.display = 'block'; return; }
  $('sp-loading').style.display = 'block';
  $('sp-go').disabled = true;
  try {
    const res = await fetch('/api/sensitivity/model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ holdings: rows.map((h) => ({ ticker: h.ticker, sector: h.sector || undefined })) }) });
    const m = await res.json();
    if (m.error || !m.available) throw new Error(m.error || m.reason || 'Could not build the model.');
    ST.model = m;
    ST.values = {}; ST.shares = {}; ST.prices = {};
    const byT = Object.fromEntries(m.assets.map((a) => [a.ticker, a]));
    rows.forEach((h) => {
      const a = byT[h.ticker];
      if (!a) return;
      ST.shares[h.ticker] = (ST.shares[h.ticker] || 0) + +h.shares;
      ST.prices[h.ticker] = h.price || a.price;
    });
    Object.keys(ST.shares).forEach((t) => { ST.values[t] = ST.shares[t] * ST.prices[t]; });
    $('sp-dash').style.display = 'block';
    renderDashboard();
    runStress(0);
    if (m.skipped.length) { msg.className = 'msg info'; msg.textContent = `Not enough price history for ${m.skipped.join(', ')}, so ${m.skipped.length > 1 ? 'they are' : 'it is'} left out.`; msg.style.display = 'block'; }
  } catch (e) {
    msg.className = 'msg'; msg.textContent = `Couldn’t run the stress test: ${e.message}`; msg.style.display = 'block';
  } finally {
    $('sp-loading').style.display = 'none';
    $('sp-go').disabled = false;
    $('sp-go').textContent = 'Update holdings →';
  }
}

// ── 2. Controls ─────────────────────────────────────────────────
function fmtShock(unit, v) {
  const n = Math.abs(v) >= 10 || Number.isInteger(v) ? Math.round(Math.abs(v)) : Math.abs(v).toFixed(1);
  return (v > 0 ? '+' : v < 0 ? '−' : '') + n + (unit === '%' ? '%' : ' ' + unit);
}

function slider(id, label, help, min, max, step, val) {
  return `<div class="st-slider"><div class="st-lab"><span>${label}</span><b id="${id}-v"></b></div>
    <input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}" aria-describedby="${id}-h" />
    <div class="st-scale"><span>${min}</span><span>${max}</span></div>
    ${help ? `<p class="st-help" id="${id}-h">${help}</p>` : ''}</div>`;
}

function renderDashboard() {
  const m = ST.model, o = ST.opts;
  const sectors = [...new Set(m.assets.filter((a) => ST.values[a.ticker] > 0).map((a) => a.sector))].sort();
  ST.sectorList = sectors;
  const nowTxt = (f) => (f.current == null ? '' : f.key === 'rates' ? ` Today: ${f.current.toFixed(2)}%.` : f.key === 'curve' ? ` Today: ${Math.round(f.current)} bp.` : f.key === 'vol' ? ` Today: ${f.current.toFixed(1)}.` : '');

  $('sp-presets').innerHTML = m.presets.map((p) => `<button class="btn st-preset" data-k="${p.key}" title="${esc(presetText(p))}">${esc(p.label)}</button>`).join('') +
    '<button class="btn btn-ghost" id="st-reset">↺ Reset to today</button><p class="sub" id="sp-preset-note" style="width:100%"></p>';

  $('sp-controls').innerHTML = `
    <h3>Shock today</h3><p class="hint">A sudden move, as if it happened overnight. Leave a slider at 0 to keep it unchanged.</p>
    ${m.factors.map((f) => slider('st-f-' + f.key, FACTOR_TEXT[f.key]?.name || esc(f.label), (FACTOR_TEXT[f.key]?.help || '') + nowTxt(f), f.min, f.max, f.step, 0)).join('')}
    <label class="st-check"><input type="checkbox" id="st-linked" ${o.linked ? 'checked' : ''}/> <span><b>Move the others too</b><br><span class="st-help">Sliders left at 0 follow the way they’ve usually moved alongside the ones you set (stocks falling usually means fear rising). Untick to move one thing at a time.</span></span></label>
    <h3 class="st-sec">Sector shocks</h3><p class="hint">An extra rise or fall for just one industry you own, on top of the moves above.</p>
    ${sectors.map((s, i) => slider('st-s-' + i, esc(s), '', -50, 50, 1, 0)).join('')}
    <h3 class="st-sec">How to simulate the future</h3><p class="hint">Settings for the range of outcomes on the right.</p>
    ${slider('st-h', 'How far ahead', 'From 1 month to 10 years.', 1, 120, 1, o.horizon_months)}
    ${slider('st-mr', 'Stock market return you expect', 'Per year, on average. US stocks have averaged roughly 7–10% a year over the long run.', -10, 15, 0.5, o.market_return)}
    ${slider('st-vm', 'How bumpy markets are', '1× is as bumpy as the last 5 years. 2× is crisis-like.', 0.5, 3, 0.1, o.vol_mult)}
    ${slider('st-tr', 'Your target return', 'Per year. We show your chance of reaching it.', -5, 25, 0.5, o.target_return)}
    <label class="st-check"><input type="checkbox" id="st-fat" ${o.fat_tails ? 'checked' : ''}/> <span><b>Allow rare big crashes</b><br><span class="st-help">Makes extreme days more likely than a bell curve would, closer to real markets.</span></span></label>
    <p class="sub" style="margin-top:14px">Sensitivities measured from ${fmtDate(m.window.start)} to ${fmtDate(m.window.end)} (${m.window.weeks} weeks of prices).</p>`;

  const read = () => {
    m.factors.forEach((f) => { ST.shocks[f.key] = +$('st-f-' + f.key).value; });
    ST.sectors = {};
    sectors.forEach((s, i) => { const v = +$('st-s-' + i).value; if (v) ST.sectors[s] = v; });
    Object.assign(ST.opts, { horizon_months: +$('st-h').value, market_return: +$('st-mr').value, vol_mult: +$('st-vm').value, target_return: +$('st-tr').value, linked: $('st-linked').checked, fat_tails: $('st-fat').checked });
    showValues();
    runStress();
  };
  $('sp-controls').querySelectorAll('input').forEach((el) => el.addEventListener('input', () => { clearPreset(); read(); }));
  const setAll = (shocks, secs) => {
    m.factors.forEach((f) => { $('st-f-' + f.key).value = shocks[f.key] || 0; });
    sectors.forEach((s, i) => { $('st-s-' + i).value = secs[s] || 0; });
    read();
  };
  const clearPreset = () => { document.querySelectorAll('.st-preset').forEach((x) => x.classList.remove('active')); $('sp-preset-note').textContent = ''; };
  document.querySelectorAll('.st-preset').forEach((b) => b.addEventListener('click', () => {
    const p = m.presets.find((x) => x.key === b.dataset.k);
    setAll(p.shocks, p.sectors);
    document.querySelectorAll('.st-preset').forEach((x) => x.classList.toggle('active', x === b));
    $('sp-preset-note').textContent = `${p.label}: ${presetText(p)}. Sliders below are set to match; adjust any of them.`;
  }));
  $('st-reset').addEventListener('click', () => { clearPreset(); setAll({}, {}); });
  showValues();
  renderRows();
}

function presetText(p) {
  const parts = Object.entries(p.shocks).map(([k, v]) => `${SHORT[k] || k} ${fmtShock(ST.model.factors.find((f) => f.key === k)?.unit || '%', v)}`);
  Object.entries(p.sectors || {}).forEach(([s, v]) => parts.push(`${s} ${fmtShock('%', v)}`));
  return parts.join(', ');
}

function showValues() {
  const m = ST.model, sc = ST.last?.scenario;
  m.factors.forEach((f) => {
    const v = +$('st-f-' + f.key).value;
    const implied = sc?.implied?.includes(f.key) && v === 0;
    $('st-f-' + f.key + '-v').innerHTML = implied ? `<span class="st-implied" title="Filled in for you from how it usually moves">${fmtShock(f.unit, sc.effective_shocks[f.key])} follows</span>` : fmtShock(f.unit, v);
  });
  ST.sectorList.forEach((s, i) => { $('st-s-' + i + '-v').textContent = fmtShock('%', +$('st-s-' + i).value); });
  const h = +$('st-h').value;
  $('st-h-v').textContent = h < 12 ? `${h} month${h > 1 ? 's' : ''}` : `${+(h / 12).toFixed(1)} year${h > 12 ? 's' : ''}`;
  $('st-mr-v').textContent = (+$('st-mr').value).toFixed(1) + '% a year';
  $('st-vm-v').textContent = (+$('st-vm').value).toFixed(1) + '×';
  $('st-tr-v').textContent = (+$('st-tr').value).toFixed(1) + '% a year';
}

function rowId(p, t) { return `st-${p}-${t.replace(/[^A-Za-z0-9]/g, '_')}`; }

function renderRows() {
  const assets = ST.model.assets.filter((a) => ST.shares[a.ticker] != null);
  $('st-rows').innerHTML = assets.map((a) => `<tr><td><b>${esc(a.ticker)}</b></td><td>${esc(a.sector)}</td>
      <td class="num"><input type="number" class="st-sh" data-t="${esc(a.ticker)}" min="0" step="any" value="${ST.shares[a.ticker]}" style="width:100px;min-width:0" /></td>
      <td class="num" id="${rowId('val', a.ticker)}">${usd0(ST.values[a.ticker])}</td>
      <td class="num" id="${rowId('chp', a.ticker)}">—</td>
      <td class="num" id="${rowId('chd', a.ticker)}">—</td>
      <td class="num">${a.betas.market.toFixed(1)}×</td>
      <td class="num">${a.betas.rates != null ? pct(a.betas.rates * 100 * 100) : '—'}</td></tr>`).join('');
  $('st-rows').querySelectorAll('.st-sh').forEach((el) => el.addEventListener('change', () => {
    const t = el.dataset.t, n = Math.max(0, +el.value || 0);
    ST.shares[t] = n; ST.values[t] = n * (ST.prices[t] || 0);
    $(rowId('val', t)).textContent = usd0(ST.values[t]);
    runStress(0);
  }));
}

// ── 3. Results ──────────────────────────────────────────────────
function runStress(delay = 140) {
  clearTimeout(ST.timer);
  ST.timer = setTimeout(async () => {
    const seq = ++ST.seq;
    if (ST.ctrl) ST.ctrl.abort();
    ST.ctrl = new AbortController();
    document.body.classList.add('st-busy');
    const o = ST.opts;
    try {
      const res = await fetch('/api/sensitivity/simulate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ST.ctrl.signal,
        body: JSON.stringify({ model: ST.model, values: ST.values, shocks: ST.shocks, sector_shocks: ST.sectors,
          horizon_months: o.horizon_months, market_return: o.market_return / 100, vol_mult: o.vol_mult,
          target_return: o.target_return / 100, linked: o.linked, fat_tails: o.fat_tails }),
      });
      const r = await res.json();
      if (seq !== ST.seq) return;
      if (r.error || !r.available) throw new Error(r.error || r.reason);
      ST.last = r;
      draw(r);
    } catch (e) {
      if (e.name === 'AbortError') return;
      $('st-say').innerHTML = `<div class="label">Something went wrong</div><p>${esc(e.message)}</p>`;
    } finally {
      if (seq === ST.seq) document.body.classList.remove('st-busy');
    }
  }, delay);
}

function chart(key, id, cfg) {
  const ch = ST.charts[key];
  if (ch) {
    ch.data.labels = cfg.data.labels;
    cfg.data.datasets.forEach((ds, i) => { if (ch.data.datasets[i]) Object.assign(ch.data.datasets[i], ds); else ch.data.datasets.push(ds); });
    ch.data.datasets.length = cfg.data.datasets.length;
    if (cfg.options?.plugins?.tooltip) ch.options.plugins.tooltip.callbacks = cfg.options.plugins.tooltip.callbacks;
    if (cfg.options?.plugins?.legend) Object.assign(ch.options.plugins.legend, cfg.options.plugins.legend);
    ch.update('none');
    return;
  }
  if (!window.Chart) return;
  cfg.options = { responsive: true, maintainAspectRatio: false, animation: false, ...(cfg.options || {}) };
  ST.charts[key] = new Chart($(id).getContext('2d'), cfg);
}

function factorName(k) { return k === 'sector' ? 'Sector shocks' : (FACTOR_TEXT[k]?.name || k).replace(/ \(.*\)/, ''); }

function draw(r) {
  const sc = r.scenario, b = r.mc.base, s = r.mc.shock, a = r.assumptions;
  const H = a.horizon_months, hz = H < 12 ? `${H} month${H > 1 ? 's' : ''}` : `${+(H / 12).toFixed(1)} year${H > 12 ? 's' : ''}`;
  const shocked = Math.abs(sc.change) > 0.5;
  const down = sc.change < 0;

  $('st-kpis').innerHTML = [
    kpi('Worth today', usd0(r.value_now), `${sc.holdings.length} holdings`, C.mint),
    kpi('Right after the scenario', `<span class="${down ? 'down' : 'up'}">${usd0(sc.value_after)}</span>`, shocked ? `${signUsd0(sc.change)} (${pct(sc.change_pct)})` : 'no scenario set yet', down ? '#f6e3da' : C.mint),
    kpi(`Middle outcome in ${hz}`, usd0(s.percentiles['50']), `9 in 10 between ${usdShort(s.percentiles['5'])} and ${usdShort(s.percentiles['95'])}`, '#dcebf3'),
    kpi('Chance of losing money', `${(s.prob_loss * 100).toFixed(0)}%`, shocked ? `vs ${(b.prob_loss * 100).toFixed(0)}% without the scenario` : `over ${hz}`, '#f7efd9'),
  ].join('');

  const say = [];
  if (shocked) {
    const top = Object.entries(sc.contributions).filter(([, v]) => Math.abs(v) > 0.5).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).slice(0, 2);
    const worst = [...sc.holdings].sort((x, y) => x.change_pct - y.change_pct)[0];
    const best = [...sc.holdings].sort((x, y) => y.change_pct - x.change_pct)[0];
    say.push(`If this happened tomorrow, your portfolio would ${down ? 'lose' : 'gain'} about <b class="${down ? 'down' : 'up'}">${usd0(Math.abs(sc.change))} (${pct(sc.change_pct)})</b>${top.length ? `, mostly because of <b>${top.map(([k]) => esc(SHORT[k] || k)).join('</b> and <b>')}</b>` : ''}.`);
    if (worst && best && worst.ticker !== best.ticker) say.push(`Hardest hit: <b>${esc(worst.ticker)}</b> (${pct(worst.change_pct)}). Holds up best: <b>${esc(best.ticker)}</b> (${pct(best.change_pct)}).`);
  } else {
    say.push('No scenario is set, so this shows the normal range of outcomes for your portfolio. Pick a scenario above or move a slider.');
  }
  say.push(`Looking ${hz} ahead, the middle outcome is <b>${usd0(s.percentiles['50'])}</b>. In a bad case (1 in 20) it would be <b>${usd0(s.percentiles['5'])}</b> or less.`);
  say.push(`Chance of earning your ${ST.opts.target_return.toFixed(1)}% a year target: <b>${(s.prob_target * 100).toFixed(0)}%</b>. Chance of a 20%+ drop from a high along the way: <b>${(s.prob_drawdown20 * 100).toFixed(0)}%</b>.`);
  $('st-say').innerHTML = `<div class="label">🌿 In plain words</div>${say.map((x) => `<p>${x}</p>`).join('')}`;
  $('st-fan-hint').textContent = `${a.paths.toLocaleString()} simulated futures over ${hz}. Assumes about ${a.expected_return_pct.toFixed(1)}% a year average growth and ${a.volatility_pct.toFixed(0)}% typical yearly swings.`;

  const by = Object.fromEntries(sc.holdings.map((h) => [h.ticker, h]));
  ST.model.assets.forEach((x) => {
    const p = $(rowId('chp', x.ticker)), d = $(rowId('chd', x.ticker));
    if (!p) return;
    const h = by[x.ticker];
    const cls = h && h.change < -0.005 ? 'down' : h && h.change > 0.005 ? 'up' : '';
    p.textContent = h ? pct(h.change_pct) : '—'; p.className = 'num ' + cls;
    d.textContent = h ? signUsd0(h.change) : '—'; d.className = 'num ' + cls;
  });

  const keys = [...ST.model.factor_keys, 'sector'];
  const vals = keys.map((k) => sc.contributions[k] || 0);
  chart('contrib', 'c-st-contrib', {
    type: 'bar',
    data: { labels: keys.map(factorName), datasets: [{ data: vals, backgroundColor: vals.map((v) => (v < 0 ? C.clay : C.leaf)), borderRadius: 6 }] },
    options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${signUsd0(c.raw)}${sc.implied.includes(keys[c.dataIndex]) ? ' (filled in for you)' : ''}` } } },
      scales: { x: { grid: { color: C.line }, ticks: { callback: (v) => usdShort(v) } }, y: { grid: { display: false }, ticks: { color: C.ink, font: { weight: 700 } } } } },
  });

  const ex = r.exposures;
  chart('tornado', 'c-st-tornado', {
    type: 'bar',
    data: { labels: ex.map((x) => `${factorName(x.key)} ±${x.standard}${x.unit === '%' ? '%' : ' ' + x.unit}`), datasets: [
      { label: 'Factor goes up', data: ex.map((x) => x.pct_up), backgroundColor: C.leaf, borderRadius: 5 },
      { label: 'Factor goes down', data: ex.map((x) => x.pct_down), backgroundColor: C.clay, borderRadius: 5 },
    ] },
    options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${pct(c.raw)} on your portfolio` } } },
      scales: { x: { stacked: true, grid: { color: C.line }, ticks: { callback: (v) => v + '%' } }, y: { stacked: true, grid: { display: false }, ticks: { color: C.ink, font: { weight: 700 } } } } },
  });

  const lbl = r.mc.months.map((x) => (x === 0 ? 'Today' : x < 1 ? `${Math.round(x * 4.33)} wk` : x < 24 ? `${+x.toFixed(1)} mo` : `${+(x / 12).toFixed(1)} yr`));
  chart('fan', 'c-st-fan', {
    type: 'line',
    data: { labels: lbl, datasets: [
      { label: 'Best 5%', data: s.fan['95'], borderColor: 'transparent', backgroundColor: 'rgba(95,163,106,.14)', fill: '+4', pointRadius: 0, tension: 0.2 },
      { label: 'Upper middle', data: s.fan['75'], borderColor: 'transparent', backgroundColor: 'rgba(95,163,106,.28)', fill: '+2', pointRadius: 0, tension: 0.2 },
      { label: 'Middle outcome', data: s.fan['50'], borderColor: C.forest, borderWidth: 2.5, fill: false, pointRadius: 0, tension: 0.2 },
      { label: 'Lower middle', data: s.fan['25'], borderColor: 'transparent', fill: false, pointRadius: 0, tension: 0.2 },
      { label: 'Worst 5%', data: s.fan['5'], borderColor: 'transparent', fill: false, pointRadius: 0, tension: 0.2 },
      { label: 'Middle, no scenario', data: b.fan['50'], borderColor: C.soft, borderDash: [5, 4], borderWidth: 1.5, fill: false, pointRadius: 0, tension: 0.2, hidden: !shocked },
    ] },
    options: { interaction: { mode: 'index', intersect: false }, plugins: { legend: { labels: { filter: (i) => ['Middle outcome', 'Middle, no scenario'].includes(i.text) } }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${usd0(c.raw)}` } } },
      scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 12 } }, y: { grid: { color: C.line }, ticks: { callback: (v) => usdShort(v) } } } },
  });

  const e = r.mc.hist.edges, mids = e.slice(0, -1).map((x, i) => (x + e[i + 1]) / 2);
  $('st-hist-hint').textContent = `Share of the ${a.paths.toLocaleString()} simulated futures ending at each value after ${hz}`;
  chart('hist', 'c-st-hist', {
    type: 'bar',
    data: { labels: mids.map(usdShort), datasets: [
      { label: shocked ? 'With the scenario' : 'Simulated futures', data: r.mc.hist.shock.map((x) => (x / a.paths) * 100), backgroundColor: mids.map((x) => (x < r.value_now ? 'rgba(201,123,90,.75)' : 'rgba(95,163,106,.8)')), borderRadius: 3, categoryPercentage: 1, barPercentage: 0.95 },
      { label: 'Without the scenario', type: 'line', data: r.mc.hist.base.map((x) => (x / a.paths) * 100), borderColor: C.soft, borderDash: [4, 3], borderWidth: 1.5, pointRadius: 0, tension: 0.3, hidden: !shocked },
    ] },
    options: { plugins: { legend: { display: shocked }, tooltip: { callbacks: { title: (c) => `About ${usd0(mids[c[0].dataIndex])}`, label: (c) => ` ${c.dataset.label}: ${c.raw.toFixed(1)}% of futures` } } },
      scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 6, maxRotation: 0 } }, y: { grid: { color: C.line }, ticks: { callback: (v) => v + '%' } } } },
  });

  showValues();
}
