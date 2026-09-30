<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeftIcon, CheckCircleIcon, ExclamationTriangleIcon, PlayIcon, ArrowDownTrayIcon,
  ShieldCheckIcon, DocumentCheckIcon, PencilSquareIcon,
} from '@heroicons/vue/24/outline'
import { api, formatDuration, jsonOptions, statusLabel } from '../services/api'

const props = defineProps({ id: String })
const router = useRouter()
const notify = inject('notify')
const meeting = ref(null)
const tab = ref('transcript')
const confirming = ref(false)
const reviewChecked = ref(false)
const actor = ref('本地复核医生')

const report = computed(() => meeting.value?.report?.content || {})
const transcriptDuration = computed(() => Math.max(0, ...(meeting.value?.segments || []).map(x => x.end_ms || 0)))
const speakerCount = computed(() => new Set((meeting.value?.segments || []).map(x => x.speaker_id)).size)
const checklist = computed(() => {
  const comparison = report.value.comparison_items || []
  const base = ['患者基本信息', '手术信息', '重要病史', '过敏史', '药物使用史', '检验检查结果', '术前评估']
  return base.map((label, index) => ({ label, ok: index !== 4 || comparison.some(x => x.item === '用药与抗凝' && x.status === 'discussed') }))
})

onMounted(load)
async function load() { try { meeting.value = await api(`/api/meetings/${props.id}`) } catch (error) { notify(error.message, 'error') } }

async function saveSegment(segment) {
  try {
    await api(`/api/segments/${segment.id}`, jsonOptions('PUT', { speaker_role: segment.speaker_role, corrected_text: segment.corrected_text, review_status: 'reviewed' }))
    segment.review_status = 'reviewed'; notify('该段转写已保存')
  } catch (error) { notify(error.message, 'error') }
}

async function confirmArchive() {
  if (!reviewChecked.value) return notify('请先确认已完成核对且无误', 'error')
  confirming.value = true
  try { meeting.value = await api(`/api/meetings/${props.id}/confirm`, jsonOptions('POST', { actor: actor.value })); notify('讨论记录已完成确认并归档') } catch (error) { notify(error.message, 'error') } finally { confirming.value = false }
}
</script>

