
import { api } from '../api.js';

export async function renderAudit(el) {
  const data = await api('/api/audits?limit=120');
  const sum = data.summary || { total: 0, by_action: [], bin_slots: [] };
  const slots = sum.bin_slots || [];
  const totalPending = slots.reduce((acc, s) => acc + (s.pending_count || 0), 0);
  el.innerHTML = `
    <div class="card">
      <h2>审计轨迹</h2>
      <p class="muted">共 ${sum.total} 条。动作分布：
        ${(sum.by_action || []).map((a) => `${a.action} ${a.c}`).join(' · ') || '暂无'}
      </p>
    </div>
    <div class="card">
      <h3>舱位摘要 <span class="chip">待复核合计 ${totalPending}</span></h3>
      <table>
        <thead><tr><th>舱号</th><th>标题</th><th>状态</th><th>占用/容量</th><th>待复核</th></tr></thead>
        <tbody>
          ${slots.map((s) => `
            <tr>
              <td>${s.bin_code}</td>
              <td>${s.title}</td>
              <td><span class="chip">${s.status}</span></td>
              <td>${s.row_count}/${s.capacity}</td>
              <td>${s.pending_count}</td>
            </tr>`).join('') || '<tr><td colspan="5" class="muted">暂无舱位</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>详情</th></tr></thead>
        <tbody>
          ${(data.items || []).map((e) => `
            <tr>
              <td>${e.created_at}</td>
              <td>${e.actor}</td>
              <td><span class="chip">${e.action}</span></td>
              <td>${e.entity_type}#${e.entity_id}</td>
              <td>${e.detail || ''}</td>
            </tr>`).join('') || '<tr><td colspan="5" class="muted">暂无审计</td></tr>'}
        </tbody>
      </table>
    </div>`;
}
