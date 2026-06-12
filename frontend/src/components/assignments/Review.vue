<script setup lang="ts">
import { Download, Paperclip, RotateCcw, X } from 'lucide-vue-next'
import type { AssignmentTeacher, TeacherSubmission } from '~/stores/assignments'
import { assignmentErrorMessage } from '~/stores/assignments'
import { formatBytes, formatAssignmentDateTime, validatePoints } from '~/utils/assignments'

const props = defineProps<{
  submissionId: string
  assignment: AssignmentTeacher
}>()
const emit = defineEmits<{ graded: []; close: [] }>()

const store = useAssignmentsStore()

const sub = ref<TeacherSubmission | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const points = ref<number | null>(null)
const feedback = ref('')
const grading = ref(false)
const reopening = ref(false)
const uploading = ref(false)
const posting = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const isDraft = computed(() => sub.value?.status === 'draft')
const isResolved = computed(
  () => sub.value?.status === 'graded' || sub.value?.status === 'returned',
)
const submissionFiles = computed(
  () => sub.value?.attachments.filter((a) => a.kind === 'submission') ?? [],
)
const feedbackFiles = computed(
  () => sub.value?.attachments.filter((a) => a.kind === 'feedback') ?? [],
)
const pointsError = computed(() =>
  points.value === null ? null : validatePoints(points.value, props.assignment.max_points),
)
const canGrade = computed(
  () => !isDraft.value && points.value !== null && pointsError.value === null,
)

const loadSubmission = async () => {
  loading.value = true
  try {
    sub.value = await store.fetchSubmission(props.submissionId)
    points.value = sub.value.points_awarded
    feedback.value = sub.value.feedback ?? ''
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось загрузить работу')
  } finally {
    loading.value = false
  }
}

const onGrade = async () => {
  if (!canGrade.value || points.value === null) return
  grading.value = true
  error.value = null
  try {
    sub.value = await store.grade(props.submissionId, {
      points_awarded: points.value,
      feedback: feedback.value.trim() || null,
    })
    emit('graded')
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось выставить оценку')
  } finally {
    grading.value = false
  }
}

const onReopen = async () => {
  reopening.value = true
  error.value = null
  try {
    sub.value = await store.reopen(props.submissionId)
    emit('graded')
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось вернуть на доработку')
  } finally {
    reopening.value = false
  }
}

const onPickFile = () => fileInput.value?.click()

const onFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  error.value = null
  try {
    await store.uploadFeedbackFile(props.submissionId, file)
    await loadSubmission()
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось загрузить файл')
  } finally {
    uploading.value = false
  }
}

const onSendMessage = async (body: string) => {
  posting.value = true
  try {
    const message = await store.postTeacherMessage(props.submissionId, body)
    if (sub.value) sub.value.messages = [...sub.value.messages, message]
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось отправить сообщение')
  } finally {
    posting.value = false
  }
}

const numberClass =
  'w-32 bg-white px-4 py-2.5 text-sm text-gray-900 border rounded-xl ' +
  'focus:outline-none focus:ring-2 focus:ring-violet-500/30'

onMounted(loadSubmission)
</script>

<template>
  <div class="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
    <div class="flex items-start justify-between gap-3">
      <div v-if="sub">
        <div class="font-medium text-gray-900">{{ sub.student_name ?? sub.student_email }}</div>
        <div class="text-xs text-gray-500">{{ sub.student_email }}</div>
      </div>
      <div class="flex items-center gap-2">
        <AssignmentsStatusPill v-if="sub" :status="sub.status" />
        <button
          type="button"
          class="text-gray-400 hover:text-gray-700 transition"
          aria-label="Закрыть"
          @click="emit('close')"
        >
          <X class="w-4 h-4" />
        </button>
      </div>
    </div>

    <p v-if="loading" class="text-sm text-gray-500">Загрузка…</p>

    <template v-else-if="sub">
      <div>
        <span class="block text-sm font-medium text-gray-700 mb-1">Ответ студента</span>
        <p class="text-sm text-gray-800 whitespace-pre-wrap bg-gray-50 rounded-xl px-4 py-3">
          {{ sub.text_content || '— без текста —' }}
        </p>
        <div class="text-xs text-gray-400 mt-1">
          Сдано: {{ formatAssignmentDateTime(sub.submitted_at) }}
        </div>
      </div>

      <div v-if="submissionFiles.length" class="flex flex-wrap gap-2">
        <a
          v-for="f in submissionFiles"
          :key="f.id"
          :href="f.download_url"
          target="_blank"
          class="inline-flex items-center gap-1.5 text-xs text-violet-700 bg-violet-50 px-2.5 py-1 rounded-lg hover:bg-violet-100 transition"
        >
          <Download class="w-3.5 h-3.5" />{{ f.original_filename }}
          <span class="text-violet-400">{{ formatBytes(f.size_bytes) }}</span>
        </a>
      </div>

      <!-- Grade -->
      <div class="border-t border-gray-100 pt-4 space-y-3">
        <div class="flex items-end gap-3">
          <div class="space-y-1.5">
            <label class="block text-sm font-medium text-gray-700">
              Балл (из {{ assignment.max_points }})
            </label>
            <input
              v-model.number="points"
              type="number"
              min="0"
              :max="assignment.max_points"
              :class="[numberClass, pointsError ? 'border-rose-300' : 'border-gray-200']"
            />
          </div>
          <p v-if="pointsError" class="text-xs text-rose-600 pb-3">{{ pointsError }}</p>
        </div>

        <UiInput
          v-model="feedback"
          as="textarea"
          :rows="3"
          label="Комментарий"
          placeholder="Фидбек для студента…"
        />

        <div class="flex items-center gap-2">
          <UiButton size="sm" variant="secondary" :loading="uploading" @click="onPickFile">
            <template #icon><Paperclip class="w-3.5 h-3.5" /></template>
            Файл к фидбеку
          </UiButton>
          <input ref="fileInput" type="file" class="hidden" @change="onFileChange" />
        </div>
        <ul v-if="feedbackFiles.length" class="space-y-1">
          <li
            v-for="f in feedbackFiles"
            :key="f.id"
            class="flex items-center gap-2 text-sm text-gray-700 bg-gray-50 rounded-lg px-3 py-1.5"
          >
            <a :href="f.download_url" target="_blank" class="flex-1 truncate hover:underline">
              {{ f.original_filename }}
            </a>
            <span class="text-xs text-gray-400">{{ formatBytes(f.size_bytes) }}</span>
          </li>
        </ul>

        <p v-if="isDraft" class="text-xs text-amber-600">
          Студент ещё не сдал работу — оценить нельзя.
        </p>
        <p v-if="error" class="text-sm text-rose-600">{{ error }}</p>

        <div class="flex items-center gap-2">
          <UiButton size="sm" :loading="grading" :disabled="!canGrade" @click="onGrade">
            Поставить и вернуть
          </UiButton>
          <UiButton
            v-if="isResolved"
            size="sm"
            variant="ghost"
            :loading="reopening"
            @click="onReopen"
          >
            <template #icon><RotateCcw class="w-3.5 h-3.5" /></template>
            Вернуть на доработку
          </UiButton>
        </div>
      </div>

      <div class="border-t border-gray-100 pt-4">
        <AssignmentsThread :messages="sub.messages" :posting="posting" @send="onSendMessage" />
      </div>
    </template>
  </div>
</template>
