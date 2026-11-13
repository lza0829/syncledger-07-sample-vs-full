<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const stats = ref(null)
const err = ref('')
onMounted(async () => {
  try { stats.value = await getJSON('/api/dashboard') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>总览</h1>
    <p class="muted">跨库对齐对账：双端抽取、对齐键匹配、差异记账（默认不自动盖写）。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="stats">
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ stats.pair_count }}</div><div class="stat-label">对账对</div></div>
        <div class="stat"><div class="stat-num">{{ stats.enabled_pairs }}</div><div class="stat-label">已启用</div></div>
        <div class="stat"><div class="stat-num">{{ stats.batch_count }}</div><div class="stat-label">对账批次</div></div>
        <div class="stat"><div class="stat-num">{{ stats.full_batch_count }}</div><div class="stat-label">全量批次</div></div>
        <div class="stat"><div class="stat-num">{{ stats.sample_batch_count }}</div><div class="stat-label">抽样批次（摸底）</div></div>
        <div class="stat"><div class="stat-num" :style="stats.conflicted_batch_count ? 'color:var(--danger)' : ''">{{ stats.conflicted_batch_count }}</div><div class="stat-label">冲突已作废</div></div>
        <div class="stat"><div class="stat-num">{{ stats.diff_count }}</div><div class="stat-label">差异行</div></div>
        <div class="stat"><div class="stat-num">{{ stats.open_dispositions }}</div><div class="stat-label">未关处置单</div></div>
      </div>
      <p style="margin-top:1rem">
        默认主策略 <span class="tag">{{ stats.default_mode === 'sample' ? '抽样摘要 sample（不可放行）' : '全量逐行 full（可清账）' }}</span>
        ，处置策略 <span class="tag">{{ stats.policy }}</span>（只记差异，不盖写两端）
      </p>
      <p class="muted" style="margin-bottom:0">
        抽样批次只能摸底、永不进入放行态；后续同对全量复核与其结论冲突时，抽样批次显式作废降级。
      </p>
      <p><router-link to="/run">去对账台切换模式并跑一趟 →</router-link></p>
    </div>
  </div>
</template>
