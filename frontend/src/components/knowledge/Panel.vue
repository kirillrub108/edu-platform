<script setup lang="ts">
import { Plus, Pencil, Trash2, Download, FileText, ArrowUp, ArrowDown, Paperclip } from 'lucide-vue-next'
import type { KnowledgeMaterial, KnowledgeNote } from '~/stores/lessonKnowledge'
import { formatBytes } from '~/utils/assignments'

/**
 * Lesson knowledge base: markdown notes + downloadable materials.
 * One component for both cabinets — editing affordances are gated on the
 * server-decided `can_edit` flag, never on a client-side role guess.
 */
const props = defineProps<{ lessonId: string; preview?: boolean }>()

const store = useLessonKnowledgeStore()
const state = computed(() => store.getState(props.lessonId))
// `can_edit` comes from the server (owner-only). In the teacher's student
// preview the owner still gets can_edit=true, so the preview flag suppresses
// the editing affordances to show exactly what a student sees.
const canEdit = computed(() => !props.preview && state.value.canEdit)
const noteMaxChars = computed(() => state.value.limits?.note_max_chars ?? 50000)
const acceptAttr = computed(() =>
  (state.value.limits?.allowed_ext ?? []).map((ext) => `.${ext}`).join(','),
)

const showNoteEditor = ref(false)
const editingNote = ref<KnowledgeNote | null>(null)
const busyId = ref<string | null>(null)

const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const materialTitle = ref('')

const openCreateNote = () => {
  editingNote.value = null
  showNoteEditor.value = true
}
const openEditNote = (note: KnowledgeNote) => {
  editingNote.value = note
  showNoteEditor.value = true
}
const closeNoteEditor = () => {
  showNoteEditor.value = false
  editingNote.value = null
}

const removeNote = async (note: KnowledgeNote) => {
  if (!window.confirm(`Удалить конспект «${note.title}»?`)) return
  busyId.value = note.id
  try {
    await store.deleteNote(props.lessonId, note.id)
  } catch {
    /* message already in state.error */
  } finally {
    busyId.value = null
  }
}

const move = async (note: KnowledgeNote, delta: number) => {
  busyId.value = note.id
  try {
    await store.moveNote(props.lessonId, note.id, delta)
  } catch {
    /* message already in state.error */
  } finally {
    busyId.value = null
  }
}

const onPickFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  state.value.error = null
  try {
    await store.uploadMaterial(props.lessonId, file, { title: materialTitle.value.trim() })
    materialTitle.value = ''
  } catch {
    /* message already in state.error */
  } finally {
    uploading.value = false
    input.value = ''
  }
}

const renameMaterial = async (material: KnowledgeMaterial) => {
  const next = window.prompt('Название материала', material.title)
  if (next === null) return
  const title = next.trim()
  if (!title || title === material.title) return
  busyId.value = material.id
  try {
    await store.updateMaterial(props.lessonId, material.id, { title })
  } catch {
    /* message already in state.error */
  } finally {
    busyId.value = null
  }
}

const removeMaterial = async (material: KnowledgeMaterial) => {
  if (!window.confirm(`Удалить файл «${material.title}»?`)) return
  busyId.value = material.id
  try {
    await store.deleteMaterial(props.lessonId, material.id)
  } catch {
    /* message already in state.error */
  } finally {
    busyId.value = null
  }
}

watch(() => props.lessonId, (id) => store.fetch(id))
onMounted(() => {
  if (!state.value.loaded) store.fetch(props.lessonId)
})
</script>

