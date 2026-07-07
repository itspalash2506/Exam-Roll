import { X } from 'lucide-react'
import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { durations, easings, useReducedMotion } from '../../lib/motion.js'

export default function Modal({ open, onClose, title, children, maxWidth = 'max-w-md' }) {
  const reduced = useReducedMotion()

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: durations.fast }}
          onClick={onClose}
        >
          <motion.div
            className={`w-full ${maxWidth} rounded-2xl bg-surface shadow-warm-lift border border-line`}
            initial={{ opacity: 0, y: reduced ? 0 : 12, scale: reduced ? 1 : 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: reduced ? 0 : 12, scale: reduced ? 1 : 0.98 }}
            transition={{ duration: durations.base, ease: easings.entrance }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-line px-6 py-4">
              <h2 className="font-display text-h3 font-medium text-ink">{title}</h2>
              <button
                onClick={onClose}
                className="rounded-xl p-1 text-muted transition-colors duration-fast hover:bg-line/60 hover:text-ink"
              >
                <X size={18} />
              </button>
            </div>
            <div className="px-6 py-4">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
