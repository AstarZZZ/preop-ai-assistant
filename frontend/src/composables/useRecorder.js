import { onBeforeUnmount, ref } from 'vue'

export function useRecorder() {
  const state = ref('idle')
  const elapsedMs = ref(0)
  const level = ref(0)
  const error = ref('')
  let stream
  let recorder
  let context
  let analyser
  let raf
  let timer
  let startedAt = 0
  let accumulated = 0
  const chunks = []

  function draw(canvas) {
    if (!canvas || !analyser) return
    const ctx = canvas.getContext('2d')
    const ratio = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    if (canvas.width !== Math.round(rect.width * ratio)) {
      canvas.width = Math.round(rect.width * ratio)
      canvas.height = Math.round(rect.height * ratio)
      ctx.scale(ratio, ratio)
    }
    const values = new Uint8Array(analyser.frequencyBinCount)
    analyser.getByteTimeDomainData(values)
    const width = rect.width
    const height = rect.height
    ctx.clearRect(0, 0, width, height)
    ctx.strokeStyle = '#dce6f1'
    ctx.lineWidth = 1
    for (let x = 0; x < width; x += 72) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke()
    }
    ctx.strokeStyle = '#1b8fa1'
    ctx.lineWidth = 1.8
    ctx.beginPath()
    let peak = 0
    values.forEach((value, index) => {
      const y = (value / 255) * height
      peak = Math.max(peak, Math.abs(value - 128) / 128)
      const x = (index / (values.length - 1)) * width
      index ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
    })
    ctx.stroke()
    level.value = Math.round(peak * 100)
    raf = requestAnimationFrame(() => draw(canvas))
  }

  async function start({ deviceId, sampleRate = 48000, canvas } = {}) {
    error.value = ''
    chunks.length = 0
    accumulated = 0
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: deviceId && deviceId !== 'default' ? { exact: deviceId } : undefined, sampleRate: Number(sampleRate), echoCancellation: true, noiseSuppression: true },
      })
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type)) || ''
      recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      recorder.addEventListener('dataavailable', event => { if (event.data?.size) chunks.push(event.data) })
      recorder.start(1000)
      context = new AudioContext({ sampleRate: Number(sampleRate) })
      analyser = context.createAnalyser()
      analyser.fftSize = 2048
      context.createMediaStreamSource(stream).connect(analyser)
      state.value = 'recording'
      startedAt = performance.now()
      timer = setInterval(() => { elapsedMs.value = accumulated + (state.value === 'recording' ? performance.now() - startedAt : 0) }, 250)
      draw(canvas)
    } catch (cause) {
      error.value = cause?.message || '无法访问麦克风'
      state.value = 'error'
      throw cause
    }
  }

  function pause() {
    if (recorder?.state !== 'recording') return
    recorder.pause()
    accumulated += performance.now() - startedAt
    state.value = 'paused'
  }

  function resume() {
    if (recorder?.state !== 'paused') return
    recorder.resume()
    startedAt = performance.now()
    state.value = 'recording'
  }

  async function snapshot() {
    if (!chunks.length) return null
    return new Blob([...chunks], { type: recorder?.mimeType || 'audio/webm' })
  }

  async function stop() {
    if (!recorder || recorder.state === 'inactive') return null
    if (state.value === 'recording') accumulated += performance.now() - startedAt
    await new Promise(resolve => { recorder.addEventListener('stop', resolve, { once: true }); recorder.stop() })
    state.value = 'stopped'
    clearInterval(timer)
    cancelAnimationFrame(raf)
    stream?.getTracks().forEach(track => track.stop())
    await context?.close()
    return new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
  }

  onBeforeUnmount(() => {
    clearInterval(timer); cancelAnimationFrame(raf)
    stream?.getTracks().forEach(track => track.stop())
    context?.close()
  })

  return { state, elapsedMs, level, error, start, pause, resume, stop, snapshot }
}
