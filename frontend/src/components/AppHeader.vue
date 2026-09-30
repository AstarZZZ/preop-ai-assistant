<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Cog6ToothIcon, ShieldCheckIcon } from '@heroicons/vue/24/outline'
import { api } from '../services/api'

const route = useRoute()
const openSettings = inject('openSettings')
const health = ref(null)
onMounted(async () => { try { health.value = await api('/api/health') } catch { health.value = null } })

const title = computed(() => ({
  dashboard: '术前讨论工作台', new: '新建术前讨论', record: '会议录制', archive: '讨论档案',
  meeting: '讨论记录与校对', knowledge: '知识规则库',
}[route.name] || '术前智议'))

const modelLabel = computed(() => {
  if (!health.value) return '服务检查中'
  if (health.value.model?.state === 'ready') return '本地模型已就绪'
  if (health.value.model?.state === 'loading') return '本地模型加载中'
  return '本地模型不可用'
})
</script>

<template>
  <header class="topbar">
    <div>
      <p>东阳市人民医院 · 杭州电子科技大学</p>
      <h1>{{ title }}</h1>
    </div>
    <div class="topbar-actions">
      <span class="model-state" :class="health?.model?.state"><i />{{ modelLabel }}</span>
      <span class="human-review"><ShieldCheckIcon /> AI 结果须人工确认</span>
      <button class="icon-button" type="button" aria-label="打开设备与存储设置" @click="openSettings"><Cog6ToothIcon /></button>
      <RouterLink v-if="route.name !== 'new'" class="button primary small" to="/new">新建讨论</RouterLink>
    </div>
  </header>
</template>
