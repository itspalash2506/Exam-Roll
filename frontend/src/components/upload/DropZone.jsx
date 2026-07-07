import { useDropzone } from 'react-dropzone'
import { motion } from 'framer-motion'
import { CloudUpload } from 'lucide-react'
import clsx from 'clsx'
import { validateFile } from '../../utils/validators.js'
import { durations, easings, useReducedMotion } from '../../lib/motion.js'
import toast from 'react-hot-toast'

// Multi-file drop surface. Selected files are rendered by <FileList> below it,
// not inside the zone — dropping again APPENDS to the queue (the parent's
// onFiles handler dedupes by filename), so users can gather a batch across
// several drops. `compact` shrinks the zone once files are queued.
export default function DropZone({ onFiles, compact = false }) {
  const reduced = useReducedMotion()
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    multiple: true,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    },
    onDrop: (dropped) => {
      const valid = []
      for (const file of dropped) {
        const err = validateFile(file)
        if (err) toast.error(`${file.name}: ${err}`)
        else valid.push(file)
      }
      if (valid.length > 0) onFiles?.(valid)
    },
  })

  return (
    <div
      {...getRootProps()}
      className={clsx(
        'relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 px-8 text-center transition-all duration-base ease-standard',
        compact ? 'min-h-[120px] py-6' : 'min-h-[280px] py-12',
        isDragActive
          ? 'border-solid border-primary bg-primary/5 shadow-warm'
          : 'border-dashed border-line bg-surface hover:border-primary/50 hover:bg-highlight/10',
      )}
    >
      <input {...getInputProps()} />

      <motion.span
        className={clsx(
          'flex items-center justify-center rounded-full transition-colors duration-base',
          compact ? 'h-12 w-12' : 'h-20 w-20',
          isDragActive ? 'bg-primary/10' : 'bg-highlight/40',
        )}
        animate={isDragActive && !reduced ? { scale: 1.06 } : { scale: 1 }}
        transition={{ duration: durations.fast, ease: easings.standard }}
      >
        <CloudUpload size={compact ? 24 : 36} className="text-primary" strokeWidth={1.5} />
      </motion.span>

      {compact ? (
        <p className="mt-3 text-small text-muted">
          {isDragActive ? 'Drop to add to the batch' : 'Drop more files here, or click to browse'}
        </p>
      ) : (
        <>
          <h3 className="mt-5 font-display text-h3 font-medium text-ink">
            {isDragActive ? 'Drop them right here' : 'Drop your documents here'}
          </h3>
          <p className="mt-1.5 text-small text-muted">
            One or more .pdf / .xlsx attestation sheets, up to 50 MB each
          </p>
          <button
            type="button"
            className="mt-5 rounded-xl border border-primary px-5 py-2 text-small font-medium text-primary transition-colors duration-fast hover:bg-primary hover:text-canvas"
            onClick={(e) => e.stopPropagation()}
          >
            Browse Files
          </button>
        </>
      )}
    </div>
  )
}
