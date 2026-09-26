<template>
  <section class="page" data-module="contract">
    <header class="page-head">
      <div>
        <h2>委托合同管理</h2>
        <p class="page-desc">维护委托检验合同，围绕合同编号、委托单位、联系人、样品数量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记委托检验合同</button>
        <button class="btn" type="button" @click="exportRows">导出委托合同清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>处理结果</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">
              {{ resultOf(row)?.处理结果 || '处理 / 查看详情' }}
            </button>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无委托合同数据，可先登记委托检验合同</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条委托合同记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 处理结果详情/提交：每次打开都重新拉取同一条 entry，避免残留旧提示 -->
    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <header class="modal-head">
          <h3>委托检验合同处理结果 · {{ detail['合同编号'] }}</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>

        <dl class="detail-grid">
          <div><dt>委托单位</dt><dd>{{ detail['委托单位'] || '—' }}</dd></div>
          <div><dt>联系人</dt><dd>{{ detail['联系人'] || '—' }}</dd></div>
          <div><dt>合同状态</dt><dd>{{ detail.status || '—' }}</dd></div>
          <div><dt>当前版本</dt><dd>v{{ Number(detail.revision ?? 0) }}</dd></div>
        </dl>

        <!-- 当前唯一有效的处理结果：列表与详情读的是同一条数据 -->
        <section class="result-block">
          <h4>当前处理结果</h4>
          <div v-if="currentResult" class="result-current">
            <p><strong>{{ currentResult['处理结果'] }}</strong><span class="result-meta">检验员：{{ currentResult['检验员'] || '—' }} · {{ currentResult['处理时间'] }}</span></p>
            <p class="result-remark">{{ currentResult['备注'] || '（无备注）' }}</p>
          </div>
          <p v-else class="empty-state">尚无处理结果，请在下方提交；每份合同仅保留一份有效结果。</p>
        </section>

        <form class="result-form" @submit.prevent="submitResult(false)">
          <h4>提交处理结果</h4>
          <label class="form-item">
            <span>判定结论</span>
            <select v-model="form.conclusion">
              <option value="" disabled>请选择处理结果</option>
              <option v-for="opt in outcomes" :key="opt" :value="opt">{{ opt }}</option>
            </select>
          </label>
          <label class="form-item">
            <span>检验员</span>
            <input v-model="form.inspector" placeholder="处理人姓名" />
          </label>
          <label class="form-item form-item-full">
            <span>处理备注</span>
            <textarea v-model="form.remark" rows="2" placeholder="处理说明（选填）"></textarea>
          </label>

          <!-- 冲突比对：把冲突前后两条处理记录放在一起，先确认是否来自同一来源 -->
          <section v-if="conflict" class="conflict-block">
            <p class="conflict-title">检测到更新的处理结果，请核对以下两条记录（同一委托单位/合同）后选择：</p>
            <div class="conflict-grid">
              <article class="conflict-col conflict-old">
                <h5>你刚提交（版本已过期 · 冲突前）</h5>
                <p><strong>{{ conflict.submitted?.['处理结果'] }}</strong></p>
                <p>检验员：{{ conflict.submitted?.['检验员'] || '—' }}</p>
                <p>{{ conflict.submitted?.['备注'] || '（无备注）' }}</p>
              </article>
              <article class="conflict-col conflict-new">
                <h5>服务器最新（v{{ conflict.serverRevision }} · 冲突后）</h5>
                <p><strong>{{ conflict.current?.['处理结果'] }}</strong></p>
                <p>检验员：{{ conflict.current?.['检验员'] || '—' }} · {{ conflict.current?.['处理时间'] }}</p>
                <p>{{ conflict.current?.['备注'] || '（无备注）' }}</p>
              </article>
            </div>
            <p class="conflict-actions">
              <button class="btn primary" type="button" @click="submitResult(true)">确认用我的结果覆盖</button>
              <button class="btn" type="button" @click="dismissConflict">保留服务器结果，放弃本次</button>
            </p>
          </section>

          <p v-if="formMessage" :class="formOk ? 'ok-text' : 'error-text'">{{ formMessage }}</p>

          <div class="form-actions" v-if="!conflict">
            <button class="btn primary" type="submit" :disabled="submitting">{{ submitting ? '提交中…' : '提交处理结果' }}</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type ResultRecord = {
  处理结果?: string
  备注?: string
  检验员?: string
  clientToken?: string
  revision?: number
  处理时间?: string
} | null
type Row = Record<string, string | number | null> & {
  revision?: number
  处理结果?: ResultRecord
}

const ENDPOINT = '/api/contract'
const columns = ["合同编号", "委托单位", "联系人", "样品数量", "检测项目", "合同金额", "签约日期", "合同状态"]
const actions = ["签约合同", "终止合同", "确认完成"]
const statuses = ["待签约", "执行中", "已完成", "已终止"]
const outcomes = ["合格", "不合格", "退回补充"]
const stats = [{"label": "待签约合同", "value": 0}, {"label": "执行中合同", "value": 0}, {"label": "本月完成", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 详情与处理结果
const detail = ref<Row | null>(null)
const submitting = ref(false)
const formMessage = ref('')
const formOk = ref(false)
const form = ref({ conclusion: '', inspector: '', remark: '' })
// 本次表单会话的幂等令牌：弹窗打开时生成一次，重复点击/重试都属于同一来源。
const clientToken = ref('')
// 409 冲突时暂存的「前一条(刚提交)/后一条(服务器最新)」两条记录
const conflict = ref<{ submitted: ResultRecord; current: ResultRecord; serverRevision: number } | null>(null)

const currentResult = computed<ResultRecord>(() => {
  const r = detail.value?.处理结果
  return r && typeof r === 'object' ? (r as ResultRecord) : null
})

function resultOf(row: Row): ResultRecord {
  const r = row.处理结果
  return r && typeof r === 'object' ? (r as ResultRecord) : null
}

function makeToken() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${crypto.randomUUID()}-${Date.now()}`
  }
  return `t-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '委托检验合同登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('委托合同动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '委托合同操作失败'
  }
}

