/* global Chart */
(function(){
  function qs(sel){ return document.querySelector(sel); }
  function val(el){ return el && el.value ? el.value.trim() : ''; }
  function fmtPct(n){ return (n || 0).toFixed(2) + '%'; }
  function fmtNum(n){ return (n || 0).toFixed(2); }
  function buildParams(){
    const params = new URLSearchParams();
    const s = val(qs('#filter-start'));
    const e = val(qs('#filter-end'));
    const sym = val(qs('#filter-symbol'));
    const minc = val(qs('#filter-min-confidence'));
    const ind = val(qs('#filter-industry'));
    const sec = val(qs('#filter-sector'));
    const src = val(qs('#filter-source'));
    if (s) params.set('start', new Date(s).toISOString());
    if (e) params.set('end', new Date(e).toISOString());
    if (sym) params.set('symbol', sym);
    if (minc) params.set('min_confidence', minc);
    if (ind) params.set('industry', ind);
    if (sec) params.set('sector', sec);
    if (src) params.set('source', src);
    return params.toString();
  }

  const charts = {};
  function ensureChart(id, cfg){
    if (charts[id]) { charts[id].destroy(); }
    const ctx = document.getElementById(id);
    if (!ctx) return null;
    charts[id] = new Chart(ctx, cfg);
    return charts[id];
  }

  async function loadKpis(){
    const res = await fetch('/stats/api/analysis/threshold-simulation?' + buildParams());
    const data = await res.json();
    qs('#kpi-trades').textContent = data.trades;
    qs('#kpi-win-rate').textContent = fmtPct(data.win_rate);
    qs('#kpi-total-pnl').textContent = fmtNum(data.total_pnl_adjusted);
    qs('#kpi-avg-pnl').textContent = fmtNum(data.avg_pnl);
  }

  async function loadConfidence(){
    const res = await fetch('/stats/api/analysis/confidence-distribution?' + buildParams());
    const d = await res.json();
    ensureChart('chart-confidence', {
      type: 'bar',
      data: { labels: d.bins, datasets: [
        { label: 'All', data: d.all_counts, backgroundColor: 'rgba(54, 162, 235, 0.6)' },
        { label: 'Winners', data: d.win_counts, backgroundColor: 'rgba(75, 192, 192, 0.6)' },
        { label: 'Losers', data: d.lose_counts, backgroundColor: 'rgba(255, 99, 132, 0.6)' }
      ]},
      options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
    });
  }

  async function loadCalibration(){
    const res = await fetch('/stats/api/analysis/calibration?' + buildParams());
    const d = await res.json();
    ensureChart('chart-calibration', {
      type: 'line',
      data: { labels: d.bins, datasets: [
        { label: 'Win Rate', data: d.win_rate, borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,0.2)', fill: true }
      ]},
      options: { scales: { y: { ticks: { callback: v => v + '%' } } } }
    });
  }

  async function loadConfidencePnl(){
    const res = await fetch('/stats/api/analysis/confidence-pnl-buckets?' + buildParams());
    const d = await res.json();
    ensureChart('chart-conf-pnl', {
      type: 'bar',
      data: { labels: d.bins, datasets: [
        { label: 'Avg PnL', data: d.avg_pnl, backgroundColor: 'rgba(153, 102, 255, 0.6)' },
        { label: 'Total PnL', data: d.total_pnl, backgroundColor: 'rgba(255, 206, 86, 0.6)' }
      ]},
      options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
    });
  }

  async function loadDirBucket(){
    const res = await fetch('/stats/api/analysis/behavior?' + buildParams());
    const d = await res.json();
    ensureChart('chart-dir-bucket', {
      type: 'bar',
      data: { labels: d.conf_bins, datasets: [
        { label: 'Buy Win %', data: d.buy_win_rate, backgroundColor: 'rgba(75, 192, 192, 0.6)' },
        { label: 'Sell Win %', data: d.sell_win_rate, backgroundColor: 'rgba(255, 99, 132, 0.6)' }
      ]},
      options: { scales: { y: { ticks: { callback: v => v + '%' } } } }
    });
  }

  async function loadIndustry(){
    const res = await fetch('/stats/api/analysis/industry-performance?' + buildParams());
    const d = await res.json();
    ensureChart('chart-industry', {
      type: 'bar',
      data: { labels: d.items.map(x => x.name), datasets: [
        { label: 'Win %', data: d.items.map(x => x.win_rate), backgroundColor: 'rgba(13,110,253,0.6)', yAxisID: 'y1' },
        { label: 'Total PnL', data: d.items.map(x => x.total_pnl_adjusted), backgroundColor: 'rgba(255,193,7,0.6)', yAxisID: 'y2' }
      ]},
      options: { responsive: true, scales: { y1: { position: 'left', ticks: { callback: v => v + '%' } }, y2: { position: 'right' } } }
    });
  }

  async function loadSector(){
    const res = await fetch('/stats/api/analysis/sector-performance?' + buildParams());
    const d = await res.json();
    ensureChart('chart-sector', {
      type: 'bar',
      data: { labels: d.items.map(x => x.name), datasets: [
        { label: 'Win %', data: d.items.map(x => x.win_rate), backgroundColor: 'rgba(40,167,69,0.6)', yAxisID: 'y1' },
        { label: 'Total PnL', data: d.items.map(x => x.total_pnl_adjusted), backgroundColor: 'rgba(220,53,69,0.6)', yAxisID: 'y2' }
      ]},
      options: { responsive: true, scales: { y1: { position: 'left', ticks: { callback: v => v + '%' } }, y2: { position: 'right' } } }
    });
  }

  async function loadSource(){
    const res = await fetch('/stats/api/analysis/source-performance?' + buildParams());
    const d = await res.json();
    ensureChart('chart-source', {
      type: 'bar',
      data: { labels: d.items.map(x => x.name), datasets: [
        { label: 'Win %', data: d.items.map(x => x.win_rate), backgroundColor: 'rgba(23,162,184,0.6)', yAxisID: 'y1' },
        { label: 'Total PnL', data: d.items.map(x => x.total_pnl_adjusted), backgroundColor: 'rgba(111,66,193,0.6)', yAxisID: 'y2' }
      ]},
      options: { responsive: true, scales: { y1: { position: 'left', ticks: { callback: v => v + '%' } }, y2: { position: 'right' } } }
    });
  }

  async function loadModel(){
    const res = await fetch('/stats/api/analysis/model-performance?' + buildParams());
    const d = await res.json();
    ensureChart('chart-model', {
      type: 'bar',
      data: { labels: d.items.map(x => x.name), datasets: [
        { label: 'Win %', data: d.items.map(x => x.win_rate), backgroundColor: 'rgba(0,123,255,0.6)', yAxisID: 'y1' },
        { label: 'Total PnL', data: d.items.map(x => x.total_pnl_adjusted), backgroundColor: 'rgba(255,159,64,0.6)', yAxisID: 'y2' }
      ]},
      options: { responsive: true, scales: { y1: { position: 'left', ticks: { callback: v => v + '%' } }, y2: { position: 'right' } } }
    });
  }

  async function runSim(){
    const params = buildParams();
    const x = val(qs('#sim-min-confidence'));
    const url = '/stats/api/analysis/threshold-simulation?' + params + (x ? '&min_confidence=' + encodeURIComponent(x) : '');
    const d = await (await fetch(url)).json();
    qs('#sim-trades').textContent = d.trades;
    qs('#sim-win-rate').textContent = fmtPct(d.win_rate);
    qs('#sim-total-pnl').textContent = fmtNum(d.total_pnl_adjusted);
    qs('#sim-avg-pnl').textContent = fmtNum(d.avg_pnl);
  }

  function reloadAll(){
    loadKpis();
    loadConfidence();
    loadCalibration();
    loadConfidencePnl();
    loadDirBucket();
    loadIndustry();
    loadSector();
    loadSource();
    loadModel();
    loadScatter();
  }

  document.addEventListener('DOMContentLoaded', function(){
    const apply = qs('#apply-filters');
    if (apply) apply.addEventListener('click', function(){ reloadAll(); });
    const run = qs('#run-sim');
    if (run) run.addEventListener('click', function(){ runSim(); });
    reloadAll();
  });

  async function loadScatter(){
    const qp = buildParams();
    const cdata = await (await fetch('/stats/api/analysis/confidence-pnl-scatter?' + qp)).json();
    ensureChart('chart-scatter-conf', {
      type: 'scatter',
      data: { datasets: [{ label: 'PnL by Confidence', data: cdata.points, parsing: { xAxisKey: 'x', yAxisKey: 'y' }, backgroundColor: 'rgba(13,110,253,0.6)' }] },
      options: { scales: { x: { min: 0.5, max: 1.0 } } }
    });

    const ddata = await (await fetch('/stats/api/analysis/duration-pnl-scatter?' + qp)).json();
    ensureChart('chart-scatter-dur', {
      type: 'scatter',
      data: { datasets: [{ label: 'PnL by Duration (min)', data: ddata.points, parsing: { xAxisKey: 'x', yAxisKey: 'y' }, backgroundColor: 'rgba(40,167,69,0.6)' }] },
      options: { scales: { x: { title: { display: true, text: 'Minutes' } } } }
    });
  }
})();


