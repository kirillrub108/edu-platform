<script setup lang="ts">
import { ChevronDown, ClipboardList } from 'lucide-vue-next'
import type { AssignmentStatus, AssignmentStudent } from '~/stores/assignments'
import { formatAssignmentDateTime } from '~/utils/assignments'

const props = defineProps<{
  lessonId: string
  // Teacher «view as student» dry-run: owner list (drafts included, badged),
  // submission form disabled — nothing is written to the backend.
  preview?: boolean
}>()

const store = useAssignmentsStore()
const state = computed(() =>
  props.preview ? store.teacherState(props.lessonId) : store.studentState(props.lessonId),
)
const expandedId = ref<string | null>(null)

// Unified render shape: student items are always 'published'; in preview the
// teacher list is mapped to the student shape, keeping status for the badge.
const items = computed<(AssignmentStudent & { status: AssignmentStatus })[]>(() => {
  if (!props.preview) {
    return store.studentState(props.lessonId).items.map((a) => ({
      ...a,
      status: 'published' as const,
    }))
  }
  return store.teacherState(props.lessonId).items.map((a) => ({
    id: a.id,
    lesson_id: a.lesson_id,
    title: a.title,
    prompt: a.prompt,
    max_points: a.max_points,
    due_at: a.due_at,
    attachments_enabled: a.attachments_enabled,
    max_files: a.max_files,
    allowed_ext: a.allowed_ext,
    max_file_mb: a.max_file_mb,
    pass_threshold: a.pass_threshold,
    my_submission: null,
    status: a.status,
  }))
})

const toggle = (id: string) => {
  expandedId.value = expandedId.value === id ? null : id
}

watch(
  () => props.lessonId,
  (id) => {
    if (!id) return
    if (props.preview) void store.fetchTeacher(id)
    else void store.fetchStudent(id)
  },
  { immediate: true },
)
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 shadow-soft p-5 space-y-4">
    <div class="flex items-center gap-2">
      <ClipboardList class="w-5 h-5 text-violet-600" />
      <h3 class="text-base font-semibold text-gray-900">Задания</h3>
    </div>

    <p v-if="state.loading" class="text-sm text-gray-500">Загрузка…</p>
    <p v-else-if="state.error" class="text-sm text-rose-600">{{ state.error }}</p>
    <p v-else-if="items.length === 0" class="text-sm text-gray-400">
      Заданий для этого урока пока нет.
    </p>

    <div v-else class="space-y-3">
      <div
        v-for="a in items"
        :key="a.id"
        class="border border-gray-100 rounded-xl overflow-hidden"
        :class="a.status === 'draft' && 'opacity-60'"
      >
        <button
          type="button"
          class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition"
          @click="toggle(a.id)"
        >
          <div class="flex-1 min-w-0">
            <div class="font-medium text-gray-900 truncate">{{ a.title }}</div>
            <div class="text-xs text-gray-500">
              Макс. балл {{ a.max_points }}
              <span v-if="a.due_at"> · до {{ formatAssignmentDateTime(a.due_at) }}</span>
            </div>
          </div>
          <span
            v-if="a.status === 'draft'"
            class="text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700 shrink-0"
          >Студент не увидит</span>
          <AssignmentsStatusPill :status="a.my_submission?.status ?? 'not_started'" />
          <ChevronDown
            class="w-4 h-4 text-gray-400 transition-transform"
            :class="expandedId === a.id && 'rotate-180'"
          />
        </button>
        <div v-if="expandedId === a.id" class="px-4 pb-4 pt-1 border-t border-gray-100">
          <AssignmentsSubmit :key="a.id" :assignment="a" :preview="preview" />
        </div>
      </div>
    </div>
  </section>
</template>
