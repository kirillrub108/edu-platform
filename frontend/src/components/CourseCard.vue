<script setup lang="ts">
import { BookOpen, ArrowRight } from 'lucide-vue-next'
import StatusBadge from './StatusBadge.vue'

const props = defineProps<{
  course: {
    id: string
    title: string
    description?: string | null
    is_published: boolean
    lessons_count?: number
    gradient_idx?: number
  }
  to?: string
}>()

const gradients = [
  'from-violet-500 via-purple-500 to-fuchsia-500',
  'from-indigo-500 via-violet-500 to-purple-500',
  'from-purple-500 via-fuchsia-500 to-pink-500',
  'from-violet-600 via-indigo-500 to-blue-500',
]
const gradient = computed(() => gradients[(props.course.gradient_idx ?? 0) % gradients.length])

const lessonsCount = computed(() => props.course.lessons_count ?? 0)
const lessonsLabel = computed(() => {
  const n = lessonsCount.value
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'урок'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'урока'
  return 'уроков'
})
</script>

<template>
  <NuxtLink
    :to="to ?? `/courses/${course.id}`"
    class="group block bg-white rounded-2xl overflow-hidden border border-gray-100 transition-all duration-150
           hover:scale-[1.01] hover:border-violet-200 shadow-soft hover:shadow-soft-hover"
  >
    <div :class="['h-20 bg-gradient-to-br', gradient]"></div>
    <div class="p-5">
      <h3 class="font-semibold text-gray-900 text-lg leading-tight">{{ course.title }}</h3>
      <p v-if="course.description" class="text-sm text-gray-500 mt-1.5 line-clamp-2">
        {{ course.description }}
      </p>
      <div class="flex items-center justify-between mt-4">
        <div class="flex items-center gap-1.5 text-xs text-gray-500">
          <BookOpen class="w-3.5 h-3.5" />
          {{ lessonsCount }} {{ lessonsLabel }}
        </div>
        <StatusBadge :status="course.is_published ? 'published' : 'draft'" />
      </div>
      <div class="mt-4 pt-4 border-t border-gray-100 flex items-center justify-between text-sm">
        <span class="text-violet-700 font-medium group-hover:text-violet-600">Открыть</span>
        <ArrowRight class="w-4 h-4 text-violet-700 transform transition group-hover:translate-x-0.5" />
      </div>
    </div>
  </NuxtLink>
</template>
