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
      colors: {
        brand: {
          DEFAULT: '#4f46e5',
          dark: '#4338ca',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
