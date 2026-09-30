import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import DashboardView from './views/DashboardView.vue'
import NewMeetingView from './views/NewMeetingView.vue'
import RecordingView from './views/RecordingView.vue'
import ArchiveView from './views/ArchiveView.vue'
import MeetingDetailView from './views/MeetingDetailView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import './styles.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/new', name: 'new', component: NewMeetingView },
    { path: '/record/:id', name: 'record', component: RecordingView, props: true },
    { path: '/archive', name: 'archive', component: ArchiveView },
    { path: '/meeting/:id', name: 'meeting', component: MeetingDetailView, props: true },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

createApp(App).use(router).mount('#app')
