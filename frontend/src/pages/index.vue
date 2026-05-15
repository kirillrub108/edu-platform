<script setup lang="ts">
import { Upload, Sparkles, Video, ArrowRight, Play, Zap, Brain, Monitor } from 'lucide-vue-next'

definePageMeta({ layout: 'bare' })

useSeoMeta({
  title: 'EduAI — Создавайте видеокурсы с ИИ за минуты',
  description: 'Загрузите PPTX, получите готовый видеокурс с автоматическим скриптом и озвучкой. Без съёмок, без монтажа — за пару минут.',
  ogTitle: 'EduAI — Видеокурсы с ИИ',
  ogDescription: 'Загрузите PPTX, получите готовый видеокурс с автоматическим скриптом и озвучкой. Без съёмок, без монтажа.',
  twitterCard: 'summary',
})

// Auth is client-only; during prerender user is null → ctaTo defaults to /register.
// No fetchMe here — landing is a public page, no need to hit the API on every visit.
const auth = useAuthStore()

const ctaTo = computed(() => {
  if (!auth.isAuthenticated) return '/register'
  return auth.user?.role === 'teacher' ? '/dashboard' : '/student/dashboard'
})
const ctaLabel = computed(() => (auth.isAuthenticated ? 'В кабинет' : 'Начать бесплатно'))

const features = [
  { icon: Upload,   title: 'Загрузите PPTX',     desc: 'Просто перетащите презентацию — никаких шаблонов и настроек.' },
  { icon: Sparkles, title: 'AI прочтёт слайды',   desc: 'Vision-модель распознаёт каждый слайд и пишет скрипт лекции.' },
  { icon: Video,    title: 'Получите видео',      desc: 'TTS-озвучка, монтаж и сборка MP4 — за пару минут.' },
]
const stats = [
  { icon: Zap,     value: '10×',    label: 'быстрее ручной записи' },
  { icon: Brain,   value: 'GPT-4o', label: 'vision-анализ слайдов' },
  { icon: Monitor, value: 'HD',     label: '1080p, 48 kHz озвучка' },
]

onMounted(restoreScroll)
</script>

<template>
  <div class="relative">
    <!-- bg blobs -->
    <div class="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
      <div class="absolute -top-40 -left-40 w-[480px] h-[480px] rounded-full bg-violet-200/40 blur-3xl"></div>
      <div class="absolute top-20 -right-32 w-[420px] h-[420px] rounded-full bg-fuchsia-200/40 blur-3xl"></div>
      <div
        class="absolute inset-0"
        style="background-image: radial-gradient(rgba(109,40,217,0.08) 1px, transparent 1px); background-size: 28px 28px;"
      ></div>
    </div>

    <!-- hero -->
    <section class="px-6 py-20 lg:py-28 max-w-5xl mx-auto text-center">

      <h1 class="text-4xl md:text-6xl font-semibold tracking-tight leading-[1.05]">
        Создавайте видеокурсы<br />
        <span class="bg-gradient-to-r from-violet-600 via-purple-500 to-fuchsia-500 bg-clip-text text-transparent">
          с ИИ за минуты
        </span>
      </h1>
      <p class="text-lg text-gray-600 mt-6 max-w-2xl mx-auto">
        Загрузите PPTX, получите готовый видеокурс с автоматическим скриптом и озвучкой.
        Без съёмок, без монтажа, без боли.
      </p>
      <div class="flex flex-col sm:flex-row gap-3 justify-center mt-9">
        <NuxtLink :to="ctaTo">
          <UiButton variant="primary" size="lg">
            {{ ctaLabel }}
            <template #icon><ArrowRight class="w-4 h-4 order-last" /></template>
          </UiButton>
        </NuxtLink>
        <UiButton variant="secondary" size="lg">
          <template #icon><Play class="w-4 h-4" /></template>
          Посмотреть демо · 90 сек
        </UiButton>
      </div>
      <div class="mt-6 text-xs text-gray-500">
        Без карты. До 3 курсов на бесплатном тарифе.
      </div>
    </section>

    <!-- features -->
    <section class="px-6 pb-20 max-w-6xl mx-auto">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div
          v-for="(f, i) in features"
          :key="i"
          class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft"
        >
          <div class="w-11 h-11 rounded-xl bg-violet-100 grid place-items-center text-violet-700 mb-4">
            <component :is="f.icon" class="w-5 h-5" />
          </div>
          <h3 class="font-semibold text-gray-900 text-base">{{ f.title }}</h3>
          <p class="text-sm text-gray-500 mt-1.5 leading-relaxed">{{ f.desc }}</p>
        </div>
      </div>
    </section>

    <!-- how it works -->
    <section class="px-6 pb-20 max-w-5xl mx-auto">
      <h2 class="text-2xl font-semibold text-center mb-10">Три шага до готового курса</h2>
      <ol class="grid grid-cols-1 md:grid-cols-3 gap-3 relative">
        <li
          v-for="(f, i) in features"
          :key="i"
          class="relative bg-white rounded-2xl border border-violet-100 p-6"
        >
          <div
            class="text-5xl font-semibold bg-gradient-to-br from-violet-500 to-purple-500 bg-clip-text text-transparent leading-none mb-3"
          >
            0{{ i + 1 }}
          </div>
          <div class="font-semibold text-gray-900">{{ f.title }}</div>
          <p class="text-sm text-gray-500 mt-1">{{ f.desc }}</p>
          <ArrowRight
            v-if="i < features.length - 1"
            class="hidden md:block absolute -right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-violet-300"
          />
        </li>
      </ol>
    </section>

    <!-- stats -->
    <section class="px-6 pb-24 max-w-5xl mx-auto">
      <div
        class="rounded-2xl bg-gradient-to-br from-violet-700 via-violet-600 to-purple-500 text-white p-8 grid grid-cols-1 md:grid-cols-3 gap-8 shadow-hero"
      >
        <div v-for="(s, i) in stats" :key="i" class="flex items-center gap-4">
          <div class="w-12 h-12 rounded-xl bg-white/15 grid place-items-center">
            <component :is="s.icon" class="w-6 h-6" />
          </div>
          <div>
            <div class="text-3xl font-semibold leading-none">{{ s.value }}</div>
            <div class="text-sm text-white/80 mt-1">{{ s.label }}</div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
