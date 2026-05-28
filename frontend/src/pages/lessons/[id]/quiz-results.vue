<script setup lang="ts">
import { AlertCircle, ArrowLeft, Inbox, Pencil, RefreshCw, Search } from 'lucide-vue-next'
import type { QuizResultOut, QuizResultsResponse } from '~/types/analytics'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'bare' })

const route = useRoute()
const { apiFetch } = useApi()

const lessonId = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id[0] : (id as string)
})

const data = ref<QuizResultsResponse | null>(null)
const loading = ref(true)
const errMsg = ref('')

const search = ref('')

const editingStudentId = ref<string | null>(null)
const editScore = ref<number | null>(null)
const editReason = ref('')
const saving = ref(false)
const saveErr = ref('')
const scoreErr = ref('')

const panelStudent = ref<{ id: string; name: string; email: string } | null>(null)

const openPanel = (item: QuizResultOut) => {
  panelStudent.value = {
    id: item.student_id,
    name: item.student_full_name || item.student_email,
    email: item.student_email,
  }
}

const filteredItems = computed<QuizResultOut[]>(() => {
  if (!data.value) return []
  const q = search.value.trim().toLowerCase()
  if (!q) return data.value.items
  return data.value.items.filter(item => {
    const name = (item.student_full_name ?? '').toLowerCase()
    return name.includes(q) || item.student_email.toLowerCase().includes(q)
  })
})

const pct = (v: number | null): string => (v === null ? '—' : `${Math.round(v * 100)}%`)

const scoreColor = (v: number | null): string => {
  if (v === null) return 'text-gray-400'
  return v >= 0.6 ? 'text-emerald-600' : 'text-rose-600'
}

const statusBadge = (item: QuizResultOut): { label: string; cls: string } => {
  if (item.quiz_score === null) return { label: 'нет попыток', cls: 'bg-gray-100 text-gray-500' }
  if (item.is_completed) return { label: 'сдал', cls: 'bg-emerald-100 text-emerald-700' }
  return { label: 'не сдал', cls: 'bg-rose-100 text-rose-700' }
}

