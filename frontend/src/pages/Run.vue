<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJSON, postJSON, putJSON } from '../api'

const pairs = ref([])
const batches = ref([])
const settings = ref({})
const pairId = ref(null)
const note = ref('')
const mode = ref('full')
const seedInput = ref('')
const rateInput = ref('')
const capInput = ref('')
const last = ref(null)
const busy = ref(false)
const err = ref('')

const modeLabel = { full: '全量逐行', sample: '抽样摸底' }
const statusMeta = {
  completed: { cls: 'ok', text: '全量完成·可清账' },
  sampled: { cls: 'warn', text: '抽样摸底·不可放行' },
  conflicted: { cls: 'danger', text: '冲突已作废·不可放行' },
}

async function refresh() {
  pairs.value = await getJSON('/api/pairs')
  batches.value = await getJSON('/api/batches?limit=20')
  settings.value = await getJSON('/api/settings')
  if (pairId.value == null && pairs.value.length) pairId.value = pairs.value[0].id
  if (!rateInput.value) rateInput.value = settings.value.default_sample_rate
  if (!capInput.value) capInput.value = settings.value.sample_size_cap
  mode.value = settings.value.default_reconcile_mode || 'full'
}

async function switchMode(next) {
  const previous = mode.value
  mode.value = next
  busy.value = true
  err.value = ''
  try {
    settings.value = await putJSON('/api/settings', { default_reconcile_mode: next })
  } catch (e) {
    mode.value = previous
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function run() {
  err.value = ''
  busy.value = true
  const body = {
    pair_id: Number(pairId.value),
    note: note.value || null,
    mode: mode.value,
  }
  if (mode.value === 'sample') {
    body.sample_seed = seedInput.value.trim() || null
    body.sample_rate = Number(rateInput.value)
    body.sample_cap = Number(capInput.value)
  }
  try {
    last.value = await postJSON('/api/reconcile', body)
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

const lastStatus = computed(() =>
  last.value ? statusMeta[last.value.status] || { cls: '', text: last.value.status } : null)

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>对账台</h1>
    <p class="muted">
      一次批次只允许一种主策略：<b>全量逐行</b>可作为清账依据；<b>抽样摸底</b>仅用于快速摸底，
      不可标记为对账已清/放行。模式切换落全局配置。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>

    <div class="panel">
      <h3 style="margin-top:0">对账主策略（写入配置 default_reconcile_mode）</h3>
      <div class="mode-switch" role="group" aria-label="对账模式">
        <button
          :class="['mode-btn', { active: mode === 'full' }]"
          :disabled="busy"
          @click="switchMode('full')"
        >全量逐行 full</button>
        <button
          :class="['mode-btn', { active: mode === 'sample' }]"
          :disabled="busy"
          @click="switchMode('sample')"
        >抽样摘要 sample</button>
      </div>
      <p class="muted" style="margin-bottom:0">
        当前默认模式：<span class="tag">{{ modeLabel[mode] }}（{{ mode }}）</span>
      </p>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">发起对账（单批次单模式）</h3>
      <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end">
        <label>
          对账对
          <select v-model.number="pairId" style="display:block;min-width:18rem;margin-top:0.25rem">
            <option v-for="p in pairs" :key="p.id" :value="p.id">{{ p.title }}</option>
          </select>
        </label>
        <label>
          备注（可选）
          <input v-model="note" style="display:block;width:14rem;margin-top:0.25rem" placeholder="本趟说明" />
        </label>
      </div>

      <div v-if="mode === 'sample'" class="sample-box">
        <h4 style="margin:0.6rem 0 0.35rem">抽样参数（可复现）</h4>
        <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end">
          <label>
            抽样种子 seed（留空则随机生成并落库）
            <input v-model="seedInput" style="display:block;width:16rem;margin-top:0.25rem"
                   placeholder="同一种子重跑结果稳定" />
          </label>
          <label>
            抽样率 rate（0 &lt; rate ≤ 1）
            <input v-model="rateInput" type="number" step="0.05" min="0.01" max="1"
                   style="display:block;width:8rem;margin-top:0.25rem" />
          </label>
          <label>
            规模上限 cap
            <input v-model="capInput" type="number" min="1"
                   style="display:block;width:7rem;margin-top:0.25rem" />
          </label>
        </div>
        <p class="muted" style="margin:0.5rem 0 0">
          抽样规模 = min(cap, ceil(并集键数 × rate), 并集键数)；
          命中键由 sha256(seed ‖ 对齐键) 排序决定，同 seed 重跑抽样摘要稳定。
        </p>
      </div>
      <div v-else class="sample-box" style="border-color:var(--line)">
        <p class="muted" style="margin:0.4rem 0">全量模式：对左右并集的每一个对齐键逐行比对，结论可作为清账/放行依据。</p>
      </div>

      <div style="margin-top:0.75rem">
        <button :disabled="busy || !pairId" @click="run">
          {{ busy ? '对账中…' : `按「${modeLabel[mode]}」跑一批` }}
        </button>
        <span v-if="mode === 'sample'" class="tag warn" style="margin-left:0.6rem">
          抽样批次仅为摸底，不会进入放行态
        </span>
      </div>
    </div>

    <div class="panel" v-if="last">
      <h3 style="margin-top:0">最近一趟</h3>
      <p>
        批次 <span class="mono">{{ last.batch_no }}</span> · {{ last.pair_title }} ·
        <span class="tag">{{ modeLabel[last.mode] }}（{{ last.mode }}）</span>
        <span class="tag" :class="lastStatus.cls" style="margin-left:0.4rem">{{ lastStatus.text }}</span>
      </p>

      <div v-if="last.mode === 'sample' && last.sample_meta" class="sample-box">
        <h4 style="margin:0.3rem 0">抽样依据（可解释 / 可复现）</h4>
        <table>
          <tbody>
            <tr><th style="width:11rem">抽样种子</th><td class="mono">{{ last.sample_meta.seed }}</td></tr>
            <tr><th>抽样率 / 上限</th><td class="mono">{{ last.sample_meta.rate }} / cap={{ last.sample_meta.cap }}</td></tr>
            <tr><th>总体（并集键数）</th><td class="mono">{{ last.sample_meta.population }}</td></tr>
            <tr><th>抽样规模与公式</th><td class="mono">{{ last.sample_meta.sample_size }} ＝ {{ last.sample_meta.size_formula }}</td></tr>
            <tr><th>放行</th><td><span class="tag danger">不可放行（scout only）</span></td></tr>
          </tbody>
        </table>
        <h4 style="margin:0.6rem 0 0.3rem">摘要命中（{{ last.sample_meta.sampled_keys.length }} 个键）</h4>
        <table>
          <thead><tr><th>对齐键</th><th>键哈希 sha256 前 16 位</th><th>抽样判定</th></tr></thead>
          <tbody>
            <tr v-for="(k, i) in last.sample_meta.sampled_keys" :key="i">
              <td class="mono">{{ JSON.stringify(k.align_key) }}</td>
              <td class="mono">{{ k.key_hash }}</td>
              <td>
                <span class="tag" :class="k.verdict === 'matched' ? 'ok' : 'danger'">
                  {{ { matched: '抽样一致', left_only: '仅左有', right_only: '仅右有', field_mismatch: '字段不一致' }[k.verdict] }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="last.sample_conflicts && last.sample_conflicts.conflict_count" class="conflict-box">
        <h4 style="margin:0.3rem 0">全量复核与历史抽样摸底冲突（抽样结论已作废/降级）</h4>
        <p style="margin:0.3rem 0">
          检查历史抽样批次 {{ last.sample_conflicts.checked_scout_batches }} 个，
          作废 {{ last.sample_conflicts.conflicted_batches.length }} 个，
          冲突键 {{ last.sample_conflicts.conflict_count }} 个。
        </p>
        <table>
          <thead><tr><th>作废抽样批次</th><th>冲突键数</th><th>冲突类型</th></tr></thead>
          <tbody>
            <tr v-for="c in last.sample_conflicts.conflicted_batches" :key="c.batch_id">
              <td class="mono">{{ c.batch_no }}（#{{ c.batch_id }}）</td>
              <td>{{ c.conflict_count }}</td>
              <td class="mono">{{ (c.reasons || []).join(', ') }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="stat-grid" style="margin-top:0.75rem">
        <div class="stat"><div class="stat-num">{{ last.matched }}</div><div class="stat-label">一致</div></div>
        <div class="stat"><div class="stat-num">{{ last.left_only }}</div><div class="stat-label">仅左有</div></div>
        <div class="stat"><div class="stat-num">{{ last.right_only }}</div><div class="stat-label">仅右有</div></div>
        <div class="stat"><div class="stat-num">{{ last.field_mismatch }}</div><div class="stat-label">字段不一致</div></div>
        <div class="stat"><div class="stat-num">{{ last.diff_total }}</div><div class="stat-label">差异合计</div></div>
      </div>
      <p style="margin-top:0.75rem">
        <router-link :to="{ path: '/diffs', query: { batch_id: last.id } }">查看本批差异 →</router-link>
        ·
        <router-link :to="{ path: '/audit', query: { batch_id: last.id } }">审计摘要 →</router-link>
      </p>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">历史批次（模式 / 批次计数 / 冲突标记口径一致）</h3>
      <table>
        <thead>
          <tr>
            <th>批次</th><th>对账对</th><th>模式</th><th>状态</th>
            <th>左/右行</th><th>抽样规模</th><th>种子</th>
            <th>一致</th><th>仅左</th><th>仅右</th><th>字段差</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td class="mono">{{ b.batch_no }}</td>
            <td>{{ b.pair_title }}</td>
            <td><span class="tag">{{ modeLabel[b.mode] || b.mode }}</span></td>
            <td><span class="tag" :class="(statusMeta[b.status] || { cls: '' }).cls">
              {{ (statusMeta[b.status] || { text: b.status }).text }}
            </span></td>
            <td class="mono">{{ b.left_rows }} / {{ b.right_rows }}</td>
            <td class="mono">{{ b.sample_size ?? '—' }}<span v-if="b.sample_population != null"> / {{ b.sample_population }}</span></td>
            <td class="mono">{{ b.sample_seed || '—' }}</td>
            <td>{{ b.matched }}</td>
            <td>{{ b.left_only }}</td>
            <td>{{ b.right_only }}</td>
            <td>{{ b.field_mismatch }}</td>
            <td class="mono">{{ b.created_at }}</td>
          </tr>
          <tr v-if="!batches.length"><td colspan="12" class="muted">还没有批次，先跑一趟。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
