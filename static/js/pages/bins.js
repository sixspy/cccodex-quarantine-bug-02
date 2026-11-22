import { api } from '../api.js';

export async function renderBins(el) {
  const bins = await api('/api/bins');
  const rows = await api('/api/rows');
  const totalReleased = (bins.items || []).reduce((acc, b) => acc + (b.released_count || 0), 0);
  el.innerHTML = `
    <div class="card">
      <h2>隔离舱 <span class="chip ok">已放行 ${totalReleased}</span></h2>
      <table>
        <thead><tr><th>舱号</th><th>标题</th><th>状态</th><th>占用/容量</th><th>待复核</th><th>已放行</th></tr></thead>
        <tbody>
          ${(bins.items || []).map((b) => `
            <tr>
              <td>${b.bin_code}</td>
              <td>${b.title}</td>
              <td><span class="chip">${b.status}</span></td>
              <td>${b.row_count}/${b.capacity}</td>
              <td>${b.pending_count}</td>
              <td><span class="chip ok">${b.released_count || 0}</span></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>舱内行</h2>
      <table>
        <thead><tr><th>舱</th><th>条目键</th><th>质量</th><th>原因</th><th>状态</th></tr></thead>
        <tbody>
          ${(rows.items || []).map((r) => `
            <tr>
              <td>${r.bin_code}</td>
              <td>${r.item_key}</td>
              <td>${r.quality}</td>
              <td>${r.reason}</td>
              <td>${r.status === '已放行' ? '<span class="chip ok">已放行</span>' : `<span class="chip">${r.status}</span>`}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}
