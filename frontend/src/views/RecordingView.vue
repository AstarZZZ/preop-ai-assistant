<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  MicrophoneIcon, PauseIcon, PlayIcon, StopIcon, Cog6ToothIcon, FolderIcon,
  CheckCircleIcon, SignalIcon, ArrowRightIcon, UserGroupIcon, ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import { api, formatDuration } from '../services/api'
import { useRecorder } from '../composables/useRecorder'

const props = defineProps({ id: String })
const router = useRouter()
const notify = inject('notify')
const openSettings = inject('openSettings')
const meeting = ref(null)
const health = ref(null)
const settings = ref(null)
const canvas = ref(null)
const saving = ref(false)
const liveSegments = ref([])
const lastPartialAt = ref(0)
const partialBusy = ref(false)
const { state, elapsedMs, level, error, start, pause, resume, stop, snapshot } = useRecorder()
let partialTimer

const recording = computed(() => state.value === 'recording' || state.value === 'paused')
const modelReady = computed(() => health.value?.model?.state === 'ready')
const speakers = computed(() => {
  const max = meeting.value?.expected_speaker_max || 3
  return Array.from({ length: Math.min(max, 6) }, (_, index) => ({ id: `speaker_${index + 1}`, label: `讲话人${index + 1}`, role: index === 0 ? '主刀医生' : index === 1 ? '麻醉医生' : index === 2 ? '影像科医生' : '待分配' }))
})
const detectedSpeakerCount = computed(() => new Set(liveSegments.value.map(item => item.speaker_id).filter(Boolean)).size)
const clinicalTerms = computed(() => {
  const text = liveSegments.value.map(item => item.corrected_text || item.text || '').join('')
  const terms = ['ASA', '阿司匹林', '华法林', '麻醉', '气道', '过敏', '出血', '感染', '影像', '超声', 'CT', '磁共振']
  return terms.filter(term => text.toLowerCase().includes(term.toLowerCase()))
})

onMounted(async () => {
  try {
    ;[meeting.value, health.value, settings.value] = await Promise.all([
      api(`/api/meetings/${props.id}`), api('/api/health'), api('/api/settings'),
    ])
  } catch (cause) { notify(cause.message, 'error') }
})

async function begin() {
  if (!modelReady.value) {
    notify(health.value?.model?.detail || '本地语音识别模型未就绪，请先启动 ASR 服务', 'error')
    return
  }
  await nextTick()
  try {
    await start({ deviceId: settings.value?.microphone_id, sampleRate: settings.value?.sample_rate, canvas: canvas.value })
    notify('会议录制已开始，真实音频正在本地缓存并滚动识别')
    partialTimer = setInterval(runPartialTranscription, 8000)
  } catch { notify(error.value || '无法开始录音，请检查麦克风权限', 'error') }
}

async function runPartialTranscription() {
  if (state.value !== 'recording' || partialBusy.value || elapsedMs.value - lastPartialAt.value < 6000) return
  const blob = await snapshot()
  if (!blob?.size) return
  lastPartialAt.value = elapsedMs.value
  partialBusy.value = true
  const form = new FormData()
  form.append('audio', blob, 'live-recording.webm')
  try {
    const result = await api(`/api/meetings/${props.id}/live-transcribe`, { method: 'POST', body: form })
    liveSegments.value = result.segments || []
  } catch (cause) { notify(`实时分段识别暂不可用：${cause.message}`, 'error') } finally { partialBusy.value = false }
}

async function finish() {
  saving.value = true
  clearInterval(partialTimer)
  try {
    const blob = await stop()
    if (!blob?.size) throw new Error('没有获取到可保存的录音数据')
    const hint = liveSegments.value.map(item => item.corrected_text).join('。')
    const form = new FormData()
    const ext = blob.type.includes('mp4') ? 'm4a' : 'webm'
    form.append('audio', blob, `meeting-${meeting.value.meeting_no}.${ext}`)
    form.append('transcript_hint', hint)
    await api(`/api/meetings/${props.id}/upload`, { method: 'POST', body: form })
    notify('录音已保存，正在生成讲话人转写与比对结果')
    await api(`/api/meetings/${props.id}/process`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ transcript_hint: hint }) })
    router.push(`/meeting/${props.id}`)
  } catch (cause) { notify(cause.message, 'error') } finally { saving.value = false }
}

