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
        { label: '7D MA', type: 'line', data: data.ma7, borderColor: '#6c757d' },
        { label: 'Trades', type: 'line', data: data.counts || [], borderColor: '#0d6efd', yAxisID: 'y1' }
      ]},
      options: { responsive: true, interaction: { mode: 'index', intersect: false }, scales: { y: { title: { text: 'USD', display: true } }, y1: { position: 'right', title: { text: 'Trades', display: true }, grid: { drawOnChartArea: false } } } }
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

  function getHorizonParams() {
    const horizon = parseInt(qv('proj-horizon')?.value || '3', 10);
    const isDaily = qv('proj-daily')?.classList.contains('active');
    if (isDaily) {
      const days = Math.max(0, Math.min(14, isNaN(horizon) ? 7 : horizon));
      return `projection_days=${days}`;
    }
    const months = Math.max(0, Math.min(6, isNaN(horizon) ? 3 : horizon));
    return `projection_months=${months}`;
  }

  async function loadMonthly() {
    const res = await fetch(`/stats/api/pnl-by-month?${buildQuery()}&${getHorizonParams()}`);
    const data = await res.json();
    const ctx = qv('chart-monthly-pnl').getContext('2d');
    state.charts.monthly?.destroy();
    const labels = data.labels.concat(data.projection_labels || []);
    const values = data.pnl.concat((data.projection || []).map(v => v));
    const bg = labels.map((_, i) => i < data.labels.length ? 'rgba(13,110,253,0.6)' : 'rgba(13,110,253,0.2)');
    state.charts.monthly = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets: [ { label: 'Monthly PnL (adj.)', data: values, backgroundColor: bg } ] },
      options: { scales: { y: { title: { text: 'USD', display: true } } }, plugins: { legend: { display: false } } }
    });
  }

  async function loadDailyProjection() {
    const res = await fetch(`/stats/api/pnl-by-day?${buildQuery()}&${getHorizonParams()}`);
    const data = await res.json();
    const ctx = qv('chart-daily-pnl').getContext('2d');
    state.charts.dailyProjection?.destroy();
    const labels = data.labels.concat(data.projection_labels || []);
    const values = data.pnl.concat((data.projection || []).map(v => v));
    const bg = labels.map((_, i) => i < data.labels.length ? 'rgba(25,135,84,0.6)' : 'rgba(25,135,84,0.2)');
    state.charts.dailyProjection = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets: [ { label: 'Daily PnL (adj.)', data: values, backgroundColor: bg }, { label: '7D MA', type: 'line', data: data.ma7.concat(new Array((data.projection||[]).length).fill(null)), borderColor: '#6c757d' } ] },
      options: { scales: { y: { title: { text: 'USD', display: true } } }, plugins: { legend: { position: 'bottom' } } }
    });
  }

  async function loadCloseReasons() {
    const res = await fetch(`/stats/api/close-reasons?${buildQuery()}`);
    const data = await res.json();
    const labels = data.items.map(i => i.reason);
    const counts = data.items.map(i => i.count);
    const winRates = data.items.map(i => i.win_rate);
    const ctx = qv('chart-close-reasons').getContext('2d');
    state.charts.closeReasons?.destroy();
    state.charts.closeReasons = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets: [
        { label: 'Count', data: counts, backgroundColor: 'rgba(108,117,125,0.6)' },
        { label: 'Win Rate %', data: winRates, type: 'line', borderColor: '#198754', yAxisID: 'y1' }
      ]},
      options: { responsive: true, interaction: { mode: 'index', intersect: false }, scales: { y: { title: { text: 'Count', display: true } }, y1: { position: 'right', title: { text: '%', display: true }, min: 0, max: 100 } } }
    });
  }

  async function loadScatterConfidence() {
    const res = await fetch(`/stats/api/analysis/confidence-pnl-scatter?${buildQuery()}`);
    const data = await res.json();
    const ctx = qv('chart-scatter-conf').getContext('2d');
    state.charts.scatterConf?.destroy();
    state.charts.scatterConf = new Chart(ctx, {
      type: 'scatter',
      data: { datasets: [{ label: 'Trades', data: data.points, parsing: { xAxisKey: 'x', yAxisKey: 'y' }, pointBackgroundColor: '#0d6efd', pointRadius: 3 }] },
      options: { scales: { x: { title: { text: 'Confidence', display: true }, min: 0.5, max: 1.0 }, y: { title: { text: 'PnL (USD, adj.)', display: true } } } }
    });
  }

  async function loadScatterDuration() {
    const res = await fetch(`/stats/api/analysis/duration-pnl-scatter?${buildQuery()}`);
    const data = await res.json();
    const ctx = qv('chart-scatter-dur').getContext('2d');
    state.charts.scatterDur?.destroy();
    state.charts.scatterDur = new Chart(ctx, {
      type: 'scatter',
      data: { datasets: [{ label: 'Trades', data: data.points, parsing: { xAxisKey: 'x', yAxisKey: 'y' }, pointBackgroundColor: '#6c757d', pointRadius: 3 }] },
      options: { scales: { x: { title: { text: 'Duration (min)', display: true } }, y: { title: { text: 'PnL (USD, adj.)', display: true } } } }
    });
  }

  async function refreshAll() {
    const isDaily = qv('proj-daily')?.classList.contains('active');
    const projLoader = isDaily ? loadDailyProjection() : loadMonthly();
    await Promise.all([
      loadSummary(), loadEquity(), loadDaily(), loadDirection(),
      projLoader, loadCloseReasons(),
      loadSymbols(), loadHeatmap(),
      loadScatterConfidence(), loadScatterDuration()
    ]);
  }

  function init() {
    const btn = qv('apply-filters');
    if (btn) btn.addEventListener('click', refreshAll);
    // Ensure system-wide by default: clear any autofilled symbol
    const symInput = qv('filter-symbol');
    if (symInput) symInput.value = '';
    // Toggle between monthly and daily projection chart
    const btnMonthly = qv('proj-monthly');
    const btnDaily = qv('proj-daily');
    if (btnMonthly && btnDaily) {
      btnMonthly.addEventListener('click', () => {
        btnMonthly.classList.add('active');
        btnDaily.classList.remove('active');
        qv('chart-monthly-pnl').style.display = '';
        qv('chart-daily-pnl').style.display = 'none';
        const lab = qv('proj-horizon-label'); if (lab) lab.textContent = 'Months';
        const input = qv('proj-horizon');
        if (input) { input.setAttribute('max','6'); if (parseInt(input.value||'0',10) > 6) input.value = '3'; }
      });
      btnDaily.addEventListener('click', () => {
        btnDaily.classList.add('active');
        btnMonthly.classList.remove('active');
        qv('chart-monthly-pnl').style.display = 'none';
        qv('chart-daily-pnl').style.display = '';
        const lab = qv('proj-horizon-label'); if (lab) lab.textContent = 'Days';
        const input = qv('proj-horizon');
        if (input) { input.setAttribute('max','14'); if (parseInt(input.value||'0',10) > 14) input.value = '7'; }
      });
    }
    const applyH = qv('proj-apply');
    if (applyH) applyH.addEventListener('click', () => {
      const isDaily = qv('proj-daily')?.classList.contains('active');
      if (isDaily) { loadDailyProjection(); }
      else { loadMonthly(); }
    });
    refreshAll();
  }

  document.addEventListener('DOMContentLoaded', init);
})();


