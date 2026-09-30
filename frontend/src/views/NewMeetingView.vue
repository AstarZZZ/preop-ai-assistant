<script setup>
import { inject, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CalendarDaysIcon, UsersIcon, DocumentTextIcon, ArrowRightIcon } from '@heroicons/vue/24/outline'
import { api, jsonOptions } from '../services/api'

const router = useRouter()
const notify = inject('notify')
const saving = ref(false)
const today = new Date().toISOString().slice(0, 10)
const form = reactive({
  meeting_date: today, patient_code: '', surgery_name: '', surgery_site: '', planned_surgery_date: '', department: '普外科',
  expected_speaker_min: 2, expected_speaker_max: 5, focus_questions: '', patient_history: '',
})

async function submit() {
  saving.value = true
  try {
    const meeting = await api('/api/meetings', jsonOptions('POST', form))
    notify('讨论已创建，请检查设备后开始录制')
    router.push(`/record/${meeting.id}`)
  } catch (error) { notify(error.message, 'error') } finally { saving.value = false }
}
</script>

<template>
  <section class="page narrow-page">
    <div class="workflow-steps"><span class="active"><b>1</b>讨论信息</span><i /><span><b>2</b>会议录制</span><i /><span><b>3</b>资料比对与复核</span></div>
    <form class="content-card meeting-form" @submit.prevent="submit">
      <header class="card-header"><div><span class="section-kicker">讨论准备</span><h2>创建术前讨论</h2><p>先录入手术与参与人数，创建后进入专注录音页面。</p></div></header>
      <div class="form-section"><div class="form-section-title"><CalendarDaysIcon /><div><h3>讨论与手术信息</h3><p>用于建立可检索的本地会议档案。</p></div></div>
        <div class="form-grid three">
          <label class="field"><span>讨论日期 *</span><input v-model="form.meeting_date" type="date" required /></label>
          <label class="field"><span>科室</span><input v-model.trim="form.department" /></label>
          <label class="field"><span>预计手术日期</span><input v-model="form.planned_surgery_date" type="date" /></label>
          <label class="field"><span>患者脱敏编号 *</span><input v-model.trim="form.patient_code" placeholder="例：P-20260805-01" required /></label>
          <label class="field"><span>手术名称 *</span><input v-model.trim="form.surgery_name" placeholder="例：腹腔镜胆囊切除术" required /></label>
          <label class="field"><span>手术部位</span><input v-model.trim="form.surgery_site" placeholder="例：腹部" /></label>
        </div>
      </div>
      <div class="form-section"><div class="form-section-title"><UsersIcon /><div><h3>讨论规模</h3><p>预期人数用于 CAM++ 讲话人聚类范围提示。</p></div></div>
        <div class="form-grid two compact-grid"><label class="field"><span>最少讲话人数</span><input v-model.number="form.expected_speaker_min" type="number" min="1" max="20" /></label><label class="field"><span>最多讲话人数</span><input v-model.number="form.expected_speaker_max" type="number" min="1" max="20" /></label></div>
      </div>
      <div class="form-section"><div class="form-section-title"><DocumentTextIcon /><div><h3>患者资料与讨论重点</h3><p>仅录入已脱敏且允许在院内系统中使用的信息。</p></div></div>
        <div class="form-grid two"><label class="field"><span>患者历史信息</span><textarea v-model.trim="form.patient_history" placeholder="既往史、过敏史、当前用药、关键检查结果等" /></label><label class="field"><span>本次重点问题</span><textarea v-model.trim="form.focus_questions" placeholder="例如：抗凝药停药时机、麻醉风险、替代方案等" /></label></div>
      </div>
      <div class="clinical-disclaimer">AI 生成内容仅用于会议记录与临床辅助参考，不构成诊断、治疗建议或法律依据；所有结果须由具备资质的医务人员复核。</div>
      <footer class="form-actions"><RouterLink class="button secondary" to="/">取消</RouterLink><button class="button primary" type="submit" :disabled="saving">{{ saving ? '创建中…' : '创建并进入会议录制' }} <ArrowRightIcon /></button></footer>
    </form>
  </section>
</template>
