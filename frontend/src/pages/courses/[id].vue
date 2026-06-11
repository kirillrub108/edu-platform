<script setup lang="ts">
import { Trash2, Archive } from 'lucide-vue-next'

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

const coverInputRef = ref<HTMLInputElement | null>(null)
const uploadingCover = ref(false)
const showArchiveConfirm = ref(false)
const archivingCourse = ref(false)
const restoringCourse = ref(false)
const deletingModule = ref<Record<string, boolean>>({})
const deletingLesson = ref<Record<string, boolean>>({})

const activeTab = ref<'content' | 'access'>('content')
const accessLoading = ref(false)
const accessError = ref('')
const copiedCode = ref(false)
const copiedLink = ref(false)
let codeTimeout: ReturnType<typeof setTimeout> | null = null
let linkTimeout: ReturnType<typeof setTimeout> | null = null

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
    await navigateTo(`/lessons/${lesson.id}`)
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при добавлении урока'
  } finally {
    addingLesson.value[moduleId] = false
  }
}

const joinLinkUrl = computed(() =>
  import.meta.client ? `${window.location.origin}/join?courseId=${course.value?.id}` : ''
)
const joinCodeUrl = computed(() =>
  import.meta.client ? `${window.location.origin}/join?code=${course.value?.access_code}` : ''
)

const copyCode = async (text: string) => {
  await navigator.clipboard.writeText(text)
  copiedCode.value = true
  if (codeTimeout) clearTimeout(codeTimeout)
  codeTimeout = setTimeout(() => { copiedCode.value = false }, 2000)
}

const copyLink = async (text: string) => {
  await navigator.clipboard.writeText(text)
  copiedLink.value = true
  if (linkTimeout) clearTimeout(linkTimeout)
  linkTimeout = setTimeout(() => { copiedLink.value = false }, 2000)
}

const setMode = async (mode: 'link' | 'code') => {
  if (!course.value || course.value.access_mode === mode || accessLoading.value) return
  accessLoading.value = true
  accessError.value = ''
  try {
    if (mode === 'link') {
      course.value = await apiFetch(`/courses/${route.params.id}/access-code`, { method: 'DELETE' })
    } else {
      course.value = await apiFetch(`/courses/${route.params.id}/access-code/generate`, { method: 'POST' })
    }
  } catch (e: any) {
    accessError.value = e?.data?.detail ?? 'Ошибка при изменении режима доступа'
  } finally {
    accessLoading.value = false
  }
}

const regenerateCode = async () => {
  if (!course.value || accessLoading.value) return
  accessLoading.value = true
  accessError.value = ''
  try {
    course.value = await apiFetch(`/courses/${route.params.id}/access-code/generate`, { method: 'POST' })
  } catch (e: any) {
    accessError.value = e?.data?.detail ?? 'Ошибка при обновлении кода'
  } finally {
    accessLoading.value = false
  }
}

const statusLabel: Record<string, string> = {
  draft: 'Черновик',
  analyzing: 'Анализируется',
  ready_for_edit: 'Готов к правке',
  processing: 'Генерируется',
  published: 'Готов',
  error: 'Ошибка',
}

const statusColor: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-500',
  analyzing: 'bg-violet-100 text-violet-700',
  ready_for_edit: 'bg-indigo-100 text-indigo-700',
  processing: 'bg-yellow-100 text-yellow-700',
  published: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-600',
}

const uploadCover = async (e: Event) => {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  uploadingCover.value = true
  actionError.value = ''
  try {
    const form = new FormData()
    form.append('file', file)
    const res = await apiFetch<{ cover_url: string }>(
      `/uploads/cover?course_id=${route.params.id}`,
      { method: 'POST', body: form },
    )
    course.value.cover_url = res.cover_url
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при загрузке обложки'
  } finally {
    uploadingCover.value = false
    if (coverInputRef.value) coverInputRef.value.value = ''
  }
}

const archiveCourse = async () => {
  archivingCourse.value = true
  actionError.value = ''
  try {
    // DELETE is a soft delete (archive): the course moves to the dashboard's
    // "Архив" section and is purged after 30 days unless restored.
    await apiFetch(`/courses/${route.params.id}`, { method: 'DELETE' })
    await navigateTo('/dashboard')
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при архивации курса'
    showArchiveConfirm.value = false
  } finally {
    archivingCourse.value = false
  }
}

