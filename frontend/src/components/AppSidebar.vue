<script setup>
import { inject } from 'vue'
import { useRoute } from 'vue-router'
import {
  HomeIcon, PlusIcon, ClipboardDocumentListIcon, BookOpenIcon,
  Cog6ToothIcon, InformationCircleIcon,
} from '@heroicons/vue/24/outline'

const route = useRoute()
const openSettings = inject('openSettings')
const items = [
  { label: '工作台', to: '/', names: ['dashboard'], icon: HomeIcon },
  { label: '新建讨论', to: '/new', names: ['new', 'record'], icon: PlusIcon },
  { label: '讨论档案', to: '/archive', names: ['archive', 'meeting'], icon: ClipboardDocumentListIcon },
  { label: '知识规则', to: '/knowledge', names: ['knowledge'], icon: BookOpenIcon },
]
</script>

<template>
  <aside class="sidebar">
    <RouterLink class="brand" to="/">
      <span class="brand-mark"><img :src="'/assets/hospital-logo.png'" alt="东阳市人民医院标识" /></span>
      <span><strong>术前智议</strong><small>PREOP ASSIST</small></span>
    </RouterLink>

    <nav class="primary-nav" aria-label="主导航">
      <RouterLink
        v-for="item in items" :key="item.to" :to="item.to"
        class="nav-link" :class="{ active: item.names.includes(route.name) }"
      >
        <component :is="item.icon" />
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="sidebar-spacer" />
    <button class="nav-link utility" type="button" @click="openSettings">
      <Cog6ToothIcon /><span>设备与存储</span>
    </button>
    <a class="nav-link utility" href="#about"><InformationCircleIcon /><span>关于</span></a>

    <div class="partner-logos">
      <div><img :src="'/assets/hospital-logo.png'" alt="东阳市人民医院" /><span>东阳市人民医院</span></div>
      <div><img :src="'/assets/university-logo.png'" alt="杭州电子科技大学" /><span>杭州电子科技大学</span></div>
    </div>
  </aside>
</template>
