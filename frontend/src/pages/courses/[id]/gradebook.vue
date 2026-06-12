<script setup lang="ts">
definePageMeta({ middleware: ['auth', 'teacher'] })

interface GradebookCell {
  lesson_id: string
  lesson_title: string
  content_type: string
  is_completed: boolean
  quiz_score: number | null
  effective_score: number | null
  manual_score: number | null
  teacher_comment: string | null
  completed_at: string | null
  progress_id: string | null
}

interface GradebookAssignmentColumn {
  assignment_id: string
  title: string
  lesson_id: string
  max_points: number
}

interface GradebookAssignmentCell {
  assignment_id: string
  status: string | null
  points_awarded: number | null
  score: number | null
  submission_id: string | null
}

interface GradebookStudentRow {
  student_id: string
  student_name: string
  student_email: string
  lessons: GradebookCell[]
  assignments: GradebookAssignmentCell[]
}

interface GradebookData {
  course_id: string
  course_title: string
  students: GradebookStudentRow[]
  assignments: GradebookAssignmentColumn[]
}

const route = useRoute()
const { apiFetch } = useApi()

const gradebook = ref<GradebookData | null>(null)
const loading = ref(true)
const pageError = ref('')

// Inline editor state
const editingKey = ref<string | null>(null)
const editingCell = ref<GradebookCell | null>(null)
const editorAnchor = ref<DOMRect | null>(null)
const editScore = ref('')
const editComment = ref('')
const saving = ref(false)
const saveError = ref('')
const scoreError = ref('')
const scoreInputRef = ref<HTMLInputElement | null>(null)

const courseId = computed(() => route.params.id as string)

const load = async () => {
  loading.value = true
  pageError.value = ''
  try {
    gradebook.value = await apiFetch<GradebookData>(`/courses/${courseId.value}/gradebook`)
  } catch (e: unknown) {
    pageError.value = (e as { data?: { detail?: string } })?.data?.detail ?? 'Не удалось загрузить журнал'
  } finally {
    loading.value = false
  }
}

const quizLessons = computed<GradebookCell[]>(() => {
  const first = gradebook.value?.students?.[0]
  if (!first) return []
  return first.lessons.filter(l => l.content_type === 'quiz')
})

const cellKey = (studentId: string, lessonId: string) => `${studentId}:${lessonId}`

// Tailwind color band classes; matches brand palette (soft, not aggressive)
const scoreBandClasses = (score: number | null): string => {
  if (score === null) return 'text-gray-300'
  if (score >= 80) return 'bg-emerald-50 text-emerald-700'
  if (score >= 60) return 'bg-amber-50 text-amber-700'
  return 'bg-rose-50 text-rose-700'
}

const cellByLesson = (row: GradebookStudentRow, lessonId: string): GradebookCell | null =>
  row.lessons.find(l => l.lesson_id === lessonId) ?? null

const assignmentColumns = computed<GradebookAssignmentColumn[]>(
  () => gradebook.value?.assignments ?? [],
)

const assignmentCell = (
  row: GradebookStudentRow,
  assignmentId: string,
): GradebookAssignmentCell | null =>
  row.assignments?.find(a => a.assignment_id === assignmentId) ?? null

// Reuse the quiz colour bands by mapping the 0..1 assignment score to 0..100.
const assignmentBandClasses = (score: number | null): string =>
  scoreBandClasses(score === null ? null : score * 100)

const averageFor = (row: GradebookStudentRow): number | null => {
  const scores = row.lessons
    .filter(l => l.content_type === 'quiz' && l.effective_score !== null)
    .map(l => l.effective_score as number)
  if (!scores.length) return null
  return scores.reduce((a, b) => a + b, 0) / scores.length
}

const openEditor = (cell: GradebookCell, studentId: string, ev: Event) => {
  if (cell.content_type !== 'quiz' || cell.progress_id === null) return
  editingKey.value = cellKey(studentId, cell.lesson_id)
  editingCell.value = cell
  editScore.value = cell.manual_score !== null ? String(cell.manual_score) : ''
  editComment.value = cell.teacher_comment ?? ''
  saveError.value = ''
  scoreError.value = ''
  const target = ev.currentTarget as HTMLElement | null
  editorAnchor.value = target?.getBoundingClientRect() ?? null
  nextTick(() => scoreInputRef.value?.focus())
}