const restoreCourse = async () => {
  restoringCourse.value = true
  actionError.value = ''
  try {
    await apiFetch(`/courses/${route.params.id}/restore`, { method: 'PATCH' })
    await load()
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при восстановлении курса'
  } finally {
    restoringCourse.value = false
  }
}

const deleteModule = async (moduleId: string) => {
  if (!window.confirm('Удалить модуль вместе со всеми его уроками?')) return
  deletingModule.value[moduleId] = true
  actionError.value = ''
  try {
    await apiFetch(`/courses/${route.params.id}/modules/${moduleId}`, { method: 'DELETE' })
    await load()
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при удалении модуля'
  } finally {
    deletingModule.value[moduleId] = false
  }
}

const deleteLesson = async (lessonId: string) => {
  if (!window.confirm('Удалить урок?')) return
  deletingLesson.value[lessonId] = true
  actionError.value = ''
  try {
    await apiFetch(`/lessons/${lessonId}`, { method: 'DELETE' })
    await load()
  } catch (e: any) {
    actionError.value = e?.data?.detail ?? 'Ошибка при удалении урока'
  } finally {
    deletingLesson.value[lessonId] = false
  }
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
      <div class="flex gap-4">
        <!-- Cover -->
        <div
          class="relative w-20 h-20 rounded-xl overflow-hidden border border-gray-200 flex-shrink-0 cursor-pointer group"
          :class="uploadingCover ? 'opacity-50' : ''"
          @click="coverInputRef?.click()"
        >
          <img
            v-if="course.cover_url"
            :src="course.cover_url"
            alt="Обложка"
            class="w-full h-full object-cover"
          />
          <div v-else class="w-full h-full bg-gray-100 flex items-center justify-center text-gray-400 text-xs text-center px-1">
            Обложка
          </div>
          <div class="absolute inset-0 bg-black/30 opacity-0 group-hover:opacity-100 transition flex items-center justify-center text-white text-xs">
            {{ uploadingCover ? '…' : 'Изменить' }}
          </div>
        </div>
        <input
          ref="coverInputRef"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          class="hidden"
          @change="uploadCover"
        />

        <div>
          <NuxtLink to="/dashboard" class="text-sm text-brand hover:underline mb-1 block">← Мои курсы</NuxtLink>
          <h1 class="text-2xl font-semibold">{{ course.title }}</h1>
          <p v-if="course.description" class="text-gray-500 mt-1 text-sm">{{ course.description }}</p>
        </div>
      </div>

      <div class="flex flex-col items-end gap-2">
        <div class="flex gap-2">
          <NuxtLink
            :to="`/courses/${route.params.id}/gradebook`"
            class="px-4 py-1.5 border rounded-lg text-sm hover:bg-gray-50 transition text-center"
          >
            Журнал оценок
          </NuxtLink>

          <!-- Active course: publish toggle + archive -->
          <template v-if="!course.is_archived">
            <button
              class="px-4 py-1.5 border rounded-lg text-sm hover:bg-gray-50 transition disabled:opacity-50 min-w-36 text-center"
              :disabled="publishing"
              @click="togglePublish"
            >
              {{ publishing ? '…' : course.is_published ? 'Снять с публикации' : 'Опубликовать' }}
            </button>
            <UiButton
              v-if="!showArchiveConfirm"
              variant="danger"
              size="sm"
              :disabled="archivingCourse || loading"
              @click="showArchiveConfirm = true"
            >
              В архив
            </UiButton>
            <template v-else>
              <span class="text-xs text-amber-600 self-center max-w-44 text-right leading-tight">
                В архив? Студенты потеряют доступ, через 30 дней курс будет удалён.
              </span>
              <UiButton variant="danger" size="sm" :loading="archivingCourse" @click="archiveCourse">
                В архив
              </UiButton>
              <button
                class="text-sm text-gray-500 hover:text-gray-700"
                @click="showArchiveConfirm = false"
              >
                Отмена
              </button>
            </template>
          </template>

          <!-- Archived course: restore only -->
          <UiButton
            v-else
            variant="primary"
            size="sm"
            :loading="restoringCourse"
            @click="restoreCourse"
          >
            Восстановить
          </UiButton>
        </div>

        <span
          v-if="course.is_archived"
          class="text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded-full inline-flex items-center gap-1"
        >
          <Archive class="w-3 h-3" />
          В архиве<template v-if="course.days_until_purge != null"> · удалится через {{ course.days_until_purge }} дн.</template>
        </span>
        <span
          v-else-if="course.is_published"
          class="text-xs text-green-600 bg-green-50 px-2 py-0.5 rounded-full"
        >
          опубликован
        </span>
      </div>
    </div>

    <p v-if="actionError" class="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
      {{ actionError }}
    </p>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 border-b">
      <button
        class="px-4 py-2 text-sm font-medium transition border-b-2 -mb-px"
        :class="activeTab === 'content'
          ? 'border-brand text-brand'
          : 'border-transparent text-gray-500 hover:text-gray-700'"
        @click="activeTab = 'content'"
      >
        Содержание
      </button>
      <button
        class="px-4 py-2 text-sm font-medium transition border-b-2 -mb-px"
        :class="activeTab === 'access'
          ? 'border-brand text-brand'
          : 'border-transparent text-gray-500 hover:text-gray-700'"
        @click="activeTab = 'access'"
      >
        Доступ
      </button>
    </div>

    <!-- Tab: Содержание -->
    <section v-if="activeTab === 'content'">
      <div v-if="!course.modules?.length" class="text-sm text-gray-400 italic mb-4 px-1">
        Добавьте первый модуль чтобы начать создавать уроки
      </div>

      <div class="space-y-4 mb-4">
        <div v-for="m in course.modules" :key="m.id" class="bg-white border rounded-xl p-4">
          <div class="font-medium text-gray-800 mb-3 flex items-center gap-2">
            <span class="text-brand/60 text-xs font-mono">M</span>
            {{ m.title }}
            <button
              class="ml-auto text-gray-300 hover:text-red-500 transition disabled:opacity-40"
              :disabled="deletingModule[m.id] || loading"
              @click="deleteModule(m.id)"
            >
              <Trash2 class="w-4 h-4" />
            </button>
          </div>

          <ul class="space-y-1 mb-3">
            <li v-for="l in m.lessons" :key="l.id" class="flex items-center gap-1 group/lesson">
              <NuxtLink
                :to="`/lessons/${l.id}`"
                class="flex-1 flex items-center justify-between rounded-lg px-3 py-2 hover:bg-gray-50 transition group border border-transparent hover:border-gray-200"
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
              <button
                class="text-gray-300 hover:text-red-500 transition opacity-0 group-hover/lesson:opacity-100 disabled:opacity-40 px-1"
                :disabled="deletingLesson[l.id] || loading"
                @click="deleteLesson(l.id)"
              >
                <Trash2 class="w-4 h-4" />
              </button>
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

    <!-- Tab: Доступ -->
    <section v-else-if="activeTab === 'access'">
      <p v-if="!course.is_published" class="mb-5 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
        Курс не опубликован — ученики не смогут записаться, пока вы его не опубликуете.
      </p>

      <p v-if="accessError" class="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
        {{ accessError }}
      </p>

      <div class="space-y-5">
        <div>
          <p class="text-sm text-gray-600 mb-2">Код доступа — продиктуйте или отправьте ученикам:</p>
          <div class="flex gap-2 items-center">
            <div class="flex-1 bg-gray-50 border rounded-xl px-6 py-4 text-3xl font-mono tracking-widest text-center text-gray-800 select-all">
              {{ course.access_code }}
            </div>
            <button
              class="px-3 py-2 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition whitespace-nowrap"
              @click="copyCode(course.access_code)"
            >
              {{ copiedCode ? '✓ Скопировано' : 'Копировать' }}
            </button>
          </div>
          <div class="flex items-center justify-end gap-2 mt-2">
            <p class="text-xs text-gray-400 flex-1">После обновления старые ссылки перестанут работать.</p>
            <button
              class="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2 transition disabled:opacity-50"
              :disabled="accessLoading"
              @click="regenerateCode"
            >
              {{ accessLoading ? '…' : 'Обновить код' }}
            </button>
          </div>
        </div>

        <div>
          <p class="text-sm text-gray-600 mb-2">Или поделитесь ссылкой:</p>
          <div class="flex gap-2">
            <code class="flex-1 bg-gray-50 border rounded-lg px-3 py-2 text-sm font-mono text-gray-700 truncate">
              {{ joinCodeUrl }}
            </code>
            <button
              class="px-3 py-2 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition whitespace-nowrap"
              @click="copyLink(joinCodeUrl)"
            >
              {{ copiedLink ? '✓ Скопировано' : 'Копировать' }}
            </button>
          </div>
        </div>
      </div>
    </section>

  </div>
</template>
