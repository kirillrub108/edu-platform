<script setup lang="ts">
import { ChevronLeft, Download, FileText, Paperclip, Search } from 'lucide-vue-next'
import { formatBytes } from '~/utils/assignments'

/**
 * Whole-course knowledge base, grouped module → lesson.
 *
 * One request instead of N per-lesson calls. Search is client-side over the
 * already-loaded titles — the tree is fetched whole (no pagination, see
 * docs/KNOWN_PROBLEMS.md), so there is nothing to ask the server for.
 * Note bodies are NOT in this payload; the title links to the lesson.
 */
definePageMeta({ middleware: ['auth', 'teacher'], layout: 'workspace' })

const route = useRoute()
const store = useCourseKnowledgeStore()

const courseId = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id[0]! : (id as string)
})

const query = ref('')

const matches = (text: string): boolean =>
  text.toLowerCase().includes(query.value.trim().toLowerCase())

// A lesson survives the filter when its own title matches, or any of its
// materials/notes do — so searching a filename still shows where it lives.
const filtered = computed(() => {
  const tree = store.tree
  if (!tree) return []
  const needle = query.value.trim()
  if (!needle) return tree.modules

  return tree.modules
    .map((module) => ({
      ...module,
      lessons: module.lessons.filter(
        (lesson) =>
          matches(module.title) ||
          matches(lesson.title) ||
          lesson.materials.some((m) => matches(m.title) || matches(m.original_filename)) ||
          lesson.notes.some((n) => matches(n.title)),
      ),
    }))
    .filter((module) => module.lessons.length > 0)
})

const totals = computed(() => {
  const lessons = store.tree?.modules.flatMap((m) => m.lessons) ?? []
  return {
    materials: lessons.reduce((sum, l) => sum + l.materials.length, 0),
    notes: lessons.reduce((sum, l) => sum + l.notes.length, 0),
  }
})

onMounted(() => store.fetchTree(courseId.value))
watch(courseId, (id) => store.fetchTree(id))
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center gap-3 flex-wrap">
      <NuxtLink
        :to="`/courses/${courseId}`"
        class="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition"
      >
        <ChevronLeft class="w-4 h-4" />
        К курсу
      </NuxtLink>
    </div>

    <div>
      <h1 class="text-2xl font-semibold text-gray-900">База знаний курса</h1>
      <p v-if="store.tree" class="text-sm text-gray-500 mt-1">
        {{ store.tree.course_title }} · {{ totals.materials }} файлов · {{ totals.notes }} конспектов
      </p>
    </div>

    <p v-if="store.error" class="text-sm text-rose-600 bg-rose-50 rounded-xl px-4 py-2.5">
      {{ store.error }}
    </p>

    <div v-if="store.loading" class="text-sm text-gray-500">Загрузка…</div>

    <template v-else-if="store.tree">
      <div class="relative max-w-md">
        <Search class="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          v-model="query"
          type="search"
          placeholder="Поиск по названию модуля, урока, файла или конспекта"
          class="w-full rounded-xl border border-gray-200 pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-200 focus:border-violet-300"
        />
      </div>

      <p v-if="!filtered.length" class="text-sm text-gray-500">
        {{ query.trim() ? 'Ничего не найдено.' : 'В курсе пока нет материалов и конспектов.' }}
      </p>

      <section
        v-for="module in filtered"
        :key="module.id"
        class="bg-white rounded-2xl border border-gray-100 shadow-soft"
      >
        <h2 class="text-base font-semibold text-gray-900 px-6 py-4 border-b border-gray-100">
          {{ module.title }}
        </h2>

        <div
          v-for="lesson in module.lessons"
          :key="lesson.id"
          class="px-6 py-4 border-b border-gray-50 last:border-b-0"
        >
          <div class="flex items-center gap-2 mb-3 flex-wrap">
            <NuxtLink
              :to="`/lessons/${lesson.id}?tab=knowledge`"
              class="text-sm font-medium text-gray-900 hover:text-violet-700 transition"
            >
              {{ lesson.title }}
            </NuxtLink>
            <span
              class="text-[11px] px-1.5 py-0.5 rounded-md font-medium"
              :class="lesson.content_type === 'text'
                ? 'bg-sky-50 text-sky-700'
                : 'bg-violet-50 text-violet-700'"
            >
              {{ lesson.content_type === 'text' ? 'текст' : lesson.content_type === 'quiz' ? 'тест' : 'видео' }}
            </span>
          </div>

          <p
            v-if="!lesson.materials.length && !lesson.notes.length"
            class="text-xs text-gray-400"
          >
            Ничего не прикреплено.
          </p>

          <ul v-if="lesson.notes.length" class="space-y-1 mb-2">
            <li
              v-for="note in lesson.notes"
              :key="note.id"
              class="flex items-center gap-2 text-sm text-gray-700"
            >
              <FileText class="w-3.5 h-3.5 text-violet-400 shrink-0" />
              <NuxtLink
                :to="`/lessons/${lesson.id}?tab=knowledge`"
                class="hover:text-violet-700 transition truncate"
              >
                {{ note.title }}
              </NuxtLink>
            </li>
          </ul>

          <ul v-if="lesson.materials.length" class="space-y-1">
            <li
              v-for="material in lesson.materials"
              :key="material.id"
              class="flex items-center gap-2 text-sm text-gray-700"
            >
              <Paperclip class="w-3.5 h-3.5 text-gray-400 shrink-0" />
              <span class="truncate">{{ material.title }}</span>
              <span class="text-xs text-gray-400 shrink-0">
                {{ formatBytes(material.size_bytes) }}
              </span>
              <span
                v-if="material.is_inline"
                class="text-[11px] px-1.5 py-0.5 rounded-md bg-gray-100 text-gray-500 shrink-0"
              >
                в тексте
              </span>
              <a
                :href="material.download_url"
                target="_blank"
                rel="noopener noreferrer"
                class="ml-auto p-1.5 rounded-lg text-violet-600 hover:bg-violet-50 shrink-0"
                :aria-label="`Скачать ${material.title}`"
              >
                <Download class="w-4 h-4" />
              </a>
            </li>
          </ul>
        </div>
      </section>
    </template>
  </div>
</template>
