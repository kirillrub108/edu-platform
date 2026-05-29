<script setup lang="ts">
import { Upload, Brain, Volume2, Video, ArrowRight } from 'lucide-vue-next'

const steps = [
  { icon: Upload, title: 'Загрузите PPTX', desc: 'Презентация и текст доклада. Никаких шаблонов и ручных настроек.' },
  { icon: Brain, title: 'ИИ-анализ слайдов', desc: 'Vision-модель Yandex распознаёт и осмысляет каждый слайд, готовит скрипт.' },
  { icon: Volume2, title: 'Озвучка Yandex SpeechKit', desc: 'Нейросетевой синтез речи проговаривает скрипт естественным голосом.' },
  { icon: Video, title: 'Готовое MP4', desc: 'Слайды и озвучка собираются в видеолекцию автоматически.' },
]
</script>

<template>
  <section id="how" class="px-6 py-20 max-w-6xl mx-auto scroll-mt-20">
    <div class="text-center max-w-2xl mx-auto">
      <h2 class="text-2xl md:text-3xl font-semibold tracking-tight">Как это работает</h2>
      <p class="mt-3 text-gray-600">Четыре шага от файла презентации до опубликованной видеолекции.</p>
    </div>

    <ol class="mt-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
      <li
        v-for="(s, i) in steps"
        :key="i"
        class="group relative rounded-2xl border border-violet-100 bg-white p-6 shadow-soft transition-all duration-200 hover:-translate-y-1 hover:shadow-soft-hover"
      >
        <div class="flex items-center justify-between">
          <div class="grid h-11 w-11 place-items-center rounded-xl bg-violet-100 text-violet-700 transition-colors group-hover:bg-violet-600 group-hover:text-white">
            <component :is="s.icon" class="h-5 w-5" />
          </div>
          <span class="text-3xl font-semibold leading-none text-violet-100">0{{ i + 1 }}</span>
        </div>
        <h3 class="mt-4 font-semibold text-gray-900">{{ s.title }}</h3>
        <p class="mt-1.5 text-sm leading-relaxed text-gray-500">{{ s.desc }}</p>

        <ArrowRight
          v-if="i < steps.length - 1"
          class="absolute -right-5 top-1/2 hidden h-5 w-5 -translate-y-1/2 text-violet-200 lg:block"
        />
      </li>
    </ol>
  </section>
</template>
