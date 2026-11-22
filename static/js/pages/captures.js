import { api } from '../api.js';

export async function renderCaptures(el) {
  const data = await api('/api/batches');
  const bins = await api('/api/bins');
  const openBin = (bins.items || []).find((b) => b.status === '开放');
  el.innerHTML = `
    <div class="card">
      <h2>抓取批次 <span class="chip ok" id="releasedTotal">已放行件数加载中…</span></h2>
      <div class="row">
        <input id="src" placeholder="来源名" />
        <input id="note" placeholder="备注" />
        <button id="create">新建批次</button>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>批号</th><th>来源</th><th>状态</th><th>条目/坏件</th><th>已放行件数</th><th>操作</th></tr></thead>
        <tbody>
          ${(data.items || []).map((b) => `
            <tr>
              <td>${b.batch_code}</td>
              <td>${b.source_name}</td>
              <td><span class="chip">${b.status}</span></td>
              <td>${b.item_count} / <span class="chip bad">${b.bad_count}</span></td>
              <td><span class="chip ok" data-released-batch="${b.id}">${b.released_count ?? 0}</span></td>
              <td class="row">
                <button data-open="${b.id}">详情</button>
                <button data-close="${b.id}">关闭</button>
                ${openBin ? `<button data-auto="${b.id}">坏件入舱</button>` : ''}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div id="detail" class="grid" style="margin-top:12px"></div>
    </div>`;

  const ledger = await api('/api/release_ledger');
  const total = ledger.summary?.released_count ?? (ledger.items || []).length;
  el.querySelector('#releasedTotal').textContent = `已放行件数 ${total}`;

  el.querySelector('#create').onclick = async () => {
    try {
      await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          source_name: el.querySelector('#src').value,
          note: el.querySelector('#note').value,
        }),
      });
    } catch (e) {
      window.alert(`提交失败：${e.message}`);
      return;
    }
    await renderCaptures(el);
  };
  el.querySelectorAll('[data-close]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/batches/${btn.dataset.close}/close`, { method: 'POST', body: '{}' });
      } catch (e) {
        window.alert(`提交失败：${e.message}`);
        return;
      }
      await renderCaptures(el);
    };
  });
  el.querySelectorAll('[data-auto]').forEach((btn) => {
    btn.onclick = async () => {
      if (!openBin) return;
      try {
        await api('/api/quarantine/auto-enter', {
          method: 'POST',
          body: JSON.stringify({ batch_id: Number(btn.dataset.auto), bin_id: openBin.id }),
        });
      } catch (e) {
        window.alert(`提交失败：${e.message}`);
        return;
      }
      await renderCaptures(el);
    };
  });
  el.querySelectorAll('[data-open]').forEach((btn) => {
    btn.onclick = async () => {
      const d = await api(`/api/batches/${btn.dataset.open}`);
      const box = el.querySelector('#detail');
      box.innerHTML = `
        <h3>${d.batch_code} 条目 · 已放行件数 <span class="chip ok">${d.released_count ?? 0}</span></h3>
        <div class="row">
          <input id="ikey" placeholder="条目键" />
          <select id="iq">
            <option>合格</option><option>缺字段</option><option>编码空</option><option>重复键</option>
          </select>
          <button id="addItem">追加条目</button>
        </div>
        <table>
          <thead><tr><th>键</th><th>质量</th><th>状态</th><th>放行落点（联验复核）</th></tr></thead>
          <tbody>
            ${(d.items || []).map((i) => `
              <tr>
                <td>${i.item_key}</td>
                <td><span class="chip ${i.quality === '合格' ? 'ok' : 'bad'}">${i.quality}</span></td>
                <td>${i.status === '已放行' ? '<span class="chip ok">已放行</span>' : i.status}</td>
                <td class="release-landing">
                  ${i.release ? `
                    <div class="landing-row">
                      <span class="muted">${i.release.channel} · ${i.release.reviewer || ''}</span>
                      <code class="fp" title="${i.release.fingerprint}">${i.release.fingerprint.slice(0, 12)}…</code>
                    </div>`
                    : '<span class="muted">未落放行落点</span>'}
                </td>
              </tr>`).join('')}
          </tbody>
        </table>`;
      box.querySelector('#addItem').onclick = async () => {
        try {
          await api(`/api/batches/${d.id}/items`, {
            method: 'POST',
            body: JSON.stringify({
              item_key: box.querySelector('#ikey').value,
              quality: box.querySelector('#iq').value,
              payload: '{}',
            }),
          });
        } catch (e) {
          window.alert(`提交失败：${e.message}`);
          return;
        }
        btn.click();
      };
    };
  });
}
