<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const qtys = reactive<Record<number, string>>({})
const msg = ref('')
const err = ref('')
async function load() { rows.value = await api('/inventory') }
function detail(e: any): string {
  try {
    const j = JSON.parse(e?.message ?? '')
    return typeof j.detail === 'string' ? j.detail : (e?.message ?? '请求失败')
  } catch { return e?.message ?? '请求失败' }
}
async function inbound(r: any) {
  msg.value = ''; err.value = ''
  try {
    const res = await api('/inventory/inbound', {
      method: 'POST',
      body: JSON.stringify({ ingredient_id: r.id, qty: Number(qtys[r.id]) }),
    })
    qtys[r.id] = ''
    msg.value = `${res.name} 入库成功，现结存 ${res.stock_qty} ${res.unit}；最新备料单缺料已同步`
    await load()
  } catch (e: any) {
    err.value = `${r.name} 入库失败：${detail(e)}`
  }
}
onMounted(load)
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 按结存入库，保存后最新备料单缺料同步对齐</p>
  <p v-if="msg" style="margin:0 0 0.6rem"><span class="badge badge-ok">{{ msg }}</span></p>
  <p v-if="err" style="margin:0 0 0.6rem"><span class="badge badge-bad">{{ err }}</span></p>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>库存</th><th>单位</th><th>入库数量</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.stock_qty }}</td><td>{{ r.unit }}</td>
          <td><input v-model="qtys[r.id]" class="num-input" type="number" min="0" step="any" placeholder="0" /></td>
          <td><button class="btn" :disabled="!Number(qtys[r.id])" @click="inbound(r)">入库</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