const closeEditor = () => {
  editingKey.value = null
  editingCell.value = null
  editorAnchor.value = null
}

const validateScore = (): boolean => {
  if (editScore.value === '') {
    scoreError.value = ''
    return true
  }
  const n = Number(editScore.value)
  if (Number.isNaN(n) || n < 0 || n > 100) {
    scoreError.value = 'Балл должен быть от 0 до 100'
    return false
  }
  scoreError.value = ''
  return true
}

const patchAndApply = async (
  cell: GradebookCell,
  body: Record<string, unknown>,
): Promise<void> => {
  saving.value = true
  saveError.value = ''
  try {
    const updated = await apiFetch<GradebookCell>(
      `/courses/${courseId.value}/progress/${cell.progress_id}`,
      { method: 'PATCH', body },
    )
    if (gradebook.value) {
      for (const row of gradebook.value.students) {
        const idx = row.lessons.findIndex(l => l.lesson_id === cell.lesson_id)
        if (idx !== -1 && row.lessons[idx].progress_id === cell.progress_id) {
          row.lessons[idx] = updated
          break
        }
      }
    }
    closeEditor()
  } catch (e: unknown) {
    saveError.value = (e as { data?: { detail?: string } })?.data?.detail ?? 'Ошибка при сохранении'
  } finally {
    saving.value = false
  }
}

const saveCell = async () => {
  const cell = editingCell.value
  if (!cell || !validateScore()) return
  const body: Record<string, unknown> = {}
  // Empty score input is intentionally a no-op for manual_score (the explicit
  // way to clear an override is the "Сбросить балл" button).
  if (editScore.value !== '') body.manual_score = Number(editScore.value)
  const normalizedComment = editComment.value.trim() === '' ? null : editComment.value
  if (normalizedComment !== (cell.teacher_comment ?? null)) {
    body.teacher_comment = normalizedComment
  }
  if (Object.keys(body).length === 0) {
    closeEditor()
    return
  }
  await patchAndApply(cell, body)
}

const resetOverride = async () => {
  const cell = editingCell.value
  if (!cell) return
  // Explicit null → backend treats this as "clear manual_score" (Pydantic
  // exclude_unset keeps the field set; service writes None).
  await patchAndApply(cell, { manual_score: null })
}

const onEditorKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    e.preventDefault()
    closeEditor()
  }
}

// Computed style for the editor popover — clamped so it never overflows
// the viewport when the clicked cell sits near the bottom/right edges.
const editorStyle = computed<Record<string, string>>(() => {
  const anchor = editorAnchor.value
  if (!anchor) return {} as Record<string, string>
  const top = Math.min(anchor.bottom + 6, window.innerHeight - 280)
  const left = Math.min(anchor.left, window.innerWidth - 304)
  return { top: `${top}px`, left: `${left}px` }
})

