// Stats page controller using Chart.js and vanilla fetch
(function () {
  const qs = (s) => document.querySelector(s);
  const qv = (id) => document.getElementById(id);
  const state = { charts: {} };

  function buildQuery() {
    const p = new URLSearchParams();
    const s = qv('filter-start')?.value; const e = qv('filter-end')?.value; const sym = qv('filter-symbol')?.value?.trim();
    if (s) p.set('start', new Date(s).toISOString());
    if (e) p.set('end', new Date(e).toISOString());
    if (sym) p.set('symbol', sym);
    return p.toString();
  }

  async function loadSummary() {
    const res = await fetch(`/stats/api/summary?${buildQuery()}`);
    const data = await res.json();
    qv('kpi-total-pnl').textContent = `$${(data.total_pnl_adjusted || 0).toFixed(2)}`;
    qv('kpi-win-rate').textContent = `${(data.win_rate || 0).toFixed(2)}%`;
    qv('kpi-max-dd').textContent = `${(data.max_drawdown || 0).toFixed(2)}%`;
    qv('kpi-sharpe').textContent = `${(data.sharpe_daily || 0).toFixed(2)}`;
    qv('kpi-avg-r').textContent = `${(data.avg_r_per_trade || 0).toFixed(2)}`;
    qv('kpi-trades').textContent = `${data.total_trades || 0}`;
  }

  async function loadEquity() {
    const res = await fetch(`/stats/api/equity?${buildQuery()}`);
    const data = await res.json();
    const ctx = qv('chart-equity').getContext('2d');
    state.charts.equity?.destroy();
    state.charts.equity = new Chart(ctx, {
      type: 'line',
      data: { labels: data.labels, datasets: [
        { label: 'Equity (adj.)', data: data.equity, borderColor: '#0d6efd', fill: false },
        { label: 'Drawdown %', data: data.drawdown_pct, borderColor: '#dc3545', yAxisID: 'y1' }
      ]},
      options: { responsive: true, interaction: { mode: 'index', intersect: false }, scales: { y: { title: { text: 'USD', display: true } }, y1: { position: 'right', title: { text: '%', display: true } } } }
    });
  }

  async function loadDaily() {
    const res = await fetch(`/stats/api/pnl-by-day?${buildQuery()}`);
    const data = await res.json();
    const ctx = qv('chart-daily').getContext('2d');
    state.charts.daily?.destroy();
    state.charts.daily = new Chart(ctx, {
      type: 'bar',
      data: { labels: data.labels, datasets: [
        { label: 'PnL', data: data.pnl, backgroundColor: data.pnl.map(v => v >= 0 ? 'rgba(25,135,84,0.6)' : 'rgba(220,53,69,0.6)') },
        { label: '7D MA', type: 'line', data: data.ma7, borderColor: '#6c757d' }
      ]},
      options: { responsive: true, interaction: { mode: 'index', intersect: false }, scales: { y: { title: { text: 'USD', display: true } } } }
    });
  }

  async function loadDirection() {
    const res = await fetch(`/stats/api/direction-breakdown?${buildQuery()}`);
    const data = await res.json();
    const ctx = qv('chart-direction').getContext('2d');
    state.charts.direction?.destroy();
    state.charts.direction = new Chart(ctx, {
      type: 'bar',
      data: { labels: ['Buy', 'Sell'], datasets: [
        { label: 'Count', data: [data.buy.count, data.sell.count], backgroundColor: 'rgba(13,110,253,0.6)' },
        { label: 'PnL (adj.)', data: [data.buy.pnl_adjusted, data.sell.pnl_adjusted], backgroundColor: 'rgba(13,202,240,0.6)', yAxisID: 'y1' }
      ]},
      options: { responsive: true, interaction: { mode: 'index', intersect: false }, scales: { y: { title: { text: 'Count', display: true } }, y1: { position: 'right', title: { text: 'USD', display: true } } } }
    });
  }

  async function loadSymbols() {
    const res = await fetch(`/stats/api/per-symbol?${buildQuery()}`);
    const data = await res.json();
    const labels = data.map(d => d.symbol);
    const pnl = data.map(d => d.total_pnl_adjusted);
    const ctx = qv('chart-symbols').getContext('2d');
    state.charts.symbols?.destroy();
    state.charts.symbols = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets: [ { label: 'PnL (adj.)', data: pnl, backgroundColor: 'rgba(108,117,125,0.6)' } ] },
      options: { indexAxis: 'y', scales: { x: { title: { text: 'USD', display: true } } } }
    });
  }

  async function loadHeatmap() {
    const res = await fetch(`/stats/api/heatmap?${buildQuery()}`);
    const data = await res.json();
    // Render a fake heatmap via stacked bars (weekday labels, hour bins as datasets)
    const ctx = qv('chart-heatmap').getContext('2d');
    state.charts.heatmap?.destroy();
    const colors = ['#e9ecef','#dee2e6','#ced4da','#adb5bd','#6c757d','#495057','#343a40','#212529'];
    state.charts.heatmap = new Chart(ctx, {
      type: 'bar',
      data: { labels: data.weekdays, datasets: data.hours.map((h, idx) => ({ label: h, data: data.matrix[idx], backgroundColor: colors[idx % colors.length] })) },
      options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { stacked: true }, y: { stacked: true, title: { text: 'Trades', display: true } } } }
    });
  }

  async function refreshAll() {
    await Promise.all([loadSummary(), loadEquity(), loadDaily(), loadDirection(), loadSymbols(), loadHeatmap()]);
  }

  function init() {
    const btn = qv('apply-filters');
    if (btn) btn.addEventListener('click', refreshAll);
    // Ensure system-wide by default: clear any autofilled symbol
    const symInput = qv('filter-symbol');
    if (symInput) symInput.value = '';
    refreshAll();
  }

  document.addEventListener('DOMContentLoaded', init);
})();


