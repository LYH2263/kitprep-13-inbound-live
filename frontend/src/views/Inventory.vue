<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const ingredientId = ref<number | null>(null)
const qty = ref<string>('')
const saving = ref(false)
const error = ref('')
const notice = ref('')

async function load() {
  rows.value = await api('/inventory')
}
async function save() {
  error.value = ''; notice.value = ''
  const q = Number(qty.value)
  if (!ingredientId.value) { error.value = '请选择原料'; return }
  if (!qty.value.trim() || Number.isNaN(q)) { error.value = '请填写入库数量'; return }
  if (q <= 0) { error.value = '入库数量必须为正数'; return }
  saving.value = true
  try {
    const res = await api('/inventory/inbound', {
      method: 'POST',
      body: JSON.stringify({ lines: [{ ingredient_id: ingredientId.value, qty: q }] }),
    })
    rows.value = res.inventory
    qty.value = ''
    notice.value = '入库已保存：库存结存、最新备料单缺料、缺料贴张数已同步对齐'
  } catch (e: any) {
    error.value = e?.message || '入库失败'
  } finally {
    saving.value = false
  }
}
onMounted(load)
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 结存可直接入库</p>
  <div class="card" style="margin-bottom:1rem;max-width:520px">
    <h2 style="margin:0 0 0.6rem;font-size:1rem">入库</h2>
    <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
      <select v-model.number="ingredientId" style="flex:1;min-width:180px">
        <option :value="null" disabled>选择原料</option>
        <option v-for="r in rows" :key="r.id" :value="r.id">{{ r.code }} · {{ r.name }}</option>
      </select>
      <input v-model="qty" type="number" step="0.001" min="0" placeholder="数量（正数）"
             style="width:150px" @keyup.enter="save" />
      <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '入库保存' }}</button>
    </div>
    <p v-if="error" style="color:var(--kp-bad,#b33a2b);font-size:0.82rem;margin:0.5rem 0 0">{{ error }}</p>
    <p v-if="notice" style="color:var(--kp-ok,#2f6b3a);font-size:0.82rem;margin:0.5rem 0 0">{{ notice }}</p>
  </div>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>结存</th><th>单位</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)"><td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.stock_qty }}</td><td>{{ r.unit }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
