<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, putJSON } from '../api'
const settings = ref({})
const form = ref({ default_reconcile_mode: 'full', default_sample_rate: '', sample_size_cap: '' })
const err = ref('')
const ok = ref('')
const busy = ref(false)

const keyLabels = {
  default_policy: '默认处置策略',
  auto_overwrite: '自动盖写',
  default_reconcile_mode: '默认对账模式',
  default_sample_rate: '默认抽样率',
  sample_size_cap: '抽样规模上限',
}

async function load() {
  settings.value = await getJSON('/api/settings')
  form.value.default_reconcile_mode = settings.value.default_reconcile_mode || 'full'
  form.value.default_sample_rate = settings.value.default_sample_rate || ''
  form.value.sample_size_cap = settings.value.sample_size_cap || ''
}

async function save() {
  err.value = ''
  ok.value = ''
  busy.value = true
  try {
    settings.value = await putJSON('/api/settings', {
      default_reconcile_mode: form.value.default_reconcile_mode,
      default_sample_rate: String(form.value.default_sample_rate),
      sample_size_cap: String(form.value.sample_size_cap),
    })
    ok.value = '已落配置：一次批次只允许一种主策略。'
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try { await load() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>设置</h1>
    <p class="muted">
      全局策略键值。自动盖写默认关闭；对账主策略在「全量逐行 full / 抽样摘要 sample」间切换，
      切换落库后作为后续批次的默认模式，单批次仍可在对账台显式指定。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="ok" class="tag ok">{{ ok }}</p>

    <div class="panel">
      <h3 style="margin-top:0">对账模式与抽样参数</h3>
      <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end">
        <label>
          默认对账模式
          <select v-model="form.default_reconcile_mode" style="display:block;margin-top:0.25rem;min-width:12rem">
            <option value="full">全量逐行 full（可清账）</option>
            <option value="sample">抽样摘要 sample（仅摸底，不可放行）</option>
          </select>
        </label>
        <label>
          默认抽样率（0 &lt; rate ≤ 1）
          <input v-model="form.default_sample_rate" type="number" step="0.05" min="0.01" max="1"
                 style="display:block;width:10rem;margin-top:0.25rem" />
        </label>
        <label>
          抽样规模上限 cap
          <input v-model="form.sample_size_cap" type="number" min="1"
                 style="display:block;width:9rem;margin-top:0.25rem" />
        </label>
        <button :disabled="busy" @click="save">{{ busy ? '保存中…' : '保存到配置' }}</button>
      </div>
      <p class="muted" style="margin-bottom:0">
        抽样规模 = min(cap, ceil(并集键数 × rate), 并集键数)；种子在对账台指定或自动生成，同 seed 重跑稳定。
      </p>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">全部配置项</h3>
      <table>
        <thead><tr><th>键</th><th>含义</th><th>值</th></tr></thead>
        <tbody>
          <tr v-for="(v, k) in settings" :key="k">
            <td class="mono">{{ k }}</td>
            <td>{{ keyLabels[k] || '—' }}</td>
            <td class="mono">{{ v }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
