import clsx from 'clsx'
import { motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import { buttonTap, durations, useReducedMotion } from '../../lib/motion.js'

const variantClasses = {
  primary: 'bg-primary text-canvas hover:bg-primary-hover',
  emphasis: 'bg-highlight text-ink hover:bg-highlight/70',
  secondary: 'border border-line text-ink bg-surface hover:bg-highlight/30',
  danger: 'bg-error text-canvas hover:bg-error/85',
  ghost: 'text-muted hover:bg-line/50 hover:text-ink',
}

const sizeClasses = {
  sm: 'px-3 py-1.5 text-caption rounded-xl',
  md: 'px-4 py-2 text-small rounded-xl',
  lg: 'px-6 py-2.5 text-body rounded-xl',
}

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  className,
  ...props
}) {
  const reduced = useReducedMotion()

  return (
    <motion.button
      whileTap={disabled || loading ? undefined : buttonTap(reduced)}
      transition={{ duration: durations.fast }}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-2 font-sans font-medium transition-colors duration-fast focus:outline-none focus:ring-2 focus:ring-primary/40 focus:ring-offset-1 focus:ring-offset-canvas disabled:opacity-50 disabled:cursor-not-allowed',
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    >
      {loading && <Loader2 size={14} className="animate-spin" />}
      {children}
    </motion.button>
  )
}
