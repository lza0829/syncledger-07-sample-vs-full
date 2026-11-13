<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'

const route = useRoute()
const batches = ref([])
const batchId = ref(null)
const summary = ref(null)
const err = ref('')

const modeLabel = { full: '全量逐行', sample: '抽样摸底' }
const kindLabel = {
  matched: '一致',
  left_only: '仅左有',
  right_only: '仅右有',
  field_mismatch: '字段不一致',
}
const reasonLabel = {
  verdict_contradiction: '结论矛盾（同键判定不一致）',
  coverage_gap_clean_sample: '覆盖缺口（抽样零差异，全量在未抽中键发现差异）',
}

async function loadBatches() {
  batches.value = await getJSON('/api/batches?limit=30')
  if (route.query.batch_id) batchId.value = Number(route.query.batch_id)
  else if (!batchId.value && batches.value.length) batchId.value = batches.value[0].id
}

async function loadSummary() {
  summary.value = null
  if (!batchId.value) return
  summary.value = await getJSON(`/api/audit/batches/${batchId.value}`)
}

onMounted(async () => {
  try {
    await loadBatches()
    await loadSummary()
  } catch (e) { err.value = String(e.message || e) }
})
watch(batchId, async () => {
  try { await loadSummary() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>审计摘要</h1>
    <p class="muted">
      按批次查看快照计数。抽样批次只作摸底、永远不可放行；与后续全量复核冲突的抽样批次已作废降级。
      导出包与清单哈希留给后题；当前 export_ready=false。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <label>
        批次
        <select v-model.number="batchId" style="display:block;margin-top:0.35rem;min-width:24rem">
          <option v-for="b in batches" :key="b.id" :value="b.id">
            {{ b.batch_no }} · {{ b.pair_title }} · {{ modeLabel[b.mode] || b.mode }} · {{ b.status }}
          </option>
        </select>
      </label>
    </div>
    <div class="panel" v-if="summary">
      <p>
        批次 <span class="mono">{{ summary.batch.batch_no }}</span> · {{ summary.pair?.title }} ·
        <span class="tag">{{ modeLabel[summary.mode] }}（{{ summary.mode }}）</span>
      </p>

      <div class="conflict-box" v-if="summary.batch.conflicted">
        <h3 style="margin:0.2rem 0">冲突标记：抽样摸底结论已作废/降级</h3>
        <p style="margin:0.3rem 0">
          由全量批次
          <span class="mono">{{ summary.batch.conflict_detail.full_batch_no }}</span>
          （#{{ summary.batch.conflict_detail.full_batch_id }}）触发，
          冲突键 {{ summary.batch.conflict_detail.conflict_count }} 个，
          处置 <span class="mono">{{ summary.batch.conflict_detail.resolution }}</span>。
        </p>
        <table>
          <thead><tr><th>对齐键</th><th>冲突类型</th><th>抽样判定</th><th>全量判定</th></tr></thead>
          <tbody>
            <tr v-for="(c, i) in summary.batch.conflict_detail.conflicting_keys" :key="i">
              <td class="mono">{{ JSON.stringify(c.align_key) }}</td>
              <td>{{ reasonLabel[c.reason] || c.reason }}</td>
              <td>{{ c.scout_verdict ? kindLabel[c.scout_verdict] || c.scout_verdict : '未覆盖' }}</td>
              <td><span class="tag danger">{{ kindLabel[c.full_verdict] || c.full_verdict }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="sample-box" v-if="summary.mode === 'sample' && summary.batch.sample_meta">
        <h3 style="margin:0.2rem 0">抽样依据（可解释 / 可复现）</h3>
        <table>
          <tbody>
            <tr><th style="width:11rem">抽样种子</th><td class="mono">{{ summary.batch.sample_meta.seed }}</td></tr>
            <tr><th>抽样率 / 上限</th><td class="mono">{{ summary.batch.sample_meta.rate }} / cap={{ summary.batch.sample_meta.cap }}</td></tr>
            <tr><th>总体（并集键数）</th><td class="mono">{{ summary.batch.sample_meta.population }}</td></tr>
            <tr><th>抽样规模与公式</th><td class="mono">{{ summary.batch.sample_meta.sample_size }} ＝ {{ summary.batch.sample_meta.size_formula }}</td></tr>
          </tbody>
        </table>
      </div>

      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ summary.diff_count }}</div><div class="stat-label">差异行</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.left_only }}</div><div class="stat-label">仅左有</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.right_only }}</div><div class="stat-label">仅右有</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.field_mismatch }}</div><div class="stat-label">字段不一致</div></div>
      </div>

      <p style="margin-top:0.85rem" class="muted">{{ summary.note }}</p>
      <p>
        放行态：
        <span class="tag" :class="summary.clearance_allowed ? 'ok' : 'danger'">
          {{ summary.clearance_allowed ? '全量完成，可清账' : '不可放行（抽样/已作废）' }}
        </span>
      </p>
      <p>可导出 <span class="tag" :class="summary.export_ready ? 'ok' : 'warn'">{{ summary.export_ready ? '是' : '否' }}</span></p>
    </div>
  </div>
</template>