<template>
  <div class="space-y-6">
    <p v-if="state.error" class="text-sm text-rose-600 bg-rose-50 rounded-xl px-4 py-2.5">
      {{ state.error }}
    </p>

    <div v-if="state.loading && !state.loaded" class="text-sm text-gray-500">Загрузка…</div>

    <template v-else>
      <!-- ── Конспекты ─────────────────────────────────────────────────────── -->
      <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
        <div class="flex items-center justify-between gap-3 mb-4">
          <h2 class="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <FileText class="w-4.5 h-4.5 text-violet-500" />
            Конспекты
          </h2>
          <UiButton v-if="canEdit && !showNoteEditor" size="sm" @click="openCreateNote">
            <template #icon><Plus class="w-4 h-4" /></template>
            Добавить
          </UiButton>
        </div>

        <div v-if="showNoteEditor" class="mb-5 p-4 rounded-xl bg-gray-50 border border-gray-100">
          <KnowledgeNoteEditor
            :key="editingNote?.id ?? 'new'"
            :lesson-id="lessonId"
            :note="editingNote"
            :max-chars="noteMaxChars"
            @saved="closeNoteEditor"
            @cancel="closeNoteEditor"
          />
        </div>

        <p v-if="!state.notes.length" class="text-sm text-gray-500">
          {{ canEdit ? 'Пока нет конспектов — добавьте первый.' : 'Преподаватель пока не добавил конспекты.' }}
        </p>

        <ul v-else class="space-y-4">
          <li
            v-for="(note, idx) in state.notes"
            :key="note.id"
            class="rounded-xl border border-gray-100 p-4"
          >
            <div class="flex items-start justify-between gap-3 mb-2">
              <h3 class="text-sm font-semibold text-gray-900">{{ note.title }}</h3>
              <div v-if="canEdit" class="flex items-center gap-1 shrink-0">
                <button
                  type="button"
                  class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-30"
                  :disabled="idx === 0 || busyId === note.id"
                  aria-label="Выше"
                  @click="move(note, -1)"
                >
                  <ArrowUp class="w-4 h-4" />
                </button>
                <button
                  type="button"
                  class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-30"
                  :disabled="idx === state.notes.length - 1 || busyId === note.id"
                  aria-label="Ниже"
                  @click="move(note, 1)"
                >
                  <ArrowDown class="w-4 h-4" />
                </button>
                <button
                  type="button"
                  class="p-1.5 rounded-lg text-gray-400 hover:text-violet-600 hover:bg-violet-50"
                  aria-label="Редактировать"
                  @click="openEditNote(note)"
                >
                  <Pencil class="w-4 h-4" />
                </button>
                <button
                  type="button"
                  class="p-1.5 rounded-lg text-gray-400 hover:text-rose-600 hover:bg-rose-50"
                  :disabled="busyId === note.id"
                  aria-label="Удалить"
                  @click="removeNote(note)"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>
            </div>
            <KnowledgeMarkdownText :content="note.content" />
          </li>
        </ul>
      </section>

      <!-- ── Материалы ─────────────────────────────────────────────────────── -->
      <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
        <h2 class="text-lg font-semibold text-gray-900 flex items-center gap-2 mb-4">
          <Paperclip class="w-4.5 h-4.5 text-violet-500" />
          Файлы
        </h2>

        <div v-if="canEdit" class="mb-5 space-y-2">
          <UiInput
            v-model="materialTitle"
            label="Название (необязательно)"
            placeholder="По умолчанию — имя файла"
          />
          <input
            ref="fileInput"
            type="file"
            class="hidden"
            :accept="acceptAttr"
            @change="onPickFile"
          />
          <UiButton
            size="sm"
            variant="secondary"
            :loading="uploading"
            @click="fileInput?.click()"
          >
            <template #icon><Plus class="w-4 h-4" /></template>
            Прикрепить файл
          </UiButton>
          <p v-if="state.limits" class="text-xs text-gray-400">
            До {{ state.limits.max_files }} файлов · суммарно до {{ state.limits.max_total_mb }} МБ
          </p>
        </div>

        <p v-if="!state.materials.length" class="text-sm text-gray-500">
          {{ canEdit ? 'Пока нет прикреплённых файлов.' : 'Преподаватель пока не приложил файлы.' }}
        </p>

        <ul v-else class="space-y-2">
          <li
            v-for="material in state.materials"
            :key="material.id"
            class="flex items-center gap-3 rounded-xl border border-gray-100 px-4 py-3"
          >
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-gray-900 truncate">{{ material.title }}</p>
              <p v-if="material.description" class="text-xs text-gray-500 truncate">
                {{ material.description }}
              </p>
              <p class="text-xs text-gray-400">
                {{ material.original_filename }} · {{ formatBytes(material.size_bytes) }}
              </p>
            </div>
            <a
              :href="material.download_url"
              target="_blank"
              rel="noopener noreferrer"
              class="p-2 rounded-lg text-violet-600 hover:bg-violet-50 shrink-0"
              :aria-label="`Скачать ${material.title}`"
            >
              <Download class="w-4 h-4" />
            </a>
            <template v-if="canEdit">
              <button
                type="button"
                class="p-2 rounded-lg text-gray-400 hover:text-violet-600 hover:bg-violet-50 shrink-0"
                :disabled="busyId === material.id"
                aria-label="Переименовать"
                @click="renameMaterial(material)"
              >
                <Pencil class="w-4 h-4" />
              </button>
              <button
                type="button"
                class="p-2 rounded-lg text-gray-400 hover:text-rose-600 hover:bg-rose-50 shrink-0"
                :disabled="busyId === material.id"
                aria-label="Удалить"
                @click="removeMaterial(material)"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </template>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
