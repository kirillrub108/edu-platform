<script setup lang="ts">
import type { AssignmentCreatePayload, AssignmentTeacher } from '~/stores/assignments'
import { assignmentErrorMessage } from '~/stores/assignments'

const props = defineProps<{
  lessonId: string
  assignment?: AssignmentTeacher | null
}>()
const emit = defineEmits<{ saved: [AssignmentTeacher]; cancel: [] }>()

const store = useAssignmentsStore()
const isEdit = computed(() => !!props.assignment)

const toLocalInput = (iso: string | null): string => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const a = props.assignment
const title = ref(a?.title ?? '')
const prompt = ref(a?.prompt ?? '')
const maxPoints = ref<number>(a?.max_points ?? 100)
const dueAt = ref<string>(toLocalInput(a?.due_at ?? null))
const passThresholdPct = ref<number | null>(
  a?.pass_threshold != null ? Math.round(a.pass_threshold * 100) : null,
)
const attachmentsEnabled = ref(a?.attachments_enabled ?? true)

const saving = ref(false)
const error = ref<string | null>(null)

const titleError = computed(() => (title.value.trim() ? '' : 'Введите название'))
const promptError = computed(() => (prompt.value.trim() ? '' : 'Введите формулировку'))
const valid = computed(
  () => !titleError.value && !promptError.value && maxPoints.value > 0,
)

const onSave = async () => {
  if (!valid.value) return
  saving.value = true
  error.value = null
  const pct = passThresholdPct.value
  const hasThreshold = pct != null && (pct as unknown) !== '' && !Number.isNaN(Number(pct))
  const payload: AssignmentCreatePayload = {
    title: title.value.trim(),
    prompt: prompt.value.trim(),
    max_points: Number(maxPoints.value),
    due_at: dueAt.value ? new Date(dueAt.value).toISOString() : null,
    attachments_enabled: attachmentsEnabled.value,
    pass_threshold: hasThreshold ? Number(pct) / 100 : null,
  }
  try {
    const result = isEdit.value
      ? await store.update(props.lessonId, props.assignment!.id, payload)
      : await store.create(props.lessonId, payload)
    emit('saved', result)
  } catch (err) {
    error.value = assignmentErrorMessage(err, 'Не удалось сохранить задание')
  } finally {
    saving.value = false
  }
}

const numberClass =
  'w-full bg-white px-4 py-2.5 text-sm text-gray-900 border border-gray-200 rounded-xl ' +
  'focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400'
</script>

<template>
  <div class="rounded-xl border border-violet-100 bg-violet-50/40 p-5 space-y-4">
    <h4 class="text-sm font-semibold text-gray-900">
      {{ isEdit ? 'Редактировать задание' : 'Новое задание' }}
    </h4>

    <UiInput v-model="title" label="Название" :error="titleError" placeholder="Например: Эссе" />
    <UiInput
      v-model="prompt"
      as="textarea"
      :rows="4"
      label="Формулировка"
      :error="promptError"
      placeholder="Что нужно сделать студенту…"
    />

    <div class="grid grid-cols-2 gap-3">
      <div class="space-y-1.5">
        <label class="block text-sm font-medium text-gray-700">Максимальный балл</label>
        <input v-model.number="maxPoints" type="number" min="1" :class="numberClass" />
      </div>
      <div class="space-y-1.5">
        <label class="block text-sm font-medium text-gray-700">Проходной балл, %</label>
        <input
          v-model.number="passThresholdPct"
          type="number"
          min="0"
          max="100"
          placeholder="не задан"
          :class="numberClass"
        />
      </div>
      <div class="space-y-1.5 col-span-2">
        <label class="block text-sm font-medium text-gray-700">Дедлайн (необязательно)</label>
        <input v-model="dueAt" type="datetime-local" :class="numberClass" />
      </div>
    </div>

    <div>
      <label class="flex items-center gap-2 text-sm text-gray-700">
        <input v-model="attachmentsEnabled" type="checkbox" class="rounded border-gray-300 text-violet-600" />
        Разрешить вложения
      </label>
      <p v-if="attachmentsEnabled" class="mt-1.5 text-xs text-gray-500">
        До 5 файлов, до 10 МБ каждый
      </p>
    </div>

    <p v-if="error" class="text-sm text-rose-600">{{ error }}</p>

    <div class="flex items-center gap-2">
      <UiButton size="sm" :loading="saving" :disabled="!valid" @click="onSave">
        {{ isEdit ? 'Сохранить' : 'Создать' }}
      </UiButton>
      <UiButton size="sm" variant="ghost" @click="emit('cancel')">Отмена</UiButton>
    </div>
  </div>
</template>
