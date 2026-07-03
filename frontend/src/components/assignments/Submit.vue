<script setup lang="ts">
import { Paperclip, Trash2, Download, CheckCircle2 } from 'lucide-vue-next'
import type { AssignmentStudent, StudentSubmission } from '~/stores/assignments'
import { assignmentErrorMessage } from '~/stores/assignments'
import {
  formatBytes,
  formatAssignmentDateTime,
  isExtAllowed,
  isFileTooLarge,
  submissionIsComplete,
} from '~/utils/assignments'

const props = defineProps<{
  assignment: AssignmentStudent
  // Teacher «view as student» dry-run: all submission actions are disabled.
  preview?: boolean
}>()

const PREVIEW_TOOLTIP = 'Недоступно в предпросмотре'

const store = useAssignmentsStore()

const sub = ref<StudentSubmission | null>(props.assignment.my_submission)
const text = ref(sub.value?.text_content ?? '')
const snapshot = ref({
  text: sub.value?.text_content ?? '',
  fileIds: sub.value?.attachments.filter(a => a.kind === 'submission').map(a => a.id) ?? [],
})
const error = ref<string | null>(null)
const fileError = ref<string | null>(null)
const saving = ref(false)
const submitting = ref(false)
const uploading = ref(false)
const posting = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const locked = computed(
  () => sub.value?.status === 'graded' || sub.value?.status === 'returned',
)
const returned = computed(() => sub.value?.status === 'returned')
const submissionFiles = computed(
  () => sub.value?.attachments.filter((a) => a.kind === 'submission') ?? [],
)
const feedbackFiles = computed(
  () => sub.value?.attachments.filter((a) => a.kind === 'feedback') ?? [],
)
const canSubmit = computed(
  () => submissionIsComplete(text.value, submissionFiles.value.length) && !locked.value,
)
const isSubmitted = computed(() => sub.value?.status === 'submitted')
const hasChanges = computed(() => {
  const textChanged = text.value !== snapshot.value.text
  const currentIds = submissionFiles.value.map(f => f.id)
  const snapshotIds = snapshot.value.fileIds
  const filesChanged =
    currentIds.length !== snapshotIds.length ||
    currentIds.some((id, i) => id !== snapshotIds[i])
  return textChanged || filesChanged
})
const scorePct = computed(() =>
  sub.value?.score != null ? Math.round(sub.value.score * 100) : null,
)

const refresh = async () => {
  const detail = await store.getStudentAssignment(props.assignment.id)
  sub.value = detail.my_submission
}

const onSaveDraft = async () => {
  if (props.preview) return
  saving.value = true
  error.value = null
  try {
    sub.value = await store.saveDraft(props.assignment.id, text.value || null)
    snapshot.value = {
      text: sub.value.text_content ?? '',
      fileIds: sub.value.attachments.filter(a => a.kind === 'submission').map(a => a.id),
    }
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось сохранить черновик')
  } finally {
    saving.value = false
  }
}

const onSubmit = async () => {
  if (props.preview) return
  submitting.value = true
  error.value = null
  try {
    sub.value = await store.submitStudent(props.assignment.id, text.value || null)
    snapshot.value = {
      text: sub.value.text_content ?? '',
      fileIds: sub.value.attachments.filter(a => a.kind === 'submission').map(a => a.id),
    }
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось отправить')
  } finally {
    submitting.value = false
  }
}

const onPickFile = () => fileInput.value?.click()

const onFileChange = async (event: Event) => {
  if (props.preview) return
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // allow re-selecting the same file later
  if (!file) return
  fileError.value = null
  if (!isExtAllowed(file.name, props.assignment.allowed_ext)) {
    fileError.value = `Допустимые форматы: ${props.assignment.allowed_ext.join(', ')}`
    return
  }
  if (isFileTooLarge(file.size, props.assignment.max_file_mb)) {
    fileError.value = `Файл больше ${props.assignment.max_file_mb} МБ`
    return
  }
  if (submissionFiles.value.length >= props.assignment.max_files) {
    fileError.value = `Не более ${props.assignment.max_files} файлов`
    return
  }
  uploading.value = true
  try {
    await store.uploadStudentFile(props.assignment.id, file)
    await refresh()
  } catch (err) {
    fileError.value = assignmentErrorMessage(err, 'Не удалось загрузить файл')
  } finally {
    uploading.value = false
  }
}

const onRemoveFile = async (attachmentId: string) => {
  if (!sub.value) return
  try {
    await store.deleteStudentFile(sub.value.id, attachmentId)
    await refresh()
  } catch (err) {
    fileError.value = assignmentErrorMessage(err, 'Не удалось удалить файл')
  }
}

