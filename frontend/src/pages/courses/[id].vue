<script setup lang="ts">
definePageMeta({ middleware: ['auth', 'teacher'] })

const route = useRoute()
const { apiFetch } = useApi()

const course = ref<any>(null)
const loading = ref(true)
const pageError = ref('')
const actionError = ref('')
const newModuleTitle = ref('')
const addingModule = ref(false)
const publishing = ref(false)
const newLessonTitle = ref<Record<string, string>>({})
const addingLesson = ref<Record<string, boolean>>({})

const load = async () => {
  loading.value = true
  pageError.value = ''
  try {
    course.value = await apiFetch<any>(`/courses/${route.params.id}`)
  } catch (e: any) {
    pageError.value = e?.data?.detail ?? 'Не удалось загрузить курс'
  } finally {
    loading.value = false
  }
}

const togglePublish = async () => {
  publishing.value = true
  actionError.value = ''
  try {
    await apiFetch(`/courses/${route.params.id}/publish`, { method: 'PUT' })
    await load()
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при изменении публикации'
  } finally {
    publishing.value = false
  }
}

const addModule = async () => {
  const title = newModuleTitle.value.trim()
  if (!title) {
    // Don't silently swallow the click — without this the user sees "ничего
    // не проходит" with no console output and no clue why.
    actionError.value = 'Введите название модуля'
    return
  }
  addingModule.value = true
  actionError.value = ''
  try {
    await apiFetch(`/courses/${route.params.id}/modules`, {
      method: 'POST',
      body: { title, order: course.value?.modules?.length ?? 0 },
    })
    newModuleTitle.value = ''
    await load()
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при добавлении модуля'
  } finally {
    addingModule.value = false
  }
}

const addLesson = async (moduleId: string) => {
  const title = newLessonTitle.value[moduleId]?.trim()
  if (!title) {
    actionError.value = 'Введите название урока'
    return
  }
  addingLesson.value[moduleId] = true
  actionError.value = ''
  try {
    const lesson = await apiFetch<any>('/lessons/', {
      method: 'POST',
      body: { title, module_id: moduleId, content_type: 'video', order: 0 },
    })
    newLessonTitle.value[moduleId] = ''
    // Navigate directly to lesson editor after creation
    await navigateTo(`/lessons/${lesson.id}`)
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при добавлении урока'
  } finally {
    // Reset on every exit (success or failure) so the button never stays
    // stuck in '…' if navigation throws or the user comes back to this page.
    addingLesson.value[moduleId] = false
  }
}

const statusLabel: Record<string, string> = {
  draft: 'Черновик',
  processing: 'Генерируется',
  published: 'Готов',
  error: 'Ошибка',
}

const statusColor: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-500',
  processing: 'bg-yellow-100 text-yellow-700',
  published: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-600',
}

onMounted(async () => {
  await load()
  await restoreScroll()
})
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>

  <div v-else-if="pageError" class="text-red-600 bg-red-50 border border-red-200 rounded-lg p-4">
    {{ pageError }}
  </div>

  <div v-else-if="course" class="max-w-3xl">

    <!-- Header -->
    <div class="flex items-start justify-between mb-6">
      <div>
        <NuxtLink to="/dashboard" class="text-sm text-brand hover:underline mb-1 block">← Мои курсы</NuxtLink>
        <h1 class="text-2xl font-semibold">{{ course.title }}</h1>
        <p v-if="course.description" class="text-gray-500 mt-1 text-sm">{{ course.description }}</p>
      </div>
      <div class="flex flex-col items-end gap-2">
        <button
          class="px-4 py-1.5 border rounded-lg text-sm hover:bg-gray-50 transition disabled:opacity-50 min-w-36 text-center"
          :disabled="publishing"
          @click="togglePublish"
        >
          {{ publishing ? '…' : course.is_published ? 'Снять с публикации' : 'Опубликовать' }}
        </button>
        <span
          v-if="course.is_published"
          class="text-xs text-green-600 bg-green-50 px-2 py-0.5 rounded-full"
        >
          опубликован
        </span>
      </div>
    </div>

    <p v-if="actionError" class="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
      {{ actionError }}
    </p>

    <!-- Modules -->
    <section>
      <h2 class="text-base font-semibold mb-3 text-gray-700">Модули и уроки</h2>

      <div v-if="!course.modules?.length" class="text-sm text-gray-400 italic mb-4 px-1">
        Добавьте первый модуль чтобы начать создавать уроки
      </div>

      <div class="space-y-4 mb-4">
        <div v-for="m in course.modules" :key="m.id" class="bg-white border rounded-xl p-4">
          <div class="font-medium text-gray-800 mb-3 flex items-center gap-2">
            <span class="text-brand/60 text-xs font-mono">M</span>
            {{ m.title }}
          </div>

          <ul class="space-y-1 mb-3">
            <li v-for="l in m.lessons" :key="l.id">
              <NuxtLink
                :to="`/lessons/${l.id}`"
                class="flex items-center justify-between rounded-lg px-3 py-2 hover:bg-gray-50 transition group border border-transparent hover:border-gray-200"
              >
                <span class="text-sm text-gray-800 group-hover:text-brand transition flex items-center gap-2">
                  <span class="text-gray-300 text-xs">▶</span>
                  {{ l.title }}
                </span>
                <span
                  class="text-xs px-2 py-0.5 rounded-full font-medium"
                  :class="statusColor[l.status] ?? 'bg-gray-100 text-gray-500'"
                >
                  {{ statusLabel[l.status] ?? l.status }}
                </span>
              </NuxtLink>
            </li>
            <li v-if="!m.lessons?.length" class="text-sm text-gray-400 italic px-3 py-1">
              нет уроков
            </li>
          </ul>

          <form class="flex gap-2" @submit.prevent="addLesson(m.id)">
            <input
              v-model="newLessonTitle[m.id]"
              placeholder="Название урока"
              required
              class="flex-1 border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
            />
            <button
              type="submit"
              class="px-3 py-1.5 bg-brand text-white rounded-lg text-sm disabled:opacity-50 whitespace-nowrap"
              :disabled="addingLesson[m.id] || !newLessonTitle[m.id]?.trim()"
            >
              {{ addingLesson[m.id] ? '…' : '+ Урок' }}
            </button>
          </form>
        </div>
      </div>

      <form class="flex gap-2" @submit.prevent="addModule">
        <input
          v-model="newModuleTitle"
          placeholder="Название нового модуля"
          required
          class="flex-1 border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
        />
        <button
          type="submit"
          class="px-4 py-2 bg-brand text-white rounded-lg text-sm disabled:opacity-50 whitespace-nowrap"
          :disabled="addingModule || !newModuleTitle.trim()"
        >
          {{ addingModule ? '…' : '+ Модуль' }}
        </button>
      </form>
    </section>
  </div>
</template>
