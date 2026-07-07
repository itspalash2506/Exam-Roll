// Shared motion tokens + variant builders for the "warm editorial" system.
// Every builder takes `reduced` (from framer-motion's useReducedMotion()) and
// strips transforms when true, keeping opacity-only fades — per
// prefers-reduced-motion: reduce.

import { useEffect, useRef, useState } from 'react'
import { animate, useReducedMotion } from 'framer-motion'

export const durations = { fast: 0.18, base: 0.28, slow: 0.5 }

export const easings = {
  standard: [0.22, 1, 0.36, 1],
  entrance: [0.16, 1, 0.3, 1],
}

// Page-level fade + 8px upward slide.
export function pageTransition(reduced) {
  return {
    initial: { opacity: 0, y: reduced ? 0 : 8 },
    animate: {
      opacity: 1,
      y: 0,
      transition: { duration: durations.base, ease: easings.standard },
    },
    exit: {
      opacity: 0,
      y: reduced ? 0 : -8,
      transition: { duration: durations.fast, ease: easings.standard },
    },
  }
}

// Wrap a list/grid of cards with this container variant, each child using staggerItem.
export function staggerContainer(reduced, stagger = 0.06) {
  return {
    hidden: {},
    show: {
      transition: { staggerChildren: reduced ? 0 : stagger },
    },
  }
}

export function staggerItem(reduced) {
  return {
    hidden: { opacity: 0, y: reduced ? 0 : 12 },
    show: {
      opacity: 1,
      y: 0,
      transition: { duration: durations.base, ease: easings.entrance },
    },
  }
}

// whileHover for interactive cards: lift 2px, border warms to primary accent.
export function cardHover(reduced) {
  if (reduced) return {}
  return {
    y: -2,
    borderColor: '#1F5D4C',
    transition: { duration: durations.fast, ease: easings.standard },
  }
}

// whileTap for buttons.
export function buttonTap(reduced) {
  return reduced ? {} : { scale: 0.98 }
}

export { useReducedMotion }

// Counts a number up from its previous value on change; respects reduced motion
// by jumping straight to the target instead of animating.
export function useCountUp(target, { duration = durations.slow } = {}) {
  const reduced = useReducedMotion()
  const numericTarget = typeof target === 'number' && !Number.isNaN(target) ? target : null
  const [value, setValue] = useState(numericTarget ?? 0)
  const prevRef = useRef(numericTarget ?? 0)

  useEffect(() => {
    if (numericTarget === null) return
    if (reduced) {
      setValue(numericTarget)
      prevRef.current = numericTarget
      return
    }
    const controls = animate(prevRef.current, numericTarget, {
      duration,
      ease: easings.standard,
      onUpdate: (v) => setValue(Math.round(v)),
    })
    prevRef.current = numericTarget
    return () => controls.stop()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericTarget, reduced, duration])

  return numericTarget === null ? target : value
}
