/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      // Mirrors src/styles/theme.css CSS variables — see DESIGN.md for rationale.
      colors: {
        canvas: '#FAF8F4',
        surface: '#FFFFFF',
        line: '#EDE8E0',
        ink: '#1F1B16',
        muted: '#6B6257',
        primary: {
          DEFAULT: '#1F5D4C',
          hover: '#2E8168',
        },
        secondary: {
          DEFAULT: '#C4623F',
          hover: '#AD5636',
        },
        success: '#2E8168',
        warning: '#B7791F',
        error: '#B4442E',
        highlight: '#F0E3C4',
      },
      fontFamily: {
        display: ['"Fraunces Variable"', 'Fraunces', 'ui-serif', 'Georgia', 'serif'],
        sans: ['"Bricolage Grotesque Variable"', '"Bricolage Grotesque"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        display: ['3rem', { lineHeight: '1.05', letterSpacing: '-0.02em' }],
        h1: ['2.25rem', { lineHeight: '1.1', letterSpacing: '-0.02em' }],
        h2: ['1.5rem', { lineHeight: '1.2', letterSpacing: '-0.02em' }],
        h3: ['1.25rem', { lineHeight: '1.3', letterSpacing: '-0.01em' }],
        body: ['1rem', { lineHeight: '1.5' }],
        small: ['0.875rem', { lineHeight: '1.5' }],
        caption: ['0.75rem', { lineHeight: '1.4' }],
      },
      maxWidth: {
        content: '1120px',
      },
      boxShadow: {
        warm: '0 1px 2px rgba(31,27,22,.04), 0 8px 24px rgba(31,27,22,.05)',
        'warm-lift': '0 2px 4px rgba(31,27,22,.05), 0 12px 32px rgba(31,27,22,.07)',
      },
      transitionTimingFunction: {
        standard: 'cubic-bezier(0.22, 1, 0.36, 1)',
        entrance: 'cubic-bezier(0.16, 1, 0.3, 1)',
        emphasized: 'cubic-bezier(0.22, 1, 0.36, 1)', // alias, kept for back-compat
      },
      transitionDuration: {
        fast: '180ms',
        base: '280ms',
        slow: '500ms',
      },
      animation: {
        'fade-in': 'fadeIn 0.28s ease-out',
        'stage-reveal': 'stageReveal 220ms cubic-bezier(0.22, 1, 0.36, 1)',
        'stage-pop': 'stagePop 260ms cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        stageReveal: {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        stagePop: {
          '0%': { opacity: '0', transform: 'scale(0.5)' },
          '60%': { opacity: '1', transform: 'scale(1.15)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
    },
  },
  plugins: [require('@tailwindcss/forms')],
}
