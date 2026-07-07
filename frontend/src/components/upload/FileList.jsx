import { useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { FileText, Table, Upload, Plus, X } from 'lucide-react'
import Button from '../common/Button.jsx'
import { formatBytes } from '../../utils/formatters.js'
import { staggerContainer, staggerItem, useReducedMotion } from '../../lib/motion.js'
import { validateFile } from '../../utils/validators.js'
import toast from 'react-hot-toast'

function FileRow({ file, onRemove, reduced }) {
  const isPdf = file.name.split('.').pop().toLowerCase() === 'pdf'
  return (
    <motion.li
      variants={staggerItem(reduced)}
      exit={{ opacity: 0, x: reduced ? 0 : -8 }}
      layout={!reduced}
      className="flex items-center gap-3 rounded-xl border border-line bg-canvas px-4 py-2.5"
    >
      <span
        className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg ${
          isPdf ? 'bg-error/10' : 'bg-success/10'
        }`}
      >
        {isPdf ? (
          <FileText size={17} className="text-error" />
        ) : (
          <Table size={17} className="text-success" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-small font-medium text-ink">{file.name}</p>
        <p className="text-caption text-muted">
          {formatBytes(file.size)} · {isPdf ? 'PDF' : 'Excel'}
        </p>
      </div>
      <button
        type="button"
        onClick={() => onRemove(file.name)}
        title={`Remove ${file.name}`}
        className="rounded-full p-1.5 text-muted transition-colors duration-fast hover:bg-line/60 hover:text-ink"
      >
        <X size={14} />
      </button>
    </motion.li>
  )
}

// Editorial queue of files waiting to upload: one row per file with a remove
// button, a real total line, add-more / clear-all affordances, and the
// primary upload button whose label reflects the count.
export default function FileList({
  files,
  onAddFiles,
  onRemove,
  onClearAll,
  onUpload,
  uploading,
  uploadProgress,
}) {
  const reduced = useReducedMotion()
  const inputRef = useRef(null)

  if (!files || files.length === 0) return null

  const totalBytes = files.reduce((sum, f) => sum + f.size, 0)
  const countLabel = files.length === 1 ? '1 file' : `${files.length} files`

  const handlePicked = (e) => {
    const picked = Array.from(e.target.files ?? [])
    const valid = []
    for (const file of picked) {
      const err = validateFile(file)
      if (err) toast.error(`${file.name}: ${err}`)
      else valid.push(file)
    }
    if (valid.length > 0) onAddFiles?.(valid)
    e.target.value = '' // allow re-picking the same file after a remove
  }

  return (
    <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-display text-h3 font-medium text-ink">Ready to upload</h3>
        <span className="text-caption text-muted">
          {countLabel} · {formatBytes(totalBytes)} total
        </span>
      </div>

      <motion.ul
        variants={staggerContainer(reduced)}
        initial="hidden"
        animate="show"
        className="space-y-2"
      >
        <AnimatePresence initial={false}>
          {files.map((file) => (
            <FileRow key={file.name} file={file} onRemove={onRemove} reduced={reduced} />
          ))}
        </AnimatePresence>
      </motion.ul>

      <div className="flex items-center gap-4">
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.xlsx"
          className="hidden"
          onChange={handlePicked}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex items-center gap-1.5 text-caption font-medium text-primary hover:text-primary-hover"
        >
          <Plus size={13} /> Add more files
        </button>
        <button
          type="button"
          onClick={onClearAll}
          className="text-caption text-muted underline hover:text-ink"
        >
          Clear all
        </button>
      </div>

      {uploading && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-caption text-muted">
            <span>Uploading {countLabel}…</span>
            <span>{uploadProgress}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-primary transition-all duration-base ease-standard"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      )}

      <Button
        variant="primary"
        size="lg"
        className="w-full"
        onClick={onUpload}
        loading={uploading}
        disabled={uploading}
      >
        {uploading ? (
          'Uploading…'
        ) : (
          <>
            <Upload size={16} />
            Upload &amp; Analyze {countLabel}
          </>
        )}
      </Button>
    </div>
  )
}
