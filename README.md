# cc-quarantine-lab

CC_Codex 二期（26.11）**数据工程**产品线：**抓取隔离舱检疫台**（Pyramid + Waitress + 原生 JS SPA 右侧抽屉 + SQLite）。

## 一句话骨架

**抓取批次 → 坏件入隔离舱 → 复核放行 / 回炉重抓 → 隔离对账**

与血缘影响、压实合并、回灌切片、契约换版、水印盖印、清单闭合、留存裁撤**正交**；不做 CDC 游标 / Feed 归并 / Slicegate 类指纹。

## 领域

- **所属领域**：数据工程
- **子方向偏采集**：源站抓取结果检疫、坏件隔离、回炉重抓、隔离对账

## 页面（≥8）

1. 抓取批次 2. 隔离舱 3. 复核放行 4. 回炉队列 5. 隔离对账  
6. 源站名册 7. 入舱规则 8. 审计轨迹 9. 台参数

## 放行链路（quarantine-bug-02 收口）

工程形态敲定：**旁路切流账册（单轨）**，不启用双写两轨。

- `release_ledger` 只追加账册：放行当刻写入条目键与放行指纹（SHA-256，按当刻不可变字段计算），
  表上触发器禁 UPDATE/DELETE（禁回刷），`ticket_id/row_id/item_id` 三列 UNIQUE 兜底排他；
- 复核放行走 `BEGIN IMMEDIATE` + 条件认领，两名仓管同抢同一复核单仅一人成功，写败返回中文说明；
- 抓取侧改读放行新旗：放行后 `capture_items.status` 翻「已放行」，批次详情/列表带已放行件数与逐条落点；
- 清洗编排闸门 `gate_status`：无落点按待复核拦截，指纹拧花即挡（对账报告带 `gate_blocked` 与被挡条目）；
- 四屏分开亮：放行徽标（复核页）、已放行件数（抓取页/舱页）、放行落点行（复核页/抓取页/设置页只读账册）；
- 台参数 `release_read_track=切流账册` 为只读口径，接口拒绝改写；审计页挂舱位摘要。

## 本地

http://127.0.0.1:7500/login · **admin / 123456** · 端口 **7500**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
python run.py
```

## 预留切口（未做）

入舱半失败闭、复核与回炉二选一命运等，出题可切。
（并发争抢写锁、放行落点与对账指纹拦截已由 release_ledger 收口，不再是预留切口。）
