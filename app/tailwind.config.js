/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#111827',
        muted: '#5b6472',
        line: '#e3e6ec',
        surface: '#f7f8fa',
        accent: '#1d4ed8',
        warn: '#b45309',
        bad: '#b91c1c',
        good: '#15803d',
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', 'Inter', 'Segoe UI', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
