import type { Config } from 'tailwindcss'

export default {
  content: [
    './src/components/**/*.{vue,js,ts}',
    './src/pages/**/*.vue',
    './src/composables/**/*.ts',
    './src/app.vue',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      colors: {
        brand: {
          DEFAULT: '#6d28d9', // violet-700 — primary CTA
          dark: '#5b21b6',    // violet-800
        },
      },
      boxShadow: {
        soft: '0 1px 3px rgba(0,0,0,0.04), 0 4px 16px rgba(109,40,217,0.06)',
        'soft-hover': '0 2px 6px rgba(0,0,0,0.05), 0 8px 24px rgba(109,40,217,0.10)',
        hero: '0 8px 32px rgba(109,40,217,0.25)',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-100% 0' },
          '100%': { backgroundPosition: '100% 0' },
        },
        indeterminate: {
          '0%': { left: '-33%' },
          '100%': { left: '100%' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.6s linear infinite',
        indeterminate: 'indeterminate 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config
