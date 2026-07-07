import { useState } from 'react'
import { motion } from 'framer-motion'
import { ChevronDown, ChevronUp, Palette } from 'lucide-react'
import { durations, easings, useReducedMotion } from '../../lib/motion.js'

const FONTS = ['Arial', 'Calibri', 'Times New Roman', 'Tahoma', 'Trebuchet MS']

const DEFAULT_STYLE = {
  header_bg_color: '#1F4E79',
  header_font_color: '#FFFFFF',
  alt_row_color: '#D6E4F0',
  count_row_color: '#FFD700',
  font_name: 'Arial',
  font_size: 10,
  column_width: 26,
}

export { DEFAULT_STYLE }

function LivePreview({ style }) {
  const headerStyle = {
    backgroundColor: style.header_bg_color,
    color: style.header_font_color,
    fontFamily: style.font_name,
    fontSize: `${style.font_size}px`,
    padding: '6px 12px',
    fontWeight: 600,
  }
  const dataStyle = {
    fontFamily: style.font_name,
    fontSize: `${style.font_size}px`,
    padding: '5px 12px',
  }
  const altStyle = { ...dataStyle, backgroundColor: style.alt_row_color }
  const countStyle = {
    ...dataStyle,
    backgroundColor: style.count_row_color,
    fontWeight: 700,
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line text-caption">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <td style={headerStyle}>Roll No.</td>
            <td style={headerStyle}>MBAN101<br /><span style={{ fontWeight: 400, opacity: 0.75 }}>Mathematics</span></td>
            <td style={headerStyle}>MBAN102<br /><span style={{ fontWeight: 400, opacity: 0.75 }}>Physics</span></td>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={dataStyle}>A001</td>
            <td style={{ ...dataStyle, textAlign: 'center' }}>✓</td>
            <td style={{ ...dataStyle, textAlign: 'center' }}>✓</td>
          </tr>
          <tr>
            <td style={altStyle}>A002</td>
            <td style={{ ...altStyle, textAlign: 'center' }}>✓</td>
            <td style={{ ...altStyle, textAlign: 'center' }}>—</td>
          </tr>
          <tr>
            <td style={countStyle}>Count</td>
            <td style={{ ...countStyle, textAlign: 'center' }}>2</td>
            <td style={{ ...countStyle, textAlign: 'center' }}>1</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export default function StylePanel({ style = DEFAULT_STYLE, onChange }) {
  const [open, setOpen] = useState(false)
  const reduced = useReducedMotion()

  const set = (key, val) => onChange?.({ ...style, [key]: val })

  return (
    <div className="rounded-2xl border border-line bg-surface shadow-warm overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors duration-fast hover:bg-highlight/20"
      >
        <div className="flex items-center gap-2.5">
          <Palette size={18} className="text-primary" />
          <span className="text-small font-semibold text-ink">Customize Excel Style</span>
        </div>
        {open ? <ChevronUp size={16} className="text-muted" /> : <ChevronDown size={16} className="text-muted" />}
      </button>

      {open && (
        <motion.div
          initial={{ opacity: 0, y: reduced ? 0 : -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: durations.base, ease: easings.entrance }}
          className="border-t border-line px-5 py-5 space-y-5"
        >
          {/* Color pickers */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: 'Header Background', key: 'header_bg_color' },
              { label: 'Header Font', key: 'header_font_color' },
              { label: 'Alternate Row', key: 'alt_row_color' },
              { label: 'Count Row', key: 'count_row_color' },
            ].map(({ label, key }) => (
              <label key={key} className="space-y-1.5">
                <span className="text-caption text-muted">{label}</span>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={style[key] ?? '#000000'}
                    onChange={(e) => set(key, e.target.value)}
                    className="h-8 w-10 cursor-pointer rounded-lg border border-line p-0.5"
                  />
                  <span className="font-mono text-caption text-muted">{style[key]}</span>
                </div>
              </label>
            ))}
          </div>

          {/* Font selector */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label className="space-y-1.5">
              <span className="text-caption text-muted">Font Family</span>
              <select
                value={style.font_name}
                onChange={(e) => set('font_name', e.target.value)}
                className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {FONTS.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </label>

            <label className="space-y-1.5">
              <span className="text-caption text-muted">Font Size ({style.font_size}pt)</span>
              <input
                type="range"
                min={8}
                max={14}
                value={style.font_size}
                onChange={(e) => set('font_size', Number(e.target.value))}
                className="mt-2 w-full accent-primary"
              />
              <div className="flex justify-between text-caption text-muted">
                <span>8</span><span>14</span>
              </div>
            </label>

            <label className="space-y-1.5">
              <span className="text-caption text-muted">Column Width ({style.column_width})</span>
              <input
                type="range"
                min={15}
                max={40}
                value={style.column_width}
                onChange={(e) => set('column_width', Number(e.target.value))}
                className="mt-2 w-full accent-primary"
              />
              <div className="flex justify-between text-caption text-muted">
                <span>15</span><span>40</span>
              </div>
            </label>
          </div>

          {/* Live preview */}
          <div className="space-y-2">
            <p className="text-caption font-medium uppercase tracking-wide text-muted">Preview</p>
            <LivePreview style={style} />
          </div>
        </motion.div>
      )}
    </div>
  )
}
