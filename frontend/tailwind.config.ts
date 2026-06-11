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
          DEFAULT: 'oklch(0.55 0.215 282 / <alpha-value>)', // = --accent / violet-700
          dark: 'oklch(0.4 0.19 270 / <alpha-value>)',       // = --accent-deep / violet-800
        },
        // Accent realigned to the landing's exact indigo hue 282 (oklch), replacing
        // Tailwind's default violet (~hue 292). Driven by CSS vars in src/app.vue
        // (L C H components) so value tweaks hot-reload; only this wiring needs the
        // one-time config sync. indigo/purple/fuchsia stay on Tailwind defaults.
        violet: {
          50: 'oklch(var(--c-violet-50) / <alpha-value>)',
          100: 'oklch(var(--c-violet-100) / <alpha-value>)',
          200: 'oklch(var(--c-violet-200) / <alpha-value>)',
          300: 'oklch(var(--c-violet-300) / <alpha-value>)',
          400: 'oklch(var(--c-violet-400) / <alpha-value>)',
          500: 'oklch(var(--c-violet-500) / <alpha-value>)',
          600: 'oklch(var(--c-violet-600) / <alpha-value>)',
          700: 'oklch(var(--c-violet-700) / <alpha-value>)',
          800: 'oklch(var(--c-violet-800) / <alpha-value>)',
          900: 'oklch(var(--c-violet-900) / <alpha-value>)',
        },
        // Neutral ramp retinted to match the landing's purple-tinted palette
        // (ink / ink-soft / muted / line / lavender bg). Values are CSS vars
        // defined in src/app.vue:root as "R G B" channels — so the scale is
        // driven at runtime and tweaks hot-reload (only this tailwind.config
        // wiring needs the one-time image rebuild). The accent (violet/indigo/
        // purple/fuchsia) is left on Tailwind defaults — it already matches the
        // landing's --accent / --accent-deep / --accent-fuchsia.
        gray: {
          50: 'rgb(var(--c-gray-50) / <alpha-value>)',
          100: 'rgb(var(--c-gray-100) / <alpha-value>)',
          200: 'rgb(var(--c-gray-200) / <alpha-value>)',
          300: 'rgb(var(--c-gray-300) / <alpha-value>)',
          400: 'rgb(var(--c-gray-400) / <alpha-value>)',
          500: 'rgb(var(--c-gray-500) / <alpha-value>)',
          600: 'rgb(var(--c-gray-600) / <alpha-value>)',
          700: 'rgb(var(--c-gray-700) / <alpha-value>)',
          800: 'rgb(var(--c-gray-800) / <alpha-value>)',
          900: 'rgb(var(--c-gray-900) / <alpha-value>)',
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
