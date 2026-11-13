# 03-syncledger（双核对账）

Syncledger — 跨库/跨系统对齐对账：双端抽取 → 对齐键对账 → 差异处置 → 批次互证。

与 Feedstitch（多源 Feed 归并）、Batchgate（作业依赖编排）主链路不同。夹具全本地，不连活库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5300 |
| API | http://localhost:10300 |

## 主链

配置对账对与对齐键 → 选择主策略（全量逐行 / 抽样摘要，落全局配置，单批次只允许一种）→ 触发双端抽取并对齐 → 落差异行与批次计数 → 页面互证

## 对账主策略（full / sample）

- **全量逐行 `full`**：对左右并集的每一个对齐键逐行比对，批次状态 `completed`，是唯一可作为清账/放行依据的状态。
- **抽样摘要 `sample`**：仅作摸底，批次状态恒为 `sampled`，**永不进入放行态**（`clearance_allowed=false`）。
  - 可解释规模：`sample_size = min(cap, ceil(并集键数 × rate), 并集键数)`，公式随批次落库。
  - 可复现依据：对并集键稳定排序后按 `sha256(seed ‖ 对齐键)` 打分取前 n；种子留空则自动生成并落库，**同一种子重跑抽样摘要稳定**（命中键哈希、判定、计数一致）。
  - 摘要命中：每个抽中键落 `key_hash` 与抽样判定（一致 / 仅左有 / 仅右有 / 字段不一致）。
- **冲突闸**：同对后续发起全量复核时，与未作废抽样摸底结论冲突（`verdict_contradiction` 结论矛盾，或 `coverage_gap_clean_sample` 抽样零差异但全量在未覆盖键发现差异），抽样批次显式置 `conflicted`、结论作废降级，并回指触发的全量批次。抽样不得冒充全量。
- 模式、批次计数、冲突标记在总览 / 对账台 / 审计摘要 / 差异清单各页与接口口径一致。

## 种子对账对

- **inventory_hq_vs_store**：总部库存 ↔ 门店库存（`sku_id`+`store_id`，比对 `qty`）
- **payment_vs_ledger**：支付网关 ↔ 账务流水（`txn_id`，比对 `amount`/`currency`）
- **sku_catalog_a_vs_b**：目录 A ↔ 目录 B（`sku_code`，比对 `name`/`category`）

底座默认只**记差异、不自动盖写**；差异处置/契约/审计页留表与入口，深逻辑留给后题。侧栏不叫「工单」，避免撞禁名单「工单客服」。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现，见出题规划）

`master_slave_pick` / `side_only_policy` / `window_buffer` / `diff_disposition_flow` / `batch_idempotency` / …
