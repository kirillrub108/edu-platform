<script setup lang="ts">
import { storeToRefs } from 'pinia'

const route = useRoute()
const { apiFetch } = useApi()
const quizStore = useQuizStore()
const { questions, selectedAnswers, result, loading: quizLoading, submitting, error: quizError, hasQuiz, allAnswered } = storeToRefs(quizStore)

const course = ref<any>(null)
const activeLesson = ref<any>(null)
const loading = ref(true)
const isCompleted = ref(false)

const load = async () => {
  loading.value = true
  try {
    course.value = await apiFetch<any>(`/students/courses/${route.params.id}`)
    activeLesson.value = course.value?.modules?.[0]?.lessons?.[0] ?? null
  } finally {
    loading.value = false
  }
}

const selectLesson = async (lesson: any) => {
  activeLesson.value = lesson
  isCompleted.value = false
  quizStore.reset()
  await quizStore.fetchQuestions(lesson.id)
}

const markComplete = async () => {
  if (!activeLesson.value) return
  await apiFetch(`/students/lessons/${activeLesson.value.id}/complete`, { method: 'POST' })
  isCompleted.value = true
}

onMounted(async () => {
  await load()
  await restoreScroll()
  if (activeLesson.value) {
    await quizStore.fetchQuestions(activeLesson.value.id)
  }
})
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>
  <div v-else-if="course" class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <aside class="md:col-span-1 bg-white border rounded p-3">
      <h2 class="font-semibold mb-2">{{ course.title }}</h2>
      <div v-for="m in course.modules" :key="m.id" class="mb-3">
        <div class="text-sm font-medium text-gray-700">{{ m.title }}</div>
        <ul class="mt-1 text-sm">
          <li
            v-for="l in m.lessons"
            :key="l.id"
            class="cursor-pointer px-2 py-1 rounded hover:bg-gray-100"
            :class="{ 'bg-gray-100 font-medium': activeLesson?.id === l.id }"
            @click="selectLesson(l)"
          >
            {{ l.title }}
          </li>
        </ul>
      </div>
    </aside>

    <section class="md:col-span-2 space-y-3">
      <LessonPlayer v-if="activeLesson" :lesson="activeLesson" />

      <button
        v-if="activeLesson && !isCompleted"
        class="px-3 py-1 bg-brand text-white rounded text-sm"
        @click="markComplete"
      >
        Отметить пройденным
      </button>

      <!-- Quiz section — shown after lesson is marked complete -->
      <div v-if="isCompleted && hasQuiz" class="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
        <!-- Result screen -->
        <template v-if="result">
          <div class="flex items-center gap-3">
            <span
              class="text-xl font-semibold"
              :class="result.passed ? 'text-green-600' : 'text-red-600'"
            >
              {{ result.passed ? 'Тест пройден' : 'Тест не пройден' }}
            </span>
            <span class="text-gray-500 text-sm">
              {{ result.correct_count }} / {{ result.total }}
              ({{ Math.round(result.score * 100) }}%)
            </span>
          </div>

          <div class="space-y-3">
            <div
              v-for="(q, idx) in questions"
              :key="q.id"
              class="rounded-lg border p-3"
              :class="result.questions[idx]?.correct ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'"
            >
              <p class="text-sm font-medium mb-2">{{ q.question }}</p>
              <ul class="space-y-1">
                <li
                  v-for="(opt, oi) in q.options"
                  :key="oi"
                  class="text-sm px-2 py-1 rounded"
                  :class="{
                    'bg-green-200 font-medium': oi === result.questions[idx]?.correct_index,
                    'bg-red-200': oi === selectedAnswers[q.id] && oi !== result.questions[idx]?.correct_index,
                  }"
                >
                  {{ opt }}
                </li>
              </ul>
            </div>
          </div>
        </template>

        <!-- Quiz form -->
        <template v-else>
          <h3 class="font-semibold text-base">Тест по уроку</h3>

          <div v-if="quizLoading" class="text-gray-500 text-sm">Загрузка вопросов…</div>

          <div v-else class="space-y-4">
            <div v-for="q in questions" :key="q.id" class="space-y-2">
              <p class="text-sm font-medium">{{ q.question }}</p>
              <ul class="space-y-1">
                <li
                  v-for="(opt, oi) in q.options"
                  :key="oi"
                  class="flex items-center gap-2 text-sm cursor-pointer"
                  @click="quizStore.selectAnswer(q.id, oi)"
                >
                  <span
                    class="w-4 h-4 rounded-full border flex-shrink-0 flex items-center justify-center"
                    :class="selectedAnswers[q.id] === oi ? 'border-brand bg-brand' : 'border-gray-300'"
                  >
                    <span v-if="selectedAnswers[q.id] === oi" class="w-2 h-2 rounded-full bg-white" />
                  </span>
                  {{ opt }}
                </li>
              </ul>
            </div>
          </div>

          <p v-if="quizError" class="text-sm text-red-600">{{ quizError }}</p>

          <button
            class="px-4 py-2 bg-brand text-white rounded text-sm disabled:opacity-50"
            :disabled="submitting || !allAnswered"
            @click="quizStore.submitAnswers()"
          >
            {{ submitting ? '…' : 'Отправить ответы' }}
          </button>
          <p v-if="!allAnswered && questions.length > 0" class="text-xs text-gray-400">
            Ответьте на все вопросы перед отправкой
          </p>
        </template>
      </div>

      <div v-else-if="isCompleted && !hasQuiz" class="text-sm text-green-600">
        Урок завершён.
      </div>
    </section>
  </div>
</template>