async function openDetail(row: Row) {
  formMessage.value = ''
  formOk.value = false
  conflict.value = null
  form.value = { conclusion: '', inspector: '', remark: '' }
  // 同一来源令牌只在「一次填写会话」内复用，保证重复提交可被幂等拦截。
  clientToken.value = makeToken()
  await loadDetail(Number(row.id))
}

async function loadDetail(id: number) {
  // 每次都拉取单条最新 entry：详情、列表、提交回写共用同一份数据，避免旧提示残留。
  const response = await request(`${ENDPOINT}/${id}`)
  if (!response.ok) {
    errorMessage.value = '委托检验合同详情读取失败'
    detail.value = null
    return
  }
  detail.value = (await response.json()) as Row
}

function closeDetail() {
  detail.value = null
  conflict.value = null
}

async function dismissConflict() {
  conflict.value = null
  formMessage.value = ''
  // 放弃覆盖：以服务器结果为准，重新拉取，保证详情回到唯一有效状态。
  if (detail.value) {
    await loadDetail(Number(detail.value.id))
  }
}

async function submitResult(force: boolean) {
  if (!detail.value) return
  if (!force && !form.value.conclusion) {
    formOk.value = false
    formMessage.value = '请选择处理结果后再提交'
    return
  }
  submitting.value = true
  formMessage.value = ''
  try {
    // 确认覆盖是一次新的写入意图，使用一次性覆盖令牌，避免与被覆盖的旧结果
    // 共用 clientToken 而在网络重试时被误判为「重复提交」、回退到旧结果。
    const token = force ? `${clientToken.value}::override::${makeToken()}` : clientToken.value
    const values: Record<string, unknown> = {
      处理结果: form.value.conclusion,
      检验员: form.value.inspector,
      备注: form.value.remark,
      // 以详情当前版本为基准提交；冲突后确认覆盖时同样带上最新版本。
      revision: Number(detail.value.revision ?? 0),
      clientToken: token,
      force,
    }
    const response = await request(`${ENDPOINT}/${detail.value.id}/result`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = (await response.json().catch(() => ({}))) as Record<string, any>

    if (response.status === 409 || payload.conflict) {
      // 冲突：把前后两条记录并排展示，交给用户先比对、再决定覆盖与否，不静默改写。
      conflict.value = {
        submitted: (payload.submitted as ResultRecord) ?? null,
        current: (payload.current as ResultRecord) ?? null,
        serverRevision: Number(payload.serverRevision ?? 0),
      }
      formOk.value = false
      formMessage.value = payload.message || '处理结果已被他人更新，请确认是否覆盖'
      return
    }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '处理结果提交失败')
    }

    // 成功（含幂等重复、确认覆盖）：直接用返回的同一条 entry 回写详情，并刷新列表，
    // 两边因此始终是同一份处理结果，不会多出记录。
    detail.value = (payload.entry as Row) ?? detail.value
    await reload()
    formOk.value = true
    formMessage.value = payload.message || '处理结果已提交'
    conflict.value = null
    if (!force) {
      form.value = { conclusion: '', inspector: '', remark: '' }
      clientToken.value = makeToken()
    }
  } catch (error) {
    formOk.value = false
    formMessage.value = error instanceof Error ? error.message : '处理结果提交失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('委托检验合同列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '委托合同列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
  z-index: 50;
}
.modal-card {
  width: min(720px, 100%);
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 20px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.modal-head h3 { margin: 0; font-size: 16px; }
.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin: 14px 0;
}
.detail-grid dt { font-size: 12px; color: var(--muted); }
.detail-grid dd { margin: 2px 0 0; font-size: 13px; }
.result-block, .result-form {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-top: 12px;
}
.result-block h4, .result-form h4 { margin: 0 0 8px; font-size: 14px; }
.result-current p { margin: 4px 0; }
.result-meta { margin-left: 8px; color: var(--muted); font-size: 12px; }
.result-remark { font-size: 13px; color: #334155; }
.form-item { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
.form-item input, .form-item select, .form-item textarea {
  font-size: 13px; color: #1f2937; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px;
}
.result-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
.result-form h4, .form-item-full, .conflict-block, .form-actions, .ok-text, .error-text { grid-column: 1 / -1; }
.form-actions { margin-top: 4px; }
.ok-text { color: #15803d; }
.conflict-block { border: 1px solid #f0b429; background: #fffbeb; border-radius: 8px; padding: 10px 12px; margin: 6px 0 12px; }
.conflict-title { margin: 0 0 8px; font-size: 13px; color: #92400e; }
.conflict-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.conflict-col { border-radius: 8px; padding: 8px 10px; font-size: 13px; }
.conflict-col p { margin: 3px 0; }
.conflict-old { border: 1px solid var(--border); background: #fff; }
.conflict-new { border: 1px solid #15803d; background: #f0fdf4; }
.conflict-col h5 { margin: 0 0 6px; font-size: 12px; }
.conflict-actions { display: flex; gap: 10px; margin-top: 10px; }
</style>
