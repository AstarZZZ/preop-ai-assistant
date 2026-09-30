export async function api(path, options = {}) {
  const response = await fetch(path, options)
  const text = await response.text()
  let payload = {}
  try { payload = text ? JSON.parse(text) : {} } catch { payload = { error: text || '响应格式错误' } }
  if (!response.ok) throw new Error(payload.error || payload.detail || `请求失败（${response.status}）`)
  return payload
}

export function jsonOptions(method, body) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const formatDate = value => value ? value.slice(0, 10).replaceAll('-', '.') : '—'

export function formatDuration(ms = 0) {
  const total = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return [hours, minutes, seconds].map(value => String(value).padStart(2, '0')).join(':')
}

export const statusLabel = {
  draft: '待录制', uploaded: '待识别', transcribed: '已转写', reviewing: '校对中',
  analyzed: '待确认', confirmed: '已归档',
}
