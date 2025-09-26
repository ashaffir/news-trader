(function(){
  const state = { page: 1, pageSize: 50 };
  const qv = (id) => document.getElementById(id);

  function buildQuery(){
    const p = new URLSearchParams();
    const s = qv('filter-start')?.value; const e = qv('filter-end')?.value; const sym = qv('filter-symbol')?.value?.trim();
    if (s) p.set('start', new Date(s).toISOString());
    if (e) p.set('end', new Date(e).toISOString());
    if (sym) p.set('symbol', sym);
    p.set('page', String(state.page));
    p.set('page_size', String(state.pageSize));
    return p.toString();
  }

  function formatDt(iso){ if (!iso) return '-'; try { const d=new Date(iso); return d.toLocaleString(); } catch { return '-'; } }
  function formatDur(mins){ if (mins==null) return '-'; const h=Math.floor(mins/60); const m=mins%60; return h?`${h}h ${m}m`:`${m}m`; }
  function formatPnl(v){ if (v==null) return '-'; const s = Number(v).toFixed(2); return (v>=0?'+$':'-$') + Math.abs(Number(s)); }
  function formatConf(v){ if (v==null) return '-'; return Number(v).toFixed(2); }

  function render(rows, total){
    const tbody = qv('trades-body');
    tbody.innerHTML = '';
    for (const r of rows){
      const tr = document.createElement('tr');
      const srcLink = r.source_url ? `<a href="${r.source_url}" target="_blank" rel="noreferrer noopener">Source</a>` : '-';
      const dateStr = r.opened_at ? r.opened_at.slice(0,10) : '';
      const assetUrl = r.symbol && dateStr ? `/stats/asset/${encodeURIComponent(r.symbol)}/${encodeURIComponent(dateStr)}/` : '#';
      tr.innerHTML = `
        <td class="nowrap">${r.symbol || '-'}</td>
        <td class="nowrap text-capitalize">${r.direction || '-'}</td>
        <td class="nowrap">${formatDt(r.opened_at)}</td>
        <td class="nowrap">${formatDt(r.closed_at)}</td>
        <td class="nowrap">${formatDur(r.duration_minutes)}</td>
        <td class="nowrap">${formatPnl(r.pnl_adjusted)}</td>
        <td class="nowrap">${srcLink}</td>
        <td class="nowrap">${formatConf(r.confidence)}</td>
        <td class="nowrap">${r.close_reason || '-'}</td>
        <td class="nowrap"><a class="btn btn-sm btn-outline-primary" href="${assetUrl}" target="_blank" rel="noreferrer noopener">View</a></td>
      `;
      tbody.appendChild(tr);
    }
    qv('total-count').textContent = String(total || 0);
    qv('page-num').textContent = String(state.page);
  }

  async function load(){
    const res = await fetch(`/stats/api/trades-log?${buildQuery()}`);
    const data = await res.json();
    render(data.items || [], data.total || 0);
  }

  function init(){
    const apply = qv('apply-filters');
    if (apply) apply.addEventListener('click', () => { state.page = 1; load(); });
    const prev = qv('prev-page'); const next = qv('next-page');
    if (prev) prev.addEventListener('click', () => { if (state.page>1){ state.page -= 1; load(); } });
    if (next) next.addEventListener('click', () => { state.page += 1; load(); });
    load();
  }

  document.addEventListener('DOMContentLoaded', init);
})();


