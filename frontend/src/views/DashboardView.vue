<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { PlusIcon, ArrowRightIcon, ShieldCheckIcon, MicrophoneIcon, ExclamationTriangleIcon } from '@heroicons/vue/24/outline'
import { api, formatDate, statusLabel } from '../services/api'

const router = useRouter()
const data = ref({ total: 0, confirmed: 0, pending: 0, high_alerts: 0, recent: [] })
const loading = ref(true)
onMounted(async () => { try { data.value = await api('/api/dashboard') } finally { loading.value = false } })
</script>

<template>
  <section class="page dashboard-page">
    <div class="welcome-panel">
      <div>
        <span class="section-kicker">本地化临床会议工作流</span>
        <h2>让每一次术前讨论有记录、有依据、可追溯</h2>
        <p>从多人语音整理到患者资料核对，全流程保留证据来源，AI 只提供辅助草稿。</p>
        <div class="welcome-tags"><span><MicrophoneIcon />本地录音</span><span><ShieldCheckIcon />人工复核</span><span><ExclamationTriangleIcon />规则预警</span></div>
      </div>
      <RouterLink class="button primary" to="/new"><PlusIcon />发起术前讨论</RouterLink>
    </div>

    <div class="metric-grid">
      <article><span>讨论档案</span><strong>{{ data.total }}</strong><small>全部本地记录</small></article>
      <article><span>待处理</span><strong>{{ data.pending }}</strong><small>待识别或待复核</small></article>
      <article><span>已归档</span><strong>{{ data.confirmed }}</strong><small>完成医务人员确认</small></article>
      <article class="risk"><span>高优先级提示</span><strong>{{ data.high_alerts }}</strong><small>仅作辅助提醒</small></article>
    </div>

    <div class="content-card recent-card">
      <header class="card-header"><div><h3>最近讨论</h3><p>按日期查看原始文本、摘要、比对结果与预警信息。</p></div><RouterLink class="text-link" to="/archive">查看全部 <ArrowRightIcon /></RouterLink></header>
      <div v-if="loading" class="loading-state">正在读取本地档案…</div>
      <div v-else-if="!data.recent.length" class="empty-state"><h3>还没有讨论记录</h3><p>新建第一条术前讨论，开始录制与转写。</p></div>
      <div v-else class="record-table-wrap"><table class="record-table"><thead><tr><th>讨论日期</th><th>手术与患者</th><th>科室</th><th>讲话段落</th><th>预警</th><th>状态</th><th /></tr></thead><tbody>
        <tr v-for="item in data.recent" :key="item.id">
          <td>{{ formatDate(item.meeting_date) }}<small>{{ item.meeting_no }}</small></td>
          <td><strong>{{ item.surgery_name }}</strong><small>患者 {{ item.patient_code }}</small></td>
          <td>{{ item.department || '未填写' }}</td><td>{{ item.segment_count }} 段</td><td :class="{ 'danger-text': item.alert_count }">{{ item.alert_count }}</td>
          <td><span class="status-badge" :class="item.status">{{ statusLabel[item.status] || item.status }}</span></td>
          <td><button class="table-action" @click="router.push(`/meeting/${item.id}`)">打开 <ArrowRightIcon /></button></td>
        </tr>
      </tbody></table></div>
    </div>
  </section>
</template>
