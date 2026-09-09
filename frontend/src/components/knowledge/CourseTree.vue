<script setup lang="ts">
import { ChevronDown, Download, FileText, Paperclip, Search } from 'lucide-vue-next'
import type { CourseKnowledgeLesson } from '~/stores/courseKnowledge'
import { formatBytes } from '~/utils/assignments'

/**
 * Whole-course knowledge base, grouped module → lesson. One component for both
 * cabinets: the collapsed rows come from the aggregate (note bodies are not in
 * it), and expanding a lesson mounts the per-lesson KnowledgePanel, which owns
 * reading the bodies and every write path. Editing affordances therefore stay
 * gated on the server's `can_edit`, never on a client-side role guess.
 *
 * Search is client-side over the already-loaded titles — the tree is fetched
 * whole (no pagination, see docs/KNOWN_PROBLEMS.md), so there is nothing to ask
 * the server for.
 */
const props = defineProps<{ courseId: string }>()

const store = useCourseKnowledgeStore()
const lessonStore = useLessonKnowledgeStore()

const query = ref('')
const expanded = ref<string | null>(null)

const matches = (text: string): boolean =>
  text.toLowerCase().includes(query.value.trim().toLowerCase())

// A lesson survives the filter when its own title matches, or its module's, or
// any of its materials/notes do — so searching a filename still shows where it
// lives.
const filtered = computed(() => {
  const tree = store.tree
  if (!tree) return []
  if (!query.value.trim()) return tree.modules

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

/**
 * Counts for a collapsed row. Once a lesson has been expanded its per-lesson
 * store is authoritative — an upload or a deleted note is reflected there
 * immediately, so the row stays honest without refetching the whole course.
 */
const counts = (lesson: CourseKnowledgeLesson): { materials: number; notes: number } => {
  const state = lessonStore.byLesson[lesson.id]
  if (state?.loaded) {
    return {
      materials: state.materials.filter((m) => !m.is_inline).length,
      notes: state.notes.length,
    }
  }
  return {
    materials: lesson.materials.filter((m) => !m.is_inline).length,
    notes: lesson.notes.length,
  }
}

const isEmpty = (lesson: CourseKnowledgeLesson): boolean => {
  const { materials, notes } = counts(lesson)
  return materials + notes === 0
}

const contentTypeLabel = (type: string): string =>
  type === 'text' ? 'текст' : type === 'quiz' ? 'тест' : 'видео'

const toggle = (lessonId: string): void => {
  expanded.value = expanded.value === lessonId ? null : lessonId
}

onMounted(() => store.fetchTree(props.courseId))
watch(() => props.courseId, (id) => {
  expanded.value = null
  store.fetchTree(id)
})
</script>

<template>
  <div class="space-y-5">
    <p v-if="store.error" class="text-sm text-rose-600 bg-rose-50 rounded-xl px-4 py-2.5">
      {{ store.error }}
    </p>

    <div v-if="store.loading" class="text-sm text-gray-500">Загрузка…</div>

    <template v-else-if="store.tree">
      <p class="text-sm text-gray-500">
        {{ store.tree.course_title }} · {{ totals.materials }} файлов ·
        {{ totals.notes }} конспектов
      </p>

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
        {{
          query.trim()
            ? 'Ничего не найдено.'
            : store.tree.can_edit
              ? 'В курсе пока нет ни одного урока — добавьте модуль и урок, чтобы прикреплять материалы.'
              : 'Преподаватель пока не добавил материалы к этому курсу.'
        }}
      </p>

      <section
        v-for="module in filtered"
        :key="module.id"
        class="bg-white rounded-2xl border border-gray-100 shadow-soft overflow-hidden"
      >
        <h2
          class="text-base font-semibold text-gray-900 px-6 py-4 border-b border-gray-100 flex items-center gap-2 flex-wrap"
        >
          <span>{{ module.title }}</span>
          <span
            v-if="!module.is_published"
            class="text-[11px] px-1.5 py-0.5 rounded-md font-medium bg-amber-100 text-amber-700"
          >Черновик</span>
        </h2>

        <div
          v-for="lesson in module.lessons"
          :key="lesson.id"
          class="border-b border-gray-50 last:border-b-0"
        >
          <button
            type="button"
            class="w-full px-6 py-4 flex items-center gap-2 flex-wrap text-left hover:bg-gray-50 transition"
            :aria-expanded="expanded === lesson.id"
            @click="toggle(lesson.id)"
          >
            <ChevronDown
              class="w-4 h-4 text-gray-400 shrink-0 transition-transform"
              :class="expanded === lesson.id && 'rotate-180'"
            />
            <span class="text-sm font-medium text-gray-900">{{ lesson.title }}</span>
            <span
              class="text-[11px] px-1.5 py-0.5 rounded-md font-medium"
              :class="lesson.content_type === 'text'
                ? 'bg-sky-50 text-sky-700'
                : 'bg-violet-50 text-violet-700'"
            >{{ contentTypeLabel(lesson.content_type) }}</span>
            <span
              v-if="!lesson.is_published"
              class="text-[11px] px-1.5 py-0.5 rounded-md font-medium bg-amber-100 text-amber-700"
            >Черновик</span>

            <span class="ml-auto flex items-center gap-3 text-xs text-gray-400 shrink-0">
              <span v-if="isEmpty(lesson)">пусто</span>
              <template v-else>
                <span v-if="counts(lesson).notes" class="flex items-center gap-1">
                  <FileText class="w-3.5 h-3.5" />{{ counts(lesson).notes }}
                </span>
                <span v-if="counts(lesson).materials" class="flex items-center gap-1">
                  <Paperclip class="w-3.5 h-3.5" />{{ counts(lesson).materials }}
                </span>
              </template>
            </span>
          </button>

          <!-- Mounted lazily: KnowledgePanel fetches that lesson's own knowledge
               base (note bodies included) and owns every write path. -->
          <div v-if="expanded === lesson.id" class="px-6 pb-6 bg-gray-50/60">
            <KnowledgePanel :lesson-id="lesson.id" />
          </div>

          <!-- Collapsed preview: downloads without leaving the course tab. -->
          <ul
            v-else-if="lesson.materials.length"
            class="px-6 pb-4 -mt-1 space-y-1"
          >
            <li
              v-for="material in lesson.materials.filter((m) => !m.is_inline)"
              :key="material.id"
              class="flex items-center gap-2 text-sm text-gray-700"
            >
              <Paperclip class="w-3.5 h-3.5 text-gray-400 shrink-0" />
              <span class="truncate">{{ material.title }}</span>
              <span class="text-xs text-gray-400 shrink-0">
                {{ formatBytes(material.size_bytes) }}
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
