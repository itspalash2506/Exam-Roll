export function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatBytes(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

export function formatPercent(value) {
  return `${Math.round((value ?? 0) * 100)}%`
}

export function formatDocType(type) {
  if (!type) return '—'
  return type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
