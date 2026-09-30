<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { MagnifyingGlassIcon, ArrowRightIcon, PlusIcon } from '@heroicons/vue/24/outline'
import { api, formatDate, statusLabel } from '../services/api'

const router = useRouter()
const items = ref([])
const query = ref('')
const loading = ref(false)
async function load() { loading.value = true; try { items.value = (await api(`/api/meetings?q=${encodeURIComponent(query.value)}`)).items } finally { loading.value = false } }
onMounted(load)
</script>

<template>
  <section class="page">
    <div class="page-heading"><div><span class="section-kicker">本地历史记录</span><h2>讨论档案</h2><p>保存原始录音、讲话人文本、患者摘要、资料比对、预警与最终讨论结论。</p></div><RouterLink class="button primary" to="/new"><PlusIcon />新建讨论</RouterLink></div>
    <div class="content-card archive-card">
      <header class="archive-toolbar"><label class="search-box"><MagnifyingGlassIcon /><input v-model="query" placeholder="搜索讨论编号、患者编号或手术名称" @keyup.enter="load" /></label><button class="button secondary" @click="load">查询</button></header>
      <div v-if="loading" class="loading-state">正在读取档案…</div>
      <div v-else-if="!items.length" class="empty-state"><h3>未找到讨论档案</h3><p>调整搜索条件，或新建一次术前讨论。</p></div>
      <div v-else class="archive-list"><article v-for="item in items" :key="item.id" @click="router.push(`/meeting/${item.id}`)"><div class="archive-date"><strong>{{ formatDate(item.meeting_date).slice(5) }}</strong><small>{{ item.meeting_date.slice(0,4) }}</small></div><div class="archive-main"><span>{{ item.meeting_no }}</span><h3>{{ item.surgery_name }}</h3><p>患者 {{ item.patient_code }} · {{ item.department || '未填写科室' }} · 预计 {{ item.expected_speaker_min }}–{{ item.expected_speaker_max }} 人</p></div><div class="archive-counts"><span><b>{{ item.segment_count }}</b> 讲话段落</span><span :class="{ risk: item.alert_count }"><b>{{ item.alert_count }}</b> 预警</span></div><span class="status-badge" :class="item.status">{{ statusLabel[item.status] }}</span><button class="table-action">查看 <ArrowRightIcon /></button></article></div>
    </div>
  </section>
</template>
