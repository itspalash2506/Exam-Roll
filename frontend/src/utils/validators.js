const ALLOWED_EXTS = ['.pdf', '.xlsx']
const MAX_BYTES = 50 * 1024 * 1024

export function validateFile(file) {
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  if (!ALLOWED_EXTS.includes(ext))
    return `File type "${ext}" is not supported. Use PDF or XLSX.`
  if (file.size > MAX_BYTES)
    return `File is too large (${(file.size / 1024 ** 2).toFixed(1)} MB). Max 50 MB.`
  return null
}
