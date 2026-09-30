<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { XMarkIcon, MicrophoneIcon, FolderIcon, ArrowPathIcon, CheckCircleIcon } from '@heroicons/vue/24/outline'
import { api, jsonOptions } from '../services/api'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['update:open'])
const notify = inject('notify')
const devices = ref([])
const settings = ref({ storage_path: '', default_storage_path: '', microphone_id: 'default', microphone_label: '系统默认麦克风', sample_rate: '48000' })
const loading = ref(false)
const permissionState = ref('unknown')
const selectedDevice = computed(() => devices.value.find(item => item.deviceId === settings.value.microphone_id))

async function load() {
  settings.value = { ...settings.value, ...await api('/api/settings') }
  await refreshDevices(false)
}

async function refreshDevices(requestPermission = true) {
  if (!navigator.mediaDevices?.enumerateDevices) return
  if (requestPermission) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach(track => track.stop())
      permissionState.value = 'granted'
    } catch { permissionState.value = 'denied' }
  }
  const all = await navigator.mediaDevices.enumerateDevices()
  devices.value = all.filter(item => item.kind === 'audioinput')
  if (!settings.value.microphone_id && devices.value.length) settings.value.microphone_id = devices.value[0].deviceId
}

async function save() {
  loading.value = true
  try {
    const device = selectedDevice.value
    settings.value = { ...settings.value, ...await api('/api/settings', jsonOptions('POST', {
      ...settings.value,
      microphone_label: device?.label || settings.value.microphone_label || '系统默认麦克风',
    })) }
    localStorage.setItem('preop-microphone-id', settings.value.microphone_id || 'default')
    notify('设备与存储设置已保存')
    emit('update:open', false)
  } catch (error) { notify(error.message, 'error') } finally { loading.value = false }
}

function restoreDefault() { settings.value.storage_path = settings.value.default_storage_path }
watch(() => props.open, value => { if (value) load() })
onMounted(load)
</script>

<template>
  <Transition name="drawer">
    <div v-if="open" class="drawer-layer" @click.self="emit('update:open', false)">
      <section class="settings-drawer" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header>
          <div><span class="section-kicker">本地运行设置</span><h2 id="settings-title">设备与存储</h2></div>
          <button class="icon-button" type="button" aria-label="关闭设置" @click="emit('update:open', false)"><XMarkIcon /></button>
        </header>

        <div class="settings-section">
          <div class="settings-heading"><span><MicrophoneIcon /></span><div><h3>录音设备</h3><p>录音开始前选择会议室麦克风。</p></div></div>
          <label class="field"><span>麦克风输入</span>
            <select v-model="settings.microphone_id">
              <option value="default">系统默认麦克风</option>
              <option v-for="device in devices" :key="device.deviceId" :value="device.deviceId">{{ device.label || `麦克风 ${devices.indexOf(device) + 1}` }}</option>
            </select>
          </label>
          <div class="setting-row">
            <span :class="['permission-state', permissionState]"><CheckCircleIcon />{{ permissionState === 'granted' ? '麦克风权限已授权' : '需要获取麦克风权限' }}</span>
            <button class="text-button" type="button" @click="refreshDevices(true)"><ArrowPathIcon />检测设备</button>
          </div>
          <label class="field"><span>采样率</span><select v-model="settings.sample_rate"><option value="16000">16 kHz（语音识别）</option><option value="48000">48 kHz（推荐）</option></select></label>
        </div>

        <div class="settings-section">
          <div class="settings-heading"><span><FolderIcon /></span><div><h3>文件存储</h3><p>音频、转写与分析结果均保存在本机。</p></div></div>
          <label class="field"><span>本地存储目录</span><input v-model.trim="settings.storage_path" spellcheck="false" /></label>
          <p class="field-help">浏览器版不能安全读取任意系统目录；可填写服务器可访问的绝对路径。默认使用项目代码目录下的 data/uploads。</p>
          <button class="text-button" type="button" @click="restoreDefault"><ArrowPathIcon />恢复默认代码路径</button>
        </div>

        <div class="settings-note">设置只保存在本地数据库中。更换存储目录不会自动迁移既有录音。</div>
        <footer><button class="button secondary" type="button" @click="emit('update:open', false)">取消</button><button class="button primary" type="button" :disabled="loading" @click="save">{{ loading ? '保存中…' : '保存设置' }}</button></footer>
      </section>
    </div>
  </Transition>
</template>
