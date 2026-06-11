<script setup lang="ts">
import { Zap, Clock, Monitor, Sparkles } from 'lucide-vue-next'

const vReveal = useScrollReveal()

// Static placeholders describing the product capability — no client/usage claims.
const metrics = [
  { icon: Clock, value: '2–5 мин', label: 'на сборку одной видеолекции' },
  { icon: Zap, value: '10×', label: 'экономия времени против ручной записи' },
  { icon: Monitor, value: '1080p', label: 'HD-видео с синхронной озвучкой' },
  { icon: Sparkles, value: 'PPTX → MP4', label: 'полностью автоматический конвейер' },
]
</script>

<template>
  <section class="px-6 py-12 max-w-5xl mx-auto">
    <div
      v-reveal
      class="rounded-3xl bg-gradient-to-br from-violet-700 via-violet-600 to-indigo-600 p-8 md:p-10 text-white shadow-hero"
    >
      <p class="text-center text-sm font-medium text-white/70">
        Создано для преподавателей, методистов и онлайн-школ
      </p>
      <div class="mt-8 grid grid-cols-2 lg:grid-cols-4 gap-8">
        <div v-for="(m, i) in metrics" :key="i" class="text-center">
          <div class="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl bg-white/15">
            <component :is="m.icon" class="h-5 w-5" />
          </div>
          <div class="text-2xl md:text-3xl font-semibold leading-none tabular-nums">{{ m.value }}</div>
          <div class="mt-1.5 text-xs text-white/75 leading-snug">{{ m.label }}</div>
        </div>
      </div>
    </div>
  </section>
</template>
