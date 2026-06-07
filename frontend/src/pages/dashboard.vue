<script setup lang="ts">
import { Plus, BookOpen, CheckCircle2, Layers, AlertCircle } from 'lucide-vue-next'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'bare' })

const { apiFetch } = useApi()

// Grouped course state: kept here (matches the existing useApi-in-page pattern;
// no Pinia store needed) so archive/restore can move cards between sections
// without a full reload.
const groups = reactive<{ published: any[]; drafts: any[]; archived: any[] }>({
  published: [],
  drafts: [],
  archived: [],
})
const loading = ref(true)
const apiError = ref('')
const actionError = ref('')

const load = async () => {
  loading.value = true
  apiError.value = ''
  try {
    const data = await apiFetch<{ published: any[]; drafts: any[]; archived: any[] }>(
      '/courses/grouped',
    )
    groups.published = data.published ?? []
    groups.drafts = data.drafts ?? []
    groups.archived = data.archived ?? []
  } catch (e: any) {
    if (e?.response?.status !== 401) {
      apiError.value = 'Не удалось загрузить курсы. Проверьте, что бэкенд запущен.'
    }
  } finally {
    loading.value = false
  }
}

const sections = computed(() => [
  { key: 'published', title: 'Опубликованные', items: groups.published },
  { key: 'drafts', title: 'Черновики', items: groups.drafts },
  { key: 'archived', title: 'Архив', items: groups.archived },
])

const isEmpty = computed(
  () => !groups.published.length && !groups.drafts.length && !groups.archived.length,
)

const stats = computed(() => ({
  total: groups.published.length + groups.drafts.length,
  published: groups.published.length,
  lessons: [...groups.published, ...groups.drafts].reduce(
    (a, c) => a + (c.lessons_count ?? 0),
    0,
  ),
}))

const removeFrom = (arr: any[], id: string): any | null => {
  const i = arr.findIndex(c => c.id === id)
  return i !== -1 ? arr.splice(i, 1)[0] : null
}

const sortByCreatedDesc = (arr: any[]) =>
  arr.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

const archiveCourse = async (id: string) => {
  actionError.value = ''
  try {
    await apiFetch(`/courses/${id}`, { method: 'DELETE' })
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Не удалось архивировать курс'
    return
  }
  const course = removeFrom(groups.published, id) ?? removeFrom(groups.drafts, id)
  if (!course) {
    await load()
    return
  }
  course.is_archived = true
  course.days_until_purge = 30
  groups.archived.unshift(course)
}

const restoreCourse = async (id: string) => {
  actionError.value = ''
  let restored: any
  try {
    restored = await apiFetch<any>(`/courses/${id}/restore`, { method: 'PATCH' })
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Не удалось восстановить курс'
    return
  }
  removeFrom(groups.archived, id)
  const target = restored.is_published ? groups.published : groups.drafts
  target.unshift(restored)
  sortByCreatedDesc(target)
}

onMounted(async () => {
  await load()
  await restoreScroll()
})
</script>

<template>
  <div class="flex">
    <AppSidebar />
    <main class="flex-1 px-6 lg:px-10 py-8">
      <div class="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <div class="text-xs text-gray-500 mb-1 uppercase tracking-wide">Преподаватель</div>
          <h1 class="text-2xl font-semibold text-gray-900">Мои курсы</h1>
        </div>
        <NuxtLink to="/courses/create">
          <UiButton variant="primary">
            <template #icon><Plus class="w-4 h-4" /></template>
            Создать курс
          </UiButton>
        </NuxtLink>
      </div>

      <!-- compact stats bar -->
      <div class="grid grid-cols-3 gap-3 mb-6">
        <div class="bg-white border border-gray-100 rounded-2xl px-4 py-3 flex items-center gap-3 shadow-soft">
          <div class="w-9 h-9 rounded-lg bg-violet-100 text-violet-700 grid place-items-center">
            <BookOpen class="w-4 h-4" />
          </div>
          <div class="leading-tight">
            <div class="text-xl font-semibold tabular-nums">{{ stats.total }}</div>
            <div class="text-xs text-gray-500">всего курсов</div>
          </div>
        </div>
        <div class="bg-white border border-gray-100 rounded-2xl px-4 py-3 flex items-center gap-3 shadow-soft">
          <div class="w-9 h-9 rounded-lg bg-emerald-100 text-emerald-700 grid place-items-center">
            <CheckCircle2 class="w-4 h-4" />
          </div>
          <div class="leading-tight">
            <div class="text-xl font-semibold tabular-nums">{{ stats.published }}</div>
            <div class="text-xs text-gray-500">опубликовано</div>
          </div>
        </div>
        <div class="bg-white border border-gray-100 rounded-2xl px-4 py-3 flex items-center gap-3 shadow-soft">
          <div class="w-9 h-9 rounded-lg bg-fuchsia-100 text-fuchsia-700 grid place-items-center">
            <Layers class="w-4 h-4" />
          </div>
          <div class="leading-tight">
            <div class="text-xl font-semibold tabular-nums">{{ stats.lessons }}</div>
            <div class="text-xs text-gray-500">уроков всего</div>
          </div>
        </div>
      </div>

      <!-- error states -->
      <div
        v-if="apiError"
        class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-2xl p-4 mb-6"
      >
        <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
        <div>{{ apiError }}</div>
      </div>
      <div
        v-if="actionError"
        class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-2xl p-4 mb-6"
      >
        <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
        <div>{{ actionError }}</div>
      </div>

      <!-- 2-column layout: courses + analytics side-by-side on lg+ -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Courses column -->
        <div class="lg:col-span-2 space-y-8">
          <!-- loading -->
          <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <SkeletonCard v-for="i in 4" :key="i" />
          </div>

          <!-- empty (no courses at all) -->
          <div
            v-else-if="isEmpty"
            class="text-center py-16 bg-white rounded-2xl border border-gray-100"
          >
            <div class="w-14 h-14 rounded-2xl bg-violet-100 text-violet-700 grid place-items-center mx-auto mb-3">
              <BookOpen class="w-7 h-7" />
            </div>
            <h2 class="text-base font-semibold text-gray-900">Нет курсов пока</h2>
            <p class="text-sm text-gray-500 mt-1 mb-4">Создайте первый и загрузите слайды лекции.</p>
            <NuxtLink to="/courses/create">
              <UiButton variant="primary">
                <template #icon><Plus class="w-4 h-4" /></template>
                Создать курс
              </UiButton>
            </NuxtLink>
          </div>

          <!-- grouped sections (empty sections are hidden) -->
          <template v-else>
            <section v-for="section in sections" :key="section.key" v-show="section.items.length">
              <div class="flex items-center gap-2 mb-3">
                <h2 class="text-base font-semibold text-gray-900">{{ section.title }}</h2>
                <span class="text-xs font-medium text-gray-500 bg-gray-100 rounded-full px-2 py-0.5 tabular-nums">
                  {{ section.items.length }}
                </span>
              </div>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <CourseCard
                  v-for="(c, i) in section.items"
                  :key="c.id"
                  :course="{ ...c, gradient_idx: i }"
                  :show-actions="true"
                  @archive="archiveCourse"
                  @restore="restoreCourse"
                />
              </div>
            </section>
          </template>
        </div>

        <!-- Analytics column -->
        <aside class="lg:col-span-1">
          <QuizAnalyticsWidget />
        </aside>
      </div>
    </main>
  </div>
</template>
