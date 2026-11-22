import { api } from '../api.js';

export async function renderSettings(el) {
  const data = await api('/api/settings');
  const items = data.items || [];
  el.innerHTML = `
    <div class="card">
      <h2>台参数</h2>
      <table>
        <thead><tr><th>项</th><th>说明</th><th>值</th><th></th></tr></thead>
        <tbody>
          ${items.map((s) => `
            <tr>
              <td>${s.key}${s.readonly ? ' <span class="chip ok">只读</span>' : ''}</td>
              <td>${s.label}</td>
              <td>
                ${s.readonly
                  ? `<input data-key="${s.key}" value="${s.value}" disabled />`
                  : `<input data-key="${s.key}" value="${s.value}" />`}
              </td>
              <td>${s.readonly
                ? '<span class="muted">放行口径锁定，禁止修改</span>'
                : `<button data-save="${s.key}">保存</button>`}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  el.querySelectorAll('[data-save]').forEach((btn) => {
    btn.onclick = async () => {
      const input = el.querySelector(`input[data-key="${btn.dataset.save}"]`);
      try {
        await api('/api/settings/update', {
          method: 'POST',
          body: JSON.stringify({ key: btn.dataset.save, value: input.value }),
        });
      } catch (e) {
        window.alert(`保存失败：${e.message}`);
        return;
      }
      await renderSettings(el);
    };
  });

  // 只读放行落点账册：只展示切流账册内容，不提供任何写操作
  const ledger = await api('/api/release_ledger');
  const rows = ledger.items || [];
  const summary = ledger.summary || {};
  el.innerHTML += `
    <div class="card" style="margin-top:1rem">
      <h3>放行落点（只读账册）
        <span class="chip ok">已放行件数 ${summary.released_count ?? rows.length}</span>
        <span class="chip ${summary.blocked_count ? 'bad' : 'ok'}">指纹拦截 ${summary.blocked_count ?? 0}</span>
      </h3>
      <p class="muted">读轨口径：切流账册，只追加、禁回刷；指纹拧花的件由清洗编排拦截。</p>
      <table>
        <thead><tr><th>落点</th><th>条目键</th><th>渠道</th><th>仓管</th><th>放行指纹</th><th>落账时刻</th></tr></thead>
        <tbody>
          ${rows.map((r) => `
            <tr>
              <td>#${r.id}</td>
              <td>${r.item_key}</td>
              <td><span class="chip">${r.channel}</span></td>
              <td>${r.reviewer || ''}</td>
              <td><code class="fp" title="${r.fingerprint}">${r.fingerprint}</code></td>
              <td>${r.created_at}</td>
            </tr>`).join('') || '<tr><td colspan="6" class="muted">暂无放行落点</td></tr>'}
        </tbody>
      </table>
    </div>`;
}
