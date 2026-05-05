/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          950: '#0f172a',
          900: '#162237',
          800: '#1e293b'
        },
        slatepro: {
          50: '#f8fafc',
          100: '#e2e8f0',
          200: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b'
        },
        action: {
          50: '#eff6ff',
          100: '#dbeafe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#2563eb',
          600: '#1d4ed8'
        }
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"Helvetica Neue"', '"Helvetica GE"', '"Noto Sans Georgian"', 'Arial', 'sans-serif']
      },
      boxShadow: {
        panel: '0 1px 2px rgba(15, 23, 42, 0.08)'
      },
      keyframes: {
        pulseSoft: {
          '0%, 100%': { opacity: '0.55', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.08)' }
        }
      },
      animation: {
        'pulse-soft': 'pulseSoft 1.6s ease-in-out infinite'
      }
    }
  },
  plugins: []
}