const onSendMessage = async (body: string) => {
  if (!sub.value) return
  posting.value = true
  try {
    const message = await store.postStudentMessage(sub.value.id, body)
    sub.value.messages = [...sub.value.messages, message]
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось отправить сообщение')
  } finally {
    posting.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <p class="text-sm text-gray-700 whitespace-pre-wrap">{{ assignment.prompt }}</p>

    <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
      <span>Макс. балл: <span class="font-medium text-gray-700">{{ assignment.max_points }}</span></span>
      <span v-if="assignment.due_at">Срок: {{ formatAssignmentDateTime(assignment.due_at) }}</span>
      <AssignmentsStatusPill v-if="sub" :status="sub.status" />
    </div>

    <!-- Released grade -->
    <div
      v-if="returned"
      class="rounded-xl border border-emerald-100 bg-emerald-50 p-4 space-y-2"
    >
      <div class="flex items-center gap-2 text-emerald-800">
        <CheckCircle2 class="w-4 h-4" />
        <span class="font-semibold text-sm">
          Оценка: {{ sub?.points_awarded }} / {{ assignment.max_points }}
          <span v-if="scorePct !== null" class="text-emerald-600">({{ scorePct }}%)</span>
        </span>
      </div>
      <p v-if="sub?.feedback" class="text-sm text-emerald-900 whitespace-pre-wrap">{{ sub.feedback }}</p>
      <div v-if="feedbackFiles.length" class="flex flex-wrap gap-2 pt-1">
        <a
          v-for="f in feedbackFiles"
          :key="f.id"
          :href="f.download_url"
          target="_blank"
          class="inline-flex items-center gap-1.5 text-xs text-emerald-700 hover:underline"
        >
          <Download class="w-3.5 h-3.5" />{{ f.original_filename }}
        </a>
      </div>
    </div>

    <!-- Answer -->
    <div>
      <div v-if="preview" class="space-y-1.5" :title="PREVIEW_TOOLTIP">
        <span class="block text-sm font-medium text-gray-400">Ваш ответ</span>
        <textarea
          disabled
          rows="4"
          placeholder="Введите текст ответа…"
          class="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm cursor-not-allowed"
        />
      </div>
      <UiInput
        v-else-if="!locked"
        v-model="text"
        as="textarea"
        :rows="6"
        label="Ваш ответ"
        placeholder="Введите текст ответа…"
      />
      <div v-else class="space-y-1.5">
        <span class="block text-sm font-medium text-gray-700">Ваш ответ</span>
        <p class="text-sm text-gray-800 whitespace-pre-wrap bg-gray-50 rounded-xl px-4 py-2.5">
          {{ text || '—' }}
        </p>
      </div>
    </div>

    <!-- Attachments -->
    <div v-if="assignment.attachments_enabled" class="space-y-2">
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium text-gray-700">Файлы</span>
        <UiButton
          v-if="!locked"
          size="sm"
          variant="secondary"
          :loading="uploading"
          :disabled="preview || submissionFiles.length >= assignment.max_files"
          :title="preview ? PREVIEW_TOOLTIP : undefined"
          @click="onPickFile"
        >
          <template #icon><Paperclip class="w-3.5 h-3.5" /></template>
          Прикрепить
        </UiButton>
        <input
          ref="fileInput"
          type="file"
          class="hidden"
          @change="onFileChange"
        />
      </div>
      <ul v-if="submissionFiles.length" class="space-y-1">
        <li
          v-for="f in submissionFiles"
          :key="f.id"
          class="flex items-center gap-2 text-sm text-gray-700 bg-gray-50 rounded-lg px-3 py-1.5"
        >
          <a :href="f.download_url" target="_blank" class="flex-1 truncate hover:underline">
            {{ f.original_filename }}
          </a>
          <span class="text-xs text-gray-400">{{ formatBytes(f.size_bytes) }}</span>
          <button
            v-if="!locked"
            type="button"
            class="text-gray-400 hover:text-rose-600 transition"
            aria-label="Удалить файл"
            @click="onRemoveFile(f.id)"
          >
            <Trash2 class="w-4 h-4" />
          </button>
        </li>
      </ul>
      <p v-if="fileError" class="text-xs text-rose-600">{{ fileError }}</p>
    </div>

    <p v-if="error" class="text-sm text-rose-600">{{ error }}</p>

    <div v-if="!locked" class="flex items-center gap-2">
      <UiButton
        variant="secondary"
        size="sm"
        :loading="saving"
        :disabled="preview || (isSubmitted && !hasChanges)"
        :title="preview ? PREVIEW_TOOLTIP : undefined"
        @click="onSaveDraft"
      >
        Сохранить черновик
      </UiButton>
      <UiButton
        size="sm"
        :loading="submitting"
        :disabled="preview || !canSubmit || (isSubmitted && !hasChanges)"
        :title="preview ? PREVIEW_TOOLTIP : undefined"
        @click="onSubmit"
      >
        Сдать работу
      </UiButton>
    </div>
    <p v-else class="text-xs text-gray-400">
      Работа отправлена на проверку — изменения недоступны.
    </p>

    <div v-if="sub" class="border-t border-gray-100 pt-4">
      <AssignmentsThread
        :messages="sub.messages"
        :posting="posting"
        @send="onSendMessage"
      />
    </div>
  </div>
</template>
