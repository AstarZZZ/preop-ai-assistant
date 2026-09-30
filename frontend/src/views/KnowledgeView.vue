<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import {
  ArrowDownTrayIcon, ArrowUpTrayIcon, BeakerIcon, BookOpenIcon, CheckCircleIcon,
  ClipboardDocumentIcon, ExclamationTriangleIcon, MagnifyingGlassIcon, PencilSquareIcon,
  PlusIcon, ShieldCheckIcon, TrashIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import { api, jsonOptions } from '../services/api'

const notify = inject('notify')
const rules = ref([])
const summary = ref({ total: 0, enabled: 0, high: 0, custom: 0, categories: [], version: '' })
const loading = ref(true)
const query = ref('')
const category = ref('')
const state = ref('all')
const editorOpen = ref(false)
const testOpen = ref(false)
const saving = ref(false)
const importInput = ref(null)
const editingId = ref('')
const testResult = ref(null)

const typeOptions = [
  { value: 'required_discussion', label: '必须讨论项', help: '转写中没有出现任一覆盖词时提示复核。' },
  { value: 'conditional_term', label: '条件性核对', help: '患者资料命中触发词，且讨论未出现覆盖词时提示。' },
  { value: 'contraindication_term', label: '疑似禁忌/高风险', help: '患者资料命中关键词即产生人工复核提示，不自动下临床结论。' },
  { value: 'patient_data_required', label: '患者资料完整性', help: '未录入患者历史信息时提示。' },
]
const severityOptions = [
  { value: 'high', label: '高优先级' },
  { value: 'warning', label: '一般提醒' },
  { value: 'info', label: '信息提示' },
]

const emptyRule = () => ({
  name: '', category: '通用核对', rule_type: 'required_discussion', severity: 'warning',
  surgery_keywords_text: '', trigger_terms_text: '', required_terms_text: '',
  message: '', source: '', version: 'local-1', created_by: '本地管理员', enabled: true,
})
const form = ref(emptyRule())
const testForm = ref({ surgery_name: '腹腔镜胆囊切除术', patient_history: '', transcript: '' })

const filteredRules = computed(() => {
  const term = query.value.trim().toLowerCase()
  return rules.value.filter(rule => {
    const text = [rule.name, rule.id, rule.category, rule.source, ...(rule.trigger_terms || []), ...(rule.required_terms || [])].join(' ').toLowerCase()
    return (!term || text.includes(term)) && (!category.value || rule.category === category.value)
      && (state.value === 'all' || (state.value === 'enabled' ? rule.enabled : !rule.enabled))
  })
})
const typeHelp = computed(() => typeOptions.find(item => item.value === form.value.rule_type)?.help || '')
const showTriggers = computed(() => ['conditional_term', 'contraindication_term'].includes(form.value.rule_type))
const showRequired = computed(() => ['required_discussion', 'conditional_term'].includes(form.value.rule_type))

onMounted(load)

async function load() {
  loading.value = true
  try {
    const data = await api('/api/rules')
    rules.value = data.items
    summary.value = data.summary
  } catch (error) { notify(error.message, 'error') }
  finally { loading.value = false }
}

function toText(value) { return (value || []).join('，') }
function toArray(value) {
  return String(value || '').split(/[,，、\n]/).map(item => item.trim()).filter((item, index, all) => item && all.indexOf(item) === index)
}
function payloadFromForm() {
  return {
    name: form.value.name, category: form.value.category, rule_type: form.value.rule_type,
    severity: form.value.severity, surgery_keywords: toArray(form.value.surgery_keywords_text),
    trigger_terms: toArray(form.value.trigger_terms_text), required_terms: toArray(form.value.required_terms_text),
    message: form.value.message, source: form.value.source, version: form.value.version,
    created_by: form.value.created_by, enabled: form.value.enabled,
  }
}

function openNew() {
  editingId.value = ''
  form.value = emptyRule()
  editorOpen.value = true
}
function openEdit(rule, copy = false) {
  editingId.value = copy ? '' : rule.id
  form.value = {
    ...rule, name: copy ? `${rule.name}（副本）` : rule.name,
    surgery_keywords_text: toText(rule.surgery_keywords), trigger_terms_text: toText(rule.trigger_terms),
    required_terms_text: toText(rule.required_terms),
  }
  editorOpen.value = true
}
async function save() {
  saving.value = true
  try {
    const path = editingId.value ? `/api/rules/${editingId.value}` : '/api/rules'
    await api(path, jsonOptions(editingId.value ? 'PUT' : 'POST', payloadFromForm()))
    editorOpen.value = false
    notify(editingId.value ? '知识条目已更新' : '知识条目已新增')
    await load()
  } catch (error) { notify(error.message, 'error') }
  finally { saving.value = false }
}
async function toggleRule(rule) {
  try {
    await api(`/api/rules/${rule.id}`, jsonOptions('PUT', { enabled: !rule.enabled }))
    notify(rule.enabled ? '知识条目已停用' : '知识条目已启用')
    await load()
  } catch (error) { notify(error.message, 'error') }
}
async function removeRule(rule) {
  if (!window.confirm(`确认删除“${rule.name}”？已生成的历史报告仍保留当时规则证据。`)) return
  try {
    await api(`/api/rules/${rule.id}`, { method: 'DELETE' })
    notify('知识条目已删除')
    await load()
  } catch (error) { notify(error.message, 'error') }
}

async function importJson(event) {
  const file = event.target.files?.[0]
  if (!file) return
  try {
    const parsed = JSON.parse(await file.text())
    const items = Array.isArray(parsed) ? parsed : parsed.items
    const result = await api('/api/rules/import', jsonOptions('POST', { items, overwrite: false }))
    notify(`导入完成：新增 ${result.created} 条，更新 ${result.updated} 条，失败 ${result.skipped} 条`, result.skipped ? 'error' : 'success')
    await load()
  } catch (error) { notify(`导入失败：${error.message}`, 'error') }
  finally { event.target.value = '' }
}

function openTest(rule) {
  editingId.value = rule?.id || editingId.value
  testResult.value = null
  testOpen.value = true
}
async function runTest() {
  testResult.value = null
  try {
    const body = { ...testForm.value }
    if (editingId.value) body.rule_id = editingId.value
    else body.rule = payloadFromForm()
    testResult.value = await api('/api/rules/test', jsonOptions('POST', body))
  } catch (error) { notify(error.message, 'error') }
}
function typeLabel(value) { return typeOptions.find(item => item.value === value)?.label || value }
function severityLabel(value) { return severityOptions.find(item => item.value === value)?.label || value }
</script>

<template>
  <section class="page knowledge-page">
    <div class="page-heading knowledge-heading">
      <div><span class="section-kicker">证据可追溯 · 本地知识库</span><h2>知识规则库</h2><p>将院内制度、术前核对项与疑似高风险条件编辑为可执行规则，分析时自动保留来源与版本。</p></div>
      <div class="knowledge-heading-actions">
        <input ref="importInput" class="visually-hidden" type="file" accept="application/json,.json" @change="importJson" />
        <button class="button secondary" @click="importInput.click()"><ArrowUpTrayIcon />导入 JSON</button>
        <a class="button secondary" href="/api/rules/export"><ArrowDownTrayIcon />导出备份</a>
        <button class="button primary" @click="openNew"><PlusIcon />新增知识条目</button>
      </div>
    </div>

    <div class="knowledge-intro"><ShieldCheckIcon /><div><strong>正式使用前须由医院临床专业组审核并定期更新</strong><p>系统只识别“需复核的线索”，不自动判定手术禁忌。当前版本：{{ summary.version || '读取中' }}</p></div></div>

    <div class="knowledge-metrics">
      <article><span>全部条目</span><strong>{{ summary.total }}</strong><small>包含内置与自定义</small></article>
      <article><span>正在启用</span><strong>{{ summary.enabled }}</strong><small>将参与下次分析</small></article>
      <article class="risk"><span>高优先级</span><strong>{{ summary.high }}</strong><small>需重点人工复核</small></article>
      <article><span>自定义条目</span><strong>{{ summary.custom }}</strong><small>由本地用户维护</small></article>
    </div>

    <div class="content-card knowledge-workbench">
      <header class="knowledge-toolbar">
        <label class="search-box"><MagnifyingGlassIcon /><input v-model="query" placeholder="搜索名称、编号、关键词或来源" /></label>
        <select v-model="category"><option value="">全部分类</option><option v-for="item in summary.categories" :key="item">{{ item }}</option></select>
        <select v-model="state"><option value="all">全部状态</option><option value="enabled">仅已启用</option><option value="disabled">仅已停用</option></select>
        <span>共 {{ filteredRules.length }} 条</span>
      </header>

      <div v-if="loading" class="loading-state">正在读取本地知识库…</div>
      <div v-else-if="filteredRules.length" class="rule-list advanced">
        <article v-for="rule in filteredRules" :key="rule.id" :class="{ disabled: !rule.enabled }">
          <div class="rule-icon"><BookOpenIcon /></div>
          <div class="rule-body">
            <div class="rule-title"><h3>{{ rule.name }}</h3><span class="rule-id">{{ rule.id }}</span><span :class="['severity-tag', rule.severity]">{{ severityLabel(rule.severity) }}</span></div>
            <p>{{ rule.message }}</p>
            <div class="rule-meta"><span>{{ rule.category }}</span><span>{{ typeLabel(rule.rule_type) }}</span><span>版本 {{ rule.version }}</span><span>来源：{{ rule.source }}</span></div>
            <div v-if="rule.surgery_keywords?.length || rule.trigger_terms?.length || rule.required_terms?.length" class="rule-logic">
              <span v-if="rule.surgery_keywords?.length"><b>手术范围</b>{{ rule.surgery_keywords.join('、') }}</span>
              <span v-if="rule.trigger_terms?.length"><b>患者触发词</b>{{ rule.trigger_terms.join('、') }}</span>
              <span v-if="rule.required_terms?.length"><b>讨论覆盖词</b>{{ rule.required_terms.join('、') }}</span>
            </div>
          </div>
          <div class="rule-actions">
            <button :class="['rule-switch', { on: rule.enabled }]" :aria-label="rule.enabled ? '停用' : '启用'" @click="toggleRule(rule)"><i /></button>
            <button class="text-button" @click="openTest(rule)"><BeakerIcon />试跑</button>
            <button class="text-button" @click="openEdit(rule)"><PencilSquareIcon />编辑</button>
            <button class="text-button" @click="openEdit(rule, true)"><ClipboardDocumentIcon />复制</button>
            <button v-if="!rule.id.startsWith('CHECK-')" class="text-button danger-text" @click="removeRule(rule)"><TrashIcon />删除</button>
          </div>
        </article>
      </div>
      <div v-else class="empty-state"><BookOpenIcon /><h3>没有符合筛选条件的知识条目</h3><p>可清除筛选条件，或新增院内知识规则。</p></div>
    </div>

    <div v-if="editorOpen" class="knowledge-modal-layer" @click.self="editorOpen=false">
      <section class="knowledge-modal" role="dialog" aria-modal="true" aria-labelledby="rule-editor-title">
        <header><div><span class="section-kicker">可执行知识规则</span><h2 id="rule-editor-title">{{ editingId ? '编辑知识条目' : '新增知识条目' }}</h2></div><button class="icon-button" @click="editorOpen=false"><XMarkIcon /></button></header>
        <div class="knowledge-form">
          <div class="form-grid two"><label class="field"><span>条目名称 *</span><input v-model.trim="form.name" placeholder="例如：肝功能异常围术期核对" /></label><label class="field"><span>分类</span><input v-model.trim="form.category" list="category-options" placeholder="例如：麻醉风险" /><datalist id="category-options"><option v-for="item in summary.categories" :key="item">{{ item }}</option></datalist></label></div>
          <div class="form-grid two"><label class="field"><span>规则类型 *</span><select v-model="form.rule_type"><option v-for="item in typeOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select><small class="field-help">{{ typeHelp }}</small></label><label class="field"><span>提示级别</span><select v-model="form.severity"><option v-for="item in severityOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label></div>
          <label class="field"><span>适用手术关键词</span><input v-model="form.surgery_keywords_text" placeholder="留空表示适用全部；多个词用逗号分隔" /><small class="field-help">例如：胆囊切除，腹腔镜胆囊切除术</small></label>
          <label v-if="showTriggers" class="field"><span>患者资料触发词 *</span><textarea v-model="form.trigger_terms_text" placeholder="例如：华法林，利伐沙班，凝血异常" /></label>
          <label v-if="showRequired" class="field"><span>讨论覆盖词 *</span><textarea v-model="form.required_terms_text" placeholder="例如：停药，出血，桥接，凝血功能" /></label>
          <label class="field"><span>触发后的人工复核提示 *</span><textarea v-model.trim="form.message" placeholder="描述需要医务人员核对的事项，避免自动下诊断或治疗结论。" /></label>
          <div class="form-grid two"><label class="field"><span>知识来源/依据 *</span><input v-model.trim="form.source" placeholder="院内制度名称、文件编号或指南章节" /></label><label class="field"><span>版本</span><input v-model.trim="form.version" placeholder="例如：2026.1" /></label></div>
          <div class="form-grid two"><label class="field"><span>维护人</span><input v-model.trim="form.created_by" /></label><label class="knowledge-enable"><input v-model="form.enabled" type="checkbox" /><span><strong>保存后立即启用</strong><small>启用后将参与新的讨论分析与重新分析</small></span></label></div>
        </div>
        <footer><button class="button secondary" @click="openTest()"><BeakerIcon />用样例试跑</button><span /><button class="button secondary" @click="editorOpen=false">取消</button><button class="button primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存知识条目' }}</button></footer>
      </section>
    </div>

    <div v-if="testOpen" class="knowledge-modal-layer test-layer" @click.self="testOpen=false">
      <section class="knowledge-modal test-modal" role="dialog" aria-modal="true">
        <header><div><span class="section-kicker">规则试验台</span><h2>使用模拟信息试跑</h2></div><button class="icon-button" @click="testOpen=false"><XMarkIcon /></button></header>
        <div class="knowledge-form"><label class="field"><span>手术名称</span><input v-model="testForm.surgery_name" /></label><label class="field"><span>模拟患者历史信息</span><textarea v-model="testForm.patient_history" placeholder="填入既往史、过敏史、用药、检查结果等" /></label><label class="field"><span>模拟讨论转写</span><textarea v-model="testForm.transcript" placeholder="填入一段模拟会议转写，检查规则是否会触发" /></label>
          <div v-if="testResult" :class="['rule-test-result', { matched: testResult.matched }]">
            <component :is="testResult.matched ? ExclamationTriangleIcon : CheckCircleIcon" /><div><strong>{{ testResult.matched ? '已触发人工复核提示' : '未触发预警' }}</strong><p>{{ testResult.explanation }}</p><small v-if="testResult.alerts?.[0]">{{ testResult.alerts[0].message }}</small></div>
          </div>
        </div>
        <footer><span /><button class="button secondary" @click="testOpen=false">关闭</button><button class="button primary" @click="runTest"><BeakerIcon />运行试跑</button></footer>
      </section>
    </div>
  </section>
</template>
