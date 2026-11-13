<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'

const route = useRoute()
const rows = ref([])
const batches = ref([])
const err = ref('')
const kindClass = { left_only: 'warn', right_only: 'warn', field_mismatch: 'danger' }
const kindLabel = { left_only: '仅左有', right_only: '仅右有', field_mismatch: '字段不一致' }
const modeLabel = { full: '全量逐行', sample: '抽样摸底' }

const batchMap = computed(() => Object.fromEntries(batches.value.map((b) => [b.id, b])))

async function refresh() {
  const q = route.query.batch_id ? `?batch_id=${route.query.batch_id}` : ''
  rows.value = await getJSON(`/api/diffs${q}`)
  batches.value = await getJSON('/api/batches?limit=100')
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
watch(() => route.query.batch_id, async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>差异清单</h1>
    <p class="muted">
      对齐后的差异行。底座只记账；主从盖写、忽略规则、严重级别闸留给后题。
      <span v-if="route.query.batch_id">当前过滤批次 #{{ route.query.batch_id }}</span>
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr><th>ID</th><th>批次 / 模式</th><th>类型</th><th>对齐键</th><th>不一致字段</th><th>左</th><th>右</th></tr>
        </thead>
        <tbody>
          <tr v-for="d in rows" :key="d.id">
            <td>{{ d.id }}</td>
            <td>
              #{{ d.batch_id }}
              <span class="tag" :class="batchMap[d.batch_id]?.mode === 'sample' ? 'warn' : ''">
                {{ modeLabel[batchMap[d.batch_id]?.mode] || '—' }}
              </span>
              <span v-if="batchMap[d.batch_id]?.status === 'conflicted'" class="tag danger">已作废</span>
            </td>
            <td><span class="tag" :class="kindClass[d.kind]">{{ kindLabel[d.kind] || d.kind }}</span></td>
            <td class="mono">{{ JSON.stringify(d.align_key) }}</td>
            <td class="mono">{{ (d.mismatched_fields || []).join(', ') || '—' }}</td>
            <td class="mono">{{ d.left ? JSON.stringify(d.left) : '—' }}</td>
            <td class="mono">{{ d.right ? JSON.stringify(d.right) : '—' }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="muted">暂无差异。去对账台跑一趟后回到这里。</td></tr>
        </tbody>
      </table>
      <p v-if="rows.some((d) => batchMap[d.batch_id]?.mode === 'sample')" class="muted" style="margin-bottom:0">
        注：抽样批次的差异仅覆盖抽中的对齐键，不代表全量结论，不得据此放行。
      </p>
    </div>
  </div>
</template>