onMounted(load)
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>

  <div
    v-else-if="pageError"
    class="text-rose-600 bg-rose-50 border border-rose-200 rounded-xl p-4"
    role="alert"
  >
    {{ pageError }}
  </div>

  <div v-else-if="gradebook" class="max-w-full">
    <div class="mb-5">
      <NuxtLink
        :to="`/courses/${courseId}`"
        class="text-sm text-brand hover:underline"
      >← Назад к курсу</NuxtLink>
      <h1 class="text-xl font-semibold mt-1 text-gray-900">
        Журнал оценок — {{ gradebook.course_title }}
      </h1>
      <p class="text-xs text-gray-500 mt-1">
        Кликните по баллу, чтобы выставить ручной override и комментарий.
        Прочерк означает, что студент ещё не проходил квиз.
      </p>
    </div>

    <div v-if="!quizLessons.length && !assignmentColumns.length" class="text-sm text-gray-500 bg-white border rounded-xl p-6 text-center">
      В курсе ещё нет квизов или заданий. Журнал отобразится после их добавления.
    </div>

    <div v-else-if="!gradebook.students.length" class="text-sm text-gray-500 bg-white border rounded-xl p-6 text-center">
      На курс ещё никто не записался.
    </div>

    <div
      v-else
      class="relative overflow-auto border border-gray-200 rounded-xl bg-white shadow-soft max-h-[70vh]"
    >
      <table class="min-w-full text-sm border-collapse" role="grid">
        <thead>
          <tr class="bg-gray-50">
            <th
              scope="col"
              class="sticky top-0 left-0 z-20 bg-gray-50 border-b border-r border-gray-200 px-4 py-2.5 text-left font-medium text-gray-600 whitespace-nowrap"
            >
              Студент
            </th>
            <th
              v-for="lesson in quizLessons"
              :key="lesson.lesson_id"
              scope="col"
              class="sticky top-0 z-10 bg-gray-50 border-b border-r border-gray-200 px-3 py-2.5 text-center font-medium text-gray-600 whitespace-nowrap"
            >
              <span class="block max-w-[8rem] truncate" :title="lesson.lesson_title">
                {{ lesson.lesson_title }}
              </span>
            </th>
            <th
              v-for="col in assignmentColumns"
              :key="col.assignment_id"
              scope="col"
              class="sticky top-0 z-10 bg-violet-50/70 border-b border-r border-gray-200 px-3 py-2.5 text-center font-medium text-gray-600 whitespace-nowrap"
            >
              <span class="block max-w-[8rem] truncate" :title="col.title">{{ col.title }}</span>
              <span class="block text-[10px] font-normal text-violet-500 uppercase tracking-wide">
                задание
              </span>
            </th>
            <th
              scope="col"
              class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 px-3 py-2.5 text-center font-medium text-gray-600 whitespace-nowrap"
            >
              Средний
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in gradebook.students"
            :key="row.student_id"
            class="odd:bg-white even:bg-gray-50/40 hover:bg-violet-50/30"
          >
            <th
              scope="row"
              class="sticky left-0 z-10 bg-inherit border-b border-r border-gray-100 px-4 py-2 text-left whitespace-nowrap"
            >
              <div class="font-medium text-gray-900">{{ row.student_name }}</div>
              <div class="text-xs text-gray-500">{{ row.student_email }}</div>
            </th>

            <td
              v-for="lesson in quizLessons"
              :key="lesson.lesson_id"
              class="border-b border-r border-gray-100 px-2 py-1.5 text-center align-middle"
            >
              <button
                v-if="cellByLesson(row, lesson.lesson_id)?.progress_id"
                type="button"
                :class="[
                  'w-full min-w-[3rem] inline-flex items-center justify-center gap-1 px-2 py-1 rounded-lg font-medium transition',
                  'focus:outline-none focus:ring-2 focus:ring-violet-500/30',
                  scoreBandClasses(cellByLesson(row, lesson.lesson_id)!.effective_score),
                  'hover:ring-2 hover:ring-violet-500/20 cursor-pointer',
                ]"
                :aria-label="`Балл студента ${row.student_name} за «${lesson.lesson_title}»: ${cellByLesson(row, lesson.lesson_id)!.effective_score ?? 'не выставлен'}`"
                :title="cellByLesson(row, lesson.lesson_id)!.teacher_comment ?? undefined"
                @click="openEditor(cellByLesson(row, lesson.lesson_id)!, row.student_id, $event)"
              >
                <span v-if="cellByLesson(row, lesson.lesson_id)!.effective_score !== null">
                  {{ cellByLesson(row, lesson.lesson_id)!.effective_score!.toFixed(1) }}
                </span>
                <span v-else>—</span>
                <span
                  v-if="cellByLesson(row, lesson.lesson_id)!.manual_score !== null"
                  class="text-[10px] uppercase tracking-wide opacity-70"
                  aria-label="изменён вручную"
                >изм</span>
              </button>
              <span
                v-else
                class="text-gray-300 cursor-default select-none"
                title="Студент ещё не проходил урок"
                aria-label="Студент не проходил урок"
              >—</span>
            </td>

            <td
              v-for="col in assignmentColumns"
              :key="col.assignment_id"
              class="border-b border-r border-gray-100 px-2 py-1.5 text-center align-middle bg-violet-50/20"
            >
              <template v-if="assignmentCell(row, col.assignment_id)?.points_awarded != null">
                <span
                  :class="['inline-block px-2 py-0.5 rounded-lg font-medium tabular-nums', assignmentBandClasses(assignmentCell(row, col.assignment_id)!.score)]"
                  :title="`${assignmentCell(row, col.assignment_id)!.points_awarded} из ${col.max_points}`"
                >
                  {{ assignmentCell(row, col.assignment_id)!.points_awarded }}/{{ col.max_points }}
                </span>
              </template>
              <AssignmentsStatusPill
                v-else-if="assignmentCell(row, col.assignment_id)?.status"
                :status="assignmentCell(row, col.assignment_id)!.status!"
              />
              <span v-else class="text-gray-300">—</span>
            </td>

            <td class="border-b border-gray-100 px-3 py-1.5 text-center align-middle">
              <span
                v-if="averageFor(row) !== null"
                :class="['inline-block px-2 py-0.5 rounded-lg font-medium', scoreBandClasses(averageFor(row))]"
              >
                {{ averageFor(row)!.toFixed(1) }}
              </span>
              <span v-else class="text-gray-300">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Inline editor popover, anchored to clicked cell via Teleport -->
    <Teleport to="body">
      <div
        v-if="editingCell && editorAnchor"
        class="fixed inset-0 z-40"
        @click.self="closeEditor"
      >
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Редактор балла"
          class="absolute w-72 bg-white rounded-xl shadow-hero border border-gray-100 p-4"
          :style="editorStyle"
          @keydown="onEditorKeydown"
        >
          <div class="text-xs text-gray-500 mb-2 truncate" :title="editingCell.lesson_title">
            {{ editingCell.lesson_title }}
          </div>

          <label class="block text-xs font-medium text-gray-700 mb-1" for="grade-score">Балл (0–100)</label>
          <div class="flex gap-2 items-center mb-1">
            <input
              id="grade-score"
              ref="scoreInputRef"
              v-model="editScore"
              type="number"
              min="0"
              max="100"
              step="0.1"
              placeholder="—"
              class="w-24 border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
              :aria-invalid="!!scoreError"
              aria-describedby="grade-score-err"
              @input="validateScore"
            />
            <span class="text-xs text-gray-400">/ 100</span>
            <span
              v-if="editingCell.quiz_score !== null"
              class="ml-auto text-xs text-gray-500"
            >
              авто: {{ editingCell.quiz_score.toFixed(1) }}
            </span>
          </div>
          <p
            v-if="scoreError"
            id="grade-score-err"
            class="text-xs text-rose-600 mb-2"
          >{{ scoreError }}</p>

          <label class="block text-xs font-medium text-gray-700 mb-1 mt-2" for="grade-comment">Комментарий</label>
          <textarea
            id="grade-comment"
            v-model="editComment"
            rows="3"
            placeholder="Необязательно"
            class="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 resize-none"
          />

          <p
            v-if="saveError"
            class="text-xs text-rose-600 mt-2"
            role="alert"
          >{{ saveError }}</p>

          <div class="flex flex-wrap items-center gap-2 mt-3">
            <UiButton
              size="sm"
              variant="primary"
              :loading="saving"
              :disabled="saving || !!scoreError"
              @click="saveCell"
            >Сохранить</UiButton>
            <UiButton
              v-if="editingCell.manual_score !== null"
              size="sm"
              variant="ghost"
              :disabled="saving"
              @click="resetOverride"
            >Сбросить балл</UiButton>
            <UiButton
              size="sm"
              variant="ghost"
              :disabled="saving"
              @click="closeEditor"
            >Отмена</UiButton>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