<template>
  <section v-if="meeting" class="meeting-detail-page">
    <header class="detail-heading"><button class="back-button" @click="router.push('/archive')"><ArrowLeftIcon /></button><div><div class="detail-title-line"><h2>{{ meeting.surgery_name }}</h2><span class="status-badge" :class="meeting.status">{{ statusLabel[meeting.status] }}</span></div><p>患者 {{ meeting.patient_code }} <i /> {{ meeting.department || '未填写科室' }} <i /> 讨论日期 {{ meeting.meeting_date }} <i /> 预计 {{ meeting.expected_speaker_min }}–{{ meeting.expected_speaker_max }} 人</p></div><div class="detail-heading-actions"><a class="button secondary" :href="`/api/meetings/${id}/export`"><ArrowDownTrayIcon />导出记录</a></div></header>
    <div class="detail-tabs"><button :class="{ active: tab === 'transcript' }" @click="tab='transcript'">原始文本与校对</button><button :class="{ active: tab === 'comparison' }" @click="tab='comparison'">患者资料比对</button><button :class="{ active: tab === 'alerts' }" @click="tab='alerts'">预警信息 <b v-if="meeting.alerts.length">{{ meeting.alerts.length }}</b></button><button :class="{ active: tab === 'summary' }" @click="tab='summary'">讨论摘要与结论</button></div>

    <div class="detail-workspace">
      <main class="detail-content">
        <div v-if="tab === 'transcript'" class="transcript-review"><div class="transcript-head"><span>时间</span><span>讲话人</span><span>原始文本（可编辑校对）</span><span>状态</span></div><article v-for="(segment, index) in meeting.segments" :key="segment.id"><time>{{ formatDuration(segment.start_ms) }}</time><div class="speaker-cell"><span :class="`speaker-dot speaker-${(index % 3)+1}`" /><strong>{{ segment.speaker_id.replace('speaker_', '讲话人') }}</strong><select v-model="segment.speaker_role"><option value="">选择角色</option><option>主刀医生</option><option>麻醉医生</option><option>影像科医生</option><option>护理人员</option></select></div><textarea v-model="segment.corrected_text" @change="saveSegment(segment)" /><button class="review-state" :class="{ reviewed: segment.review_status === 'reviewed' }" @click="saveSegment(segment)"><CheckCircleIcon />{{ segment.review_status === 'reviewed' ? '已校对' : '保存' }}</button></article><div v-if="!meeting.segments.length" class="empty-state"><h3>尚无转写文本</h3><p>请返回录制页面完成会议录音与识别。</p><RouterLink class="button primary" :to="`/record/${id}`">进入会议录制</RouterLink></div></div>
        <div v-else-if="tab === 'comparison'" class="comparison-view"><header><h3>患者资料与讨论覆盖比对</h3><p>证据来自患者资料、转写片段与本地知识规则，最终状态须人工确认。本次知识版本：{{ meeting.report?.knowledge_version || '未记录' }}</p></header><div class="comparison-table"><div class="comparison-row comparison-header"><span>比对项目</span><span>讨论覆盖</span><span>证据与知识来源</span><span>AI 状态</span></div><div v-for="item in report.comparison_items || []" :key="item.rule_id || item.item" class="comparison-row"><strong>{{ item.item }}<small v-if="item.rule_id">{{ item.rule_id }} · {{ item.category }}</small></strong><span>{{ item.status === 'discussed' ? '已在讨论中发现' : '未找到明确内容' }}</span><div class="comparison-evidence"><span v-if="item.evidence?.length" class="evidence-link">{{ item.evidence[0].speaker || '讲话人' }}：{{ item.evidence[0].text }}</span><span v-else>暂无转写证据</span><small v-if="item.source">知识来源：{{ item.source }} · {{ item.version }}</small></div><span class="status-badge" :class="item.status === 'discussed' ? 'confirmed' : 'uploaded'">{{ item.status === 'discussed' ? '已覆盖' : '待核对' }}</span></div></div></div>
        <div v-else-if="tab === 'alerts'" class="alerts-view"><header><h3>预警与证据</h3><p>以下内容仅提示需要复核的项目，不构成诊断或治疗建议。</p></header><article v-for="alert in meeting.alerts" :key="alert.id" class="alert-detail" :class="alert.severity"><ExclamationTriangleIcon /><div><span>{{ alert.severity === 'high' ? '高优先级' : '一般提醒' }}</span><h3>{{ alert.title }}</h3><p>{{ alert.message }}</p><div class="alert-evidence-grid"><section><b>患者资料证据</b><small v-for="evidence in alert.patient_evidence" :key="evidence.matched_term || evidence">{{ evidence.matched_term ? `命中“${evidence.matched_term}”：${evidence.excerpt}` : evidence }}</small><small v-if="!alert.patient_evidence?.length">未记录命中片段</small></section><section><b>讨论转写证据</b><small v-for="evidence in alert.meeting_evidence?.slice(0, 2)" :key="evidence.segment_id">{{ evidence.speaker || '讲话人' }}：{{ evidence.text }}</small><small v-if="!alert.meeting_evidence?.length">未找到对应讨论片段</small></section><section><b>知识条目</b><small>{{ alert.knowledge_evidence?.[0]?.name || alert.rule_id }} · {{ alert.knowledge_evidence?.[0]?.source || '本地知识规则' }} · {{ alert.knowledge_evidence?.[0]?.version }}</small></section></div></div><button class="button secondary small">标记已处理</button></article><div v-if="!meeting.alerts.length" class="empty-state"><CheckCircleIcon /><h3>当前没有规则预警</h3><p>仍需由医务人员完成全部内容复核。</p></div></div>
        <div v-else class="summary-view"><section><h3>患者历史信息摘要</h3><p>{{ report.patient_summary || '尚未生成患者摘要。' }}</p></section><section><h3>术前讨论摘要</h3><p>{{ report.discussion_summary || '尚未生成讨论摘要。' }}</p></section><section><h3>手术关键总结</h3><ul><li v-for="point in report.key_points || []" :key="point">{{ point }}</li></ul></section><section><h3>讨论结论</h3><p>{{ report.discussion_conclusion || '尚未形成可复核结论。' }}</p></section><section class="missing"><h3>待补充信息</h3><ul><li v-for="item in report.missing_information || []" :key="item">{{ item }}</li></ul></section></div>

        <div v-if="meeting.audio_url" class="audio-dock"><button><PlayIcon /></button><span>{{ formatDuration(transcriptDuration) }} / {{ formatDuration(transcriptDuration) }}</span><audio :src="meeting.audio_url" controls /><small>原始录音 · {{ speakerCount }} 位讲话人</small></div>
      </main>

      <aside class="evidence-sidebar"><section><h3>预警与证据</h3><article v-if="meeting.alerts[0]" class="evidence-alert"><div><ExclamationTriangleIcon /><strong>{{ meeting.alerts[0].severity === 'high' ? '高优先级' : '待关注' }}：{{ meeting.alerts[0].title }}</strong></div><p>{{ meeting.alerts[0].message }}</p><h4>证据来源</h4><small>患者资料与本地知识规则</small><button class="text-link" @click="tab='alerts'">查看详情</button></article><div v-else class="safe-note"><CheckCircleIcon />未发现规则触发项</div></section><section><h3>患者资料要点核对</h3><ul class="check-list"><li v-for="item in checklist" :key="item.label"><span>{{ item.label }}</span><small :class="{ pending: !item.ok }">{{ item.ok ? '已核对' : '待核对' }}</small><CheckCircleIcon v-if="item.ok" /><ExclamationTriangleIcon v-else /></li></ul></section><section><h3>人工确认</h3><label class="field"><span>复核人</span><input v-model="actor" /></label><label class="review-check"><input v-model="reviewChecked" type="checkbox" />我已核对原始录音、转写、患者资料及预警信息</label></section></aside>
    </div>
    <div class="detail-bottom-bar"><div><span>讨论记录时长 {{ formatDuration(transcriptDuration) }}</span><i /><span>发言人数 {{ speakerCount }}</span></div><label><input v-model="reviewChecked" type="checkbox" />核对完成并确认无误</label><button class="button secondary" @click="confirmArchive" :disabled="confirming">确认归档</button><button class="button primary" @click="notify('校对内容已保存在本地数据库')"><DocumentCheckIcon />保存校对</button></div>
  </section>
  <section v-else class="page"><div class="loading-state">正在加载讨论档案…</div></section>
</template>
