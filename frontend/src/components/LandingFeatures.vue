<script setup lang="ts">
import { Zap, Volume2, Sparkles, Monitor } from 'lucide-vue-next'

const features = [
  { icon: Zap, title: 'В 10× быстрее', desc: 'Одна лекция — за 2–5 минут вместо 4–8 часов студийной записи и перезаписей.' },
  { icon: Volume2, title: 'Озвучка Yandex SpeechKit', desc: 'Нейросетевой синтез речи с естественными интонациями — без диктора и микрофона.' },
  { icon: Sparkles, title: 'Новейшие модели Yandex', desc: 'Анализ слайдов и генерация скрипта работают на актуальных ИИ-моделях Yandex.' },
  { icon: Monitor, title: 'Без студии и монтажа', desc: 'Ни камеры, ни видеоредактора — весь процесс происходит в браузере.' },
]
</script>

<template>
  <section class="px-6 py-20 max-w-6xl mx-auto">
    <div class="text-center max-w-2xl mx-auto">
      <h2 class="text-2xl md:text-3xl font-semibold tracking-tight">Почему это работает быстрее</h2>
      <p class="mt-3 text-gray-600">Рутину создания видеолекции берут на себя ИИ-модели и синтез речи Yandex.</p>
    </div>

    <div class="mt-12 grid grid-cols-1 md:grid-cols-2 gap-4">
      <div
        v-for="(f, i) in features"
        :key="i"
        class="group flex gap-4 rounded-2xl border border-gray-100 bg-white p-6 shadow-soft transition-all duration-200 hover:-translate-y-0.5 hover:shadow-soft-hover"
      >
        <div class="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-violet-100 text-violet-700 transition-colors group-hover:bg-violet-600 group-hover:text-white">
          <component :is="f.icon" class="h-5 w-5" />
        </div>
        <div>
          <h3 class="font-semibold text-gray-900">{{ f.title }}</h3>
          <p class="mt-1 text-sm leading-relaxed text-gray-500">{{ f.desc }}</p>
        </div>
      </div>
    </div>
  </section>
</template>
