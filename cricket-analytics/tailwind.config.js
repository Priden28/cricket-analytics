/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['"Fraunces"', 'Georgia', 'serif'],
        body: ['"Inter Tight"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      colors: {
        ink: {
          950: '#0a0d0b',
          900: '#11150f',
          800: '#1a1f17',
          700: '#252b21',
          600: '#363d31',
        },
        willow: {
          50:  '#f0f5ec',
          100: '#dde9d2',
          200: '#bcd2a6',
          300: '#9bbc7a',
          400: '#7aa654',
          500: '#5e8b3d',
          600: '#4a6e30',
          700: '#3a5626',
          800: '#2c411d',
          900: '#1f2e15',
        },
        cream: {
          50:  '#faf7f0',
          100: '#f3ecdc',
          200: '#e8dcbb',
          300: '#d9c693',
          400: '#c4a866',
        },
        ember: {
          500: '#c8553d',
          600: '#a8412f',
        },
      },
      boxShadow: {
        'card': '0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px -8px rgba(0,0,0,0.5)',
        'inset-line': 'inset 0 -1px 0 rgba(255,255,255,0.06)',
      },
    },
  },
  plugins: [],
}
