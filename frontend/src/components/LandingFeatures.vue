<script setup lang="ts">
import { Clock, Library, Volume2, FileText } from 'lucide-vue-next'

const vReveal = useScrollReveal()

const features = [
  { icon: Clock, title: 'Экономит часы препода', desc: 'Одна лекция — за 2–5 минут вместо 4–8 часов записи и бесконечных перезаписей.' },
  { icon: Library, title: 'Единый формат курса', desc: 'Все лекции выглядят и звучат одинаково — без разнобоя записей с разных микрофонов.' },
  { icon: FileText, title: 'Авто-текст по слайдам', desc: 'ИИ сам пишет закадровый текст по содержанию каждого слайда — или берёт ваш сценарий.' },
  { icon: Volume2, title: 'Авто-озвучка голосом', desc: 'Закадровый текст синтезируется естественным голосом — без диктора, студии и микрофона.' },
]
</script>

<template>
  <section id="features" class="px-6 py-20 max-w-6xl mx-auto scroll-mt-20">
    <div v-reveal class="text-center max-w-2xl mx-auto">
      <span class="text-xs font-semibold uppercase tracking-wider text-violet-600">Зачем это нужно</span>
      <h2 class="mt-2 text-2xl md:text-3xl font-semibold tracking-tight">Меньше рутины — больше курсов</h2>
      <p class="mt-3 text-gray-600">Подготовку видеолекции берут на себя ИИ-анализ слайдов и нейросетевая озвучка.</p>
    </div>

    <div class="mt-12 grid grid-cols-1 md:grid-cols-2 gap-4">
      <div
        v-for="(f, i) in features"
        :key="i"
        v-reveal
        :data-reveal-delay="i * 60"
        class="group flex gap-4 rounded-2xl border border-gray-100 bg-white p-6 shadow-soft transition-all duration-200 hover:-translate-y-1 hover:border-violet-100 hover:shadow-[0_10px_34px_rgba(124,58,237,0.14)]"
      >
        <div class="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-violet-100 text-violet-700 transition-all duration-200 group-hover:scale-105 group-hover:bg-violet-600 group-hover:text-white">
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