const fmtDate = (s: string | null): string => {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

const load = async () => {
  loading.value = true
  errMsg.value = ''
  try {
    data.value = await apiFetch<QuizResultsResponse>(
      `/teacher/lessons/${lessonId.value}/quiz-results`,
    )
  } catch (e: any) {
    if (e?.response?.status !== 401) {
      errMsg.value = e?.data?.detail ?? 'Не удалось загрузить результаты.'
    }
  } finally {
    loading.value = false
  }
}

const startEdit = (item: QuizResultOut) => {
  editingStudentId.value = item.student_id
  editScore.value = item.quiz_score !== null ? Math.round(item.quiz_score * 100) : null
  editReason.value = item.edit_reason ?? ''
  saveErr.value = ''
  scoreErr.value = ''
}

const cancelEdit = () => {
  editingStudentId.value = null
  editScore.value = null
  editReason.value = ''
  saveErr.value = ''
  scoreErr.value = ''
}

const save = async (studentId: string) => {
  scoreErr.value = ''
  saveErr.value = ''

  if (editScore.value === null || editScore.value === undefined || String(editScore.value) === '') {
    scoreErr.value = 'Введите балл'
    return
  }
  if (editScore.value < 0 || editScore.value > 100) {
    scoreErr.value = 'Балл от 0 до 100'
    return
  }

  saving.value = true
  try {
    const updated = await apiFetch<QuizResultOut>(
      `/teacher/lessons/${lessonId.value}/quiz-results/${studentId}`,
      {
        method: 'PATCH',
        body: { quiz_score: editScore.value / 100, reason: editReason.value || null },
      },
    )
    if (data.value) {
      const idx = data.value.items.findIndex(it => it.student_id === studentId)
      if (idx !== -1) data.value.items[idx] = updated
    }
    cancelEdit()
  } catch (e: any) {
    saveErr.value = e?.data?.detail ?? 'Ошибка при сохранении.'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="flex">
    <AppSidebar />
    <main class="flex-1 px-6 lg:px-10 py-8">
      <!-- Header -->
      <div class="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div class="flex items-center gap-3 min-w-0">
          <NuxtLink
            :to="`/lessons/${lessonId}`"
            class="shrink-0 w-8 h-8 rounded-xl border border-gray-200 bg-white text-gray-600 hover:text-violet-700 hover:border-violet-300 grid place-items-center transition"
          >
            <ArrowLeft class="w-4 h-4" />
          </NuxtLink>
          <div class="min-w-0">
            <div class="text-xs text-gray-500 mb-1 uppercase tracking-wide">Аналитика</div>
            <h1 class="text-2xl font-semibold text-gray-900 truncate">
              Результаты теста: {{ data?.lesson_title ?? '…' }}
            </h1>
          </div>
        </div>
        <UiButton variant="secondary" :loading="loading" @click="load">
          <template #icon><RefreshCw class="w-4 h-4" /></template>
          Обновить
        </UiButton>
      </div>

      <!-- Error -->
      <div
        v-if="errMsg"
        class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-2xl p-4 mb-6"
      >
        <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
        <div>{{ errMsg }}</div>
      </div>

      <!-- Search -->
      <div class="mb-4">
        <div class="relative max-w-sm">
          <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            v-model="search"
            type="text"
            placeholder="Поиск по имени студента"
            class="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-300"
          >
        </div>
      </div>

      <!-- Table -->
      <section class="bg-white border border-gray-100 rounded-2xl shadow-soft overflow-hidden">
        <!-- Loading skeleton -->
        <div v-if="loading" class="p-6 space-y-3">
          <div v-for="i in 6" :key="i" class="h-12 rounded-lg bg-gray-100 animate-pulse" />
        </div>

        <!-- Empty state -->
        <div
          v-else-if="!errMsg && filteredItems.length === 0"
          class="px-6 py-16 text-center text-gray-500"
        >
          <Inbox class="w-10 h-10 mx-auto mb-3 text-gray-300" />
          <p class="text-sm">
            {{ search ? 'Студент не найден' : 'Ни один студент ещё не проходил тест' }}
          </p>
        </div>

        <!-- Data table -->
        <table v-else-if="!loading && filteredItems.length > 0" class="w-full text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="px-4 py-3 text-left font-medium">Студент</th>
              <th class="px-4 py-3 text-center font-medium">Балл</th>
              <th class="px-4 py-3 text-center font-medium">Статус</th>
              <th class="px-4 py-3 text-left font-medium">Дата</th>
              <th class="px-4 py-3 text-center font-medium w-10" title="Правка учителем">
                <Pencil class="w-3.5 h-3.5 mx-auto" />
              </th>
              <th class="px-4 py-3 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-50">
            <template v-for="item in filteredItems" :key="item.student_id">
              <!-- Normal row -->
              <tr
                v-if="editingStudentId !== item.student_id"
                class="hover:bg-violet-50/30 transition cursor-pointer"
                @click="openPanel(item)"
              >
                <td class="px-4 py-3">
                  <div class="text-gray-900 font-medium">
                    {{ item.student_full_name || item.student_email }}
                  </div>
                  <div class="text-xs text-gray-500">{{ item.student_email }}</div>
                </td>
                <td class="px-4 py-3 text-center tabular-nums">
                  <span class="font-medium" :class="scoreColor(item.quiz_score)">
                    {{ pct(item.quiz_score) }}
                  </span>
                </td>
                <td class="px-4 py-3 text-center">
                  <span
                    class="text-xs px-2 py-0.5 rounded-full"
                    :class="statusBadge(item).cls"
                  >{{ statusBadge(item).label }}</span>
                </td>
                <td class="px-4 py-3 text-gray-500 tabular-nums">
                  {{ fmtDate(item.completed_at) }}
                </td>
                <td class="px-4 py-3 text-center">
                  <Pencil
                    v-if="item.edited_by_teacher"
                    class="w-3.5 h-3.5 mx-auto text-violet-500"
                    title="Балл скорректирован учителем"
                  />
                </td>
                <td class="px-4 py-3 text-right">
                  <button
                    class="text-xs text-violet-700 hover:text-violet-900 hover:underline transition"
                    @click.stop="startEdit(item)"
                  >
                    Изменить балл
                  </button>
                </td>
              </tr>

              <!-- Inline edit row -->
              <tr v-else class="bg-violet-50/50">
                <td colspan="6" class="px-4 py-4">
                  <div class="flex flex-wrap gap-4 items-start">
                    <div>
                      <div class="text-sm font-medium text-gray-700 mb-1">
                        {{ item.student_full_name || item.student_email }}
                      </div>
                      <label class="block text-xs text-gray-500 mb-1">Балл (%)</label>
                      <input
                        v-model.number="editScore"
                        type="number"
                        min="0"
                        max="100"
                        step="1"
                        class="w-24 px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                        :class="{ 'border-rose-400': scoreErr }"
                      >
                      <div v-if="scoreErr" class="text-xs text-rose-600 mt-1">{{ scoreErr }}</div>
                    </div>
                    <div class="flex-1 min-w-[200px]">
                      <label class="block text-xs text-gray-500 mb-1">Причина (необязательно)</label>
                      <textarea
                        v-model="editReason"
                        rows="2"
                        class="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                        placeholder="Комментарий к изменению балла"
                      />
                    </div>
                    <div class="flex items-start gap-2 pt-5">
                      <UiButton size="sm" :loading="saving" @click="save(item.student_id)">
                        Сохранить
                      </UiButton>
                      <UiButton size="sm" variant="secondary" :disabled="saving" @click="cancelEdit">
                        Отмена
                      </UiButton>
                    </div>
                  </div>
                  <div v-if="saveErr" class="text-xs text-rose-600 mt-2">{{ saveErr }}</div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </section>
    </main>

    <AttemptListPanel
      v-if="panelStudent"
      :lesson-id="lessonId"
      :student="panelStudent"
      @close="panelStudent = null"
    />
  </div>
</template>