onBeforeUnmount(() => { clearInterval(partialTimer) })
</script>

<template>
  <section v-if="meeting" class="recording-page">
    <div class="recording-steps"><span class="done"><b>1</b>讨论信息</span><i /><span class="active"><b>2</b>会议录制</span><i /><span><b>3</b>资料比对</span><i /><span><b>4</b>人工复核</span><i /><span><b>5</b>归档</span></div>
    <div class="recording-layout">
      <aside class="case-column">
        <section><div class="column-title"><h3>病例概览</h3></div><dl class="case-facts"><div><dt>患者</dt><dd>{{ meeting.patient_code }}</dd></div><div><dt>手术</dt><dd>{{ meeting.surgery_name }}</dd></div><div><dt>讨论日期</dt><dd>{{ meeting.meeting_date }}</dd></div><div><dt>预计参与人数</dt><dd>{{ meeting.expected_speaker_min }}–{{ meeting.expected_speaker_max }} 人</dd></div></dl></section>
        <section><div class="column-title"><h3>讲话人映射</h3><small>录制后可编辑</small></div><div class="speaker-map"><div v-for="(speaker, index) in speakers.slice(0, 4)" :key="speaker.id"><i :class="`speaker-${index + 1}`" /><span>{{ speaker.label }}</span><small>{{ speaker.role }}</small></div></div></section>
        <section class="storage-card"><div class="column-title"><h3>本地存储</h3><button class="icon-button mini" @click="openSettings"><Cog6ToothIcon /></button></div><p><FolderIcon />{{ settings?.storage_path }}</p><div class="storage-meter"><span /></div><small>录音结束后写入该目录</small></section>
      </aside>

      <main class="recording-studio">
        <section class="recorder-control">
          <button v-if="state === 'idle' || state === 'error'" class="record-button" type="button" :disabled="!modelReady" @click="begin"><MicrophoneIcon /><strong>{{ modelReady ? '开始会议录制' : '本地识别模型未就绪' }}</strong></button>
          <div v-else class="recording-status"><span class="live-dot" /><div><strong>{{ state === 'paused' ? '录制已暂停' : '正在录制' }}</strong><small>录音文件正在本地保存</small></div><b>{{ formatDuration(elapsedMs) }}</b></div>
          <div class="input-device"><span>麦克风输入</span><strong>{{ settings?.microphone_label || '系统默认麦克风' }}</strong><button class="text-button" @click="openSettings"><Cog6ToothIcon />更换设备</button></div>
          <div class="quality-state"><span>输入电平</span><div class="level-bars"><i v-for="n in 18" :key="n" :class="{ on: n <= Math.max(2, Math.ceil(level / 5)) }" /></div><small>{{ recording ? (level > 3 ? '良好' : '声音较低') : '等待录制' }}</small></div>
        </section>

        <section class="waveform-panel"><div class="section-row"><div><h3>音频波形（实时）</h3><p>{{ recording ? '正在捕获会议室单麦克风声音' : '开始录制后显示实时输入波形' }}</p></div><span><SignalIcon />48 kHz / 本地</span></div><canvas ref="canvas" class="waveform-canvas" aria-label="实时录音波形" /><div class="timeline"><span>00:00</span><span>{{ formatDuration(elapsedMs / 2) }}</span><span>{{ formatDuration(elapsedMs) }}</span></div><div class="transport">
          <button v-if="state === 'recording'" class="round-control" @click="pause"><PauseIcon /></button><button v-else-if="state === 'paused'" class="round-control" @click="resume"><PlayIcon /></button><button v-if="recording" class="round-control stop" @click="finish"><StopIcon /></button><div><strong>{{ formatDuration(elapsedMs) }}</strong><small>{{ state === 'paused' ? '已暂停' : recording ? '录制时长' : '等待开始' }}</small></div></div></section>

        <section class="live-transcript"><div class="section-row"><div><h3>实时转录</h3><p>{{ modelReady ? 'SenseVoice + CAM++ 本地真实识别，约 8 秒滚动刷新' : '本地 ASR 服务未就绪，不会生成模拟文本' }}</p></div><span class="status-badge" :class="modelReady ? 'confirmed' : 'warning'">{{ modelReady ? '本地真实模型' : '模型未就绪' }}</span></div>
          <div v-if="!liveSegments.length" class="transcript-empty"><MicrophoneIcon /><p>{{ recording ? '正在聆听，首条转录即将出现…' : '开始录制后，讲话人和实时文本将在这里显示。' }}</p></div>
          <div v-else class="live-lines"><article v-for="(segment, index) in liveSegments" :key="segment.id"><time>{{ formatDuration(segment.start_ms) }}</time><span class="speaker-chip" :class="`speaker-${(index % 3) + 1}`">{{ segment.speaker_id?.replace('speaker_', '讲话人') }}</span><p>{{ segment.corrected_text || segment.text }}</p><small v-if="segment.confidence">置信度 {{ segment.confidence }}</small><small v-else>CAM++ 匿名讲话人标签</small></article><article v-if="recording" class="recognizing"><time>{{ formatDuration(elapsedMs) }}</time><span class="speaker-chip neutral">{{ partialBusy ? '识别中' : '监听中' }}</span><p>{{ partialBusy ? '本地模型正在处理当前录音…' : '正在接收新的语音片段…' }}</p></article></div>
        </section>
      </main>

      <aside class="assistant-column">
        <section><div class="column-title"><h3>会议助手</h3></div><div class="assistant-stat"><UserGroupIcon /><div><span>参与者检测</span><strong>已检测 {{ detectedSpeakerCount }} / 预计 {{ meeting.expected_speaker_max }}</strong></div></div><div class="assistant-stat"><SignalIcon /><div><span>识别服务</span><strong>{{ modelReady ? 'SenseVoice / CAM++' : '不可用' }}</strong><small>{{ modelReady ? '本地离线运行' : '请启动本地模型服务' }}</small></div></div></section>
        <section><div class="column-title"><h3>识别到的临床术语</h3></div><div v-if="clinicalTerms.length" class="term-cloud"><span v-for="term in clinicalTerms" :key="term">{{ term }}</span></div><p v-else class="muted-copy">待真实转录后提取</p></section>
        <section class="ai-reminder"><ExclamationTriangleIcon /><div><span>AI 提醒（仅供参考）</span><strong>知识库比对将在录制结束后执行</strong><p>转录、患者资料与院内规则将一并核对，所有结果须由医务人员复核。</p></div></section>
      </aside>
    </div>

    <div class="recording-actions"><div class="clinical-disclaimer">AI 生成内容仅用于会议记录与临床辅助参考，不构成诊断、治疗建议或法律依据，所有结果须由具备资质的医务人员复核。</div><button v-if="recording" class="button secondary" @click="state === 'paused' ? resume() : pause()"><component :is="state === 'paused' ? PlayIcon : PauseIcon" />{{ state === 'paused' ? '继续录制' : '暂停录制' }}</button><button class="button danger" :disabled="!recording || saving" @click="finish"><StopIcon />{{ saving ? '保存并处理中…' : '结束并保存' }}</button><button class="button primary" :disabled="!meeting.segments?.length" @click="router.push(`/meeting/${id}`)">进入患者资料比对 <ArrowRightIcon /></button></div>
  </section>
  <section v-else class="page"><div class="loading-state">正在加载讨论信息…</div></section>
</template>
