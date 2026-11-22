import { api } from '../api.js';

export async function renderReview(el) {
  const data = await api('/api/tickets');
  const tickets = data.items || [];
  const releasedCount = tickets.filter((t) => t.decision === '放行' && t.ledger_id).length;
  el.innerHTML = `
    <div class="card">
      <h2>复核放行
        <span class="chip ok" id="releaseChip">已放行 ${releasedCount}</span>
      </h2>
      <p class="muted">放行读轨：切流账册（只追加、禁回刷）。放行成功后抓取侧同步翻“已放行”。</p>
      <table>
        <thead><tr><th>单号</th><th>条目</th><th>舱</th><th>裁决</th><th>放行落点</th><th>操作</th></tr></thead>
        <tbody>
          ${tickets.map((t) => `
            <tr>
              <td>${t.ticket_code}</td>
              <td>${t.item_key}</td>
              <td>${t.bin_code}</td>
              <td>${t.decision === '放行'
                ? '<span class="chip ok">已放行</span>'
                : `<span class="chip">${t.decision}</span>`}</td>
              <td class="release-landing">
                ${t.ledger_id ? `
                  <div class="landing-row">
                    <span class="muted">落点#${t.ledger_id} · ${t.channel || '复核放行'}</span>
                    <code class="fp">${t.fingerprint ? t.fingerprint.slice(0, 12) : ''}…</code>
                  </div>`
                  : '<span class="muted">—</span>'}
              </td>
              <td class="row">
                ${t.decision === '待决' ? `
                  <button data-d="放行" data-id="${t.id}">放行</button>
                  <button data-d="驳回回炉" data-id="${t.id}">驳回回炉</button>
                  <button data-d="废弃" data-id="${t.id}">废弃</button>
                ` : (t.comment || '')}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  el.querySelectorAll('button[data-d]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/tickets/${btn.dataset.id}/decide`, {
          method: 'POST',
          body: JSON.stringify({ decision: btn.dataset.d, comment: '台上裁决' }),
        });
      } catch (e) {
        window.alert(`提交失败：${e.message}`);
        return;
      }
      await renderReview(el);
    };
  });
}
