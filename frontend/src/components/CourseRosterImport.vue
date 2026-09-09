<script setup lang="ts">
import { Upload, X } from 'lucide-vue-next'
import {
  ROSTER_IMPORT_MAX_FILE_MB,
  ROSTER_IMPORT_MAX_ROWS,
  reportToCsv,
  rosterReasonLabel,
  type RosterImportReport,
} from '~/utils/rosterImport'

const props = defineProps<{ courseId: string }>()
const emit = defineEmits<{ imported: [] }>()

const { apiFetch } = useApi()

const open = ref(false)
const file = ref<File | null>(null)
const dragging = ref(false)
const uploading = ref(false)
const error = ref('')
const report = ref<RosterImportReport | null>(null)
const chosenColumn = ref<number | null>(null)
const showAllRows = ref(false)

const problems = computed(() => report.value?.results.filter(r => r.status === 'skipped') ?? [])
const shownRows = computed(() => (showAllRows.value ? (report.value?.results ?? []) : problems.value))

const reset = () => {
  file.value = null
  report.value = null
  chosenColumn.value = null
  error.value = ''
  showAllRows.value = false
}

const pick = (picked: File | null | undefined) => {
  if (!picked) return
  reset()
  file.value = picked
}

const onPick = (e: Event) => {
  pick((e.target as HTMLInputElement).files?.[0])
}

const onDrop = (e: DragEvent) => {
  dragging.value = false
  pick(e.dataTransfer?.files?.[0])
}

const upload = async () => {
  if (!file.value || uploading.value) return
  if (file.value.size > ROSTER_IMPORT_MAX_FILE_MB * 1024 * 1024) {
    error.value = `Файл слишком большой (максимум ${ROSTER_IMPORT_MAX_FILE_MB} МБ)`
    return
  }
  uploading.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value)
    // Second pass after a column choice re-sends the same File — the teacher
    // never has to pick it again.
    if (chosenColumn.value !== null) form.append('email_column', String(chosenColumn.value))
    const res = await apiFetch<RosterImportReport>(
      `/courses/${props.courseId}/access-grants/import`,
      { method: 'POST', body: form },
    )
    report.value = res
    if (res.needs_column_choice) {
      chosenColumn.value = res.columns?.[0]?.index ?? null
    } else if (res.added > 0) {
      emit('imported')
    }
  } catch (e: any) {
    report.value = null
    error.value = e?.data?.detail ?? 'Не удалось импортировать файл'
  } finally {
    uploading.value = false
  }
}

const downloadCsv = () => {
  if (!report.value) return
  const blob = new Blob([reportToCsv(report.value)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'import-report.csv'
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div>
    <button
      type="button"
      class="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition"
      @click="open = !open"
    >
      <component :is="open ? X : Upload" class="w-4 h-4" aria-hidden="true" />
      {{ open ? 'Скрыть импорт' : 'Импорт из файла' }}
    </button>

    <div v-if="open" class="mt-3 border rounded-lg p-4 space-y-4">
      <p class="text-xs text-gray-500">
        Файл <code>.xlsx</code> или <code>.csv</code>, один email в строке.
        Колонка с заголовком «email» / «почта» либо единственная колонка с адресами.
        До {{ ROSTER_IMPORT_MAX_ROWS }} строк и {{ ROSTER_IMPORT_MAX_FILE_MB }} МБ.
      </p>

      <label
        class="flex flex-col items-center justify-center gap-1 border-2 border-dashed rounded-lg px-4 py-6 text-center cursor-pointer transition"
        :class="dragging ? 'border-violet-400 bg-violet-50' : 'border-gray-300 hover:bg-gray-50'"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <span class="text-sm text-gray-700">
          {{ file ? file.name : 'Перетащите файл или выберите' }}
        </span>
        <span class="text-xs text-gray-500">.xlsx, .csv</span>
        <input
          type="file"
          accept=".xlsx,.csv"
          class="sr-only"
          @change="onPick"
        >
      </label>

      <div v-if="report?.needs_column_choice" class="space-y-2">
        <label class="block text-sm text-gray-600" for="roster-column">
          Не удалось определить колонку с адресами — выберите её:
        </label>
        <select
          id="roster-column"
          v-model.number="chosenColumn"
          class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
        >
          <option v-for="col in report.columns ?? []" :key="col.index" :value="col.index">
            {{ col.header }} — {{ col.samples.join(', ') || 'пусто' }}
          </option>
        </select>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition disabled:opacity-50"
          :disabled="!file || uploading"
          @click="upload"
        >
          {{ uploading ? 'Загрузка…' : 'Загрузить' }}
        </button>
        <button
          v-if="file"
          type="button"
          class="px-3 py-1.5 rounded-lg border border-gray-300 text-xs text-gray-600 hover:bg-gray-50 transition"
          @click="reset"
        >
          Очистить
        </button>
      </div>

      <p v-if="error" class="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
        {{ error }}
      </p>

      <div aria-live="polite" class="space-y-2">
        <template v-if="report && !report.needs_column_choice">
          <p class="text-sm text-gray-800">
            Добавлено {{ report.added }} из {{ report.total_rows }}
            <span v-if="report.detected_column" class="text-gray-500">
              (колонка «{{ report.detected_column.header }}»)
            </span>
          </p>
          <p v-if="!report.total_rows" class="text-sm text-gray-500">
            В файле не нашлось ни одной непустой строки.
          </p>

          <details v-if="problems.length" class="text-sm">
            <summary class="cursor-pointer text-gray-600">
              Пропущено строк: {{ problems.length }}
            </summary>
            <ul class="mt-2 border rounded-lg divide-y">
              <li
                v-for="row in shownRows"
                :key="row.row"
                class="flex items-start justify-between gap-3 px-3 py-2"
              >
                <span class="min-w-0 text-gray-700">
                  <span class="text-gray-400">{{ row.row }}.</span> {{ row.raw_value }}
                </span>
                <span class="shrink-0 text-xs" :class="row.status === 'added' ? 'text-green-700' : 'text-amber-700'">
                  {{ row.status === 'added' ? 'Добавлен' : rosterReasonLabel(row.reason) }}
                </span>
              </li>
            </ul>
            <label class="mt-2 flex items-center gap-2 text-xs text-gray-500">
              <input v-model="showAllRows" type="checkbox"> показать и успешные строки
            </label>
          </details>

          <button
            type="button"
            class="px-3 py-1.5 rounded-lg border border-gray-300 text-xs text-gray-600 hover:bg-gray-50 transition"
            @click="downloadCsv"
          >
            Скачать отчёт (CSV)
          </button>
        </template>
      </div>
    </div>
  </div>
</template>
