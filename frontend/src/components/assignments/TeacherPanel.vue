<script setup lang="ts">
import { Plus, Pencil, Trash2, Eye, EyeOff, Users } from 'lucide-vue-next'
import type { AssignmentTeacher, SubmissionSummary } from '~/stores/assignments'
import { assignmentErrorMessage } from '~/stores/assignments'
import { formatAssignmentDateTime } from '~/utils/assignments'

const props = defineProps<{ lessonId: string }>()

const store = useAssignmentsStore()
const state = computed(() => store.teacherState(props.lessonId))

const showEditor = ref(false)
const editing = ref<AssignmentTeacher | null>(null)
const busyId = ref<string | null>(null)

const openAssignment = ref<AssignmentTeacher | null>(null)
const submissions = ref<SubmissionSummary[]>([])
const submissionsLoading = ref(false)
const reviewId = ref<string | null>(null)

const openCreate = () => {
  editing.value = null
  showEditor.value = true
}
const openEdit = (a: AssignmentTeacher) => {
  editing.value = a
  showEditor.value = true
}
const onSaved = () => {
  showEditor.value = false
  editing.value = null
}

const togglePublish = async (a: AssignmentTeacher) => {
  busyId.value = a.id
  try {
    await store.setStatus(props.lessonId, a.id, a.status === 'published' ? 'unpublish' : 'publish')
  } catch (err) {
    state.value.error = assignmentErrorMessage(err, 'Не удалось изменить статус')
  } finally {
    busyId.value = null
  }
}

const onDelete = async (a: AssignmentTeacher) => {
  if (!window.confirm(`Удалить задание «${a.title}» и все работы по нему?`)) return
  busyId.value = a.id
  try {
    await store.remove(props.lessonId, a.id)
    if (openAssignment.value?.id === a.id) openAssignment.value = null
  } catch {
    /* error surfaced in state */
  } finally {
    busyId.value = null
  }
}

const loadSubmissions = async (a: AssignmentTeacher) => {
  submissionsLoading.value = true
  reviewId.value = null
  try {
    submissions.value = await store.fetchSubmissions(a.id)
  } finally {
    submissionsLoading.value = false
  }
}

const toggleSubmissions = async (a: AssignmentTeacher) => {
  if (openAssignment.value?.id === a.id) {
    openAssignment.value = null
    return
  }
  openAssignment.value = a
  await loadSubmissions(a)
}

const onGraded = async () => {
  if (openAssignment.value) await loadSubmissions(openAssignment.value)
  await store.fetchTeacher(props.lessonId)
}

watch(
  () => props.lessonId,
  (id) => {
    if (id) void store.fetchTeacher(id)
  },
  { immediate: true },
)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-gray-900">Задания</h2>
      <UiButton v-if="!showEditor" size="sm" @click="openCreate">
        <template #icon><Plus class="w-3.5 h-3.5" /></template>
        Создать задание
      </UiButton>
    </div>

    <AssignmentsEditor
      v-if="showEditor"
      :lesson-id="lessonId"
      :assignment="editing"
      @saved="onSaved"
      @cancel="showEditor = false"
    />

    <p v-if="state.loading" class="text-sm text-gray-500">Загрузка…</p>
    <p v-else-if="state.error" class="text-sm text-rose-600">{{ state.error }}</p>
    <p v-else-if="state.items.length === 0 && !showEditor" class="text-sm text-gray-400">
      Заданий пока нет. Создайте первое.
    </p>

    <div
      v-for="a in state.items"
      :key="a.id"
      class="border border-gray-100 rounded-xl p-4 space-y-3"
    >
      <div class="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="font-medium text-gray-900 truncate">{{ a.title }}</span>
            <StatusBadge :status="a.status" />
          </div>
          <div class="text-xs text-gray-500 mt-0.5">
            Макс. балл {{ a.max_points }}
            <span v-if="a.due_at"> · до {{ formatAssignmentDateTime(a.due_at) }}</span>
            <span v-if="a.pending_count > 0" class="text-amber-600">
              · {{ a.pending_count }} на проверке
            </span>
          </div>
        </div>
        <div class="flex items-center gap-1">
          <UiButton
            size="sm"
            variant="ghost"
            :loading="busyId === a.id"
            @click="togglePublish(a)"
          >
            <template #icon>
              <EyeOff v-if="a.status === 'published'" class="w-3.5 h-3.5" />
              <Eye v-else class="w-3.5 h-3.5" />
            </template>
            {{ a.status === 'published' ? 'Снять' : 'Опубликовать' }}
          </UiButton>
          <UiButton size="sm" variant="ghost" @click="openEdit(a)">
            <template #icon><Pencil class="w-3.5 h-3.5" /></template>
          </UiButton>
          <UiButton size="sm" variant="ghost" @click="onDelete(a)">
            <template #icon><Trash2 class="w-3.5 h-3.5 text-rose-500" /></template>
          </UiButton>
        </div>
      </div>

      <button
        type="button"
        class="inline-flex items-center gap-1.5 text-sm text-violet-700 hover:text-violet-900 transition"
        @click="toggleSubmissions(a)"
      >
        <Users class="w-4 h-4" />
        Работы ({{ a.submission_count }})
      </button>

      <div v-if="openAssignment?.id === a.id" class="space-y-2">
        <p v-if="submissionsLoading" class="text-sm text-gray-500">Загрузка работ…</p>
        <p v-else-if="submissions.length === 0" class="text-sm text-gray-400">
          Пока никто не сдал.
        </p>
        <table v-else class="w-full text-sm">
          <tbody class="divide-y divide-gray-50">
            <tr v-for="s in submissions" :key="s.id">
              <td class="py-2 pr-2">
                <div class="text-gray-800">{{ s.student_name ?? s.student_email }}</div>
                <div class="text-xs text-gray-400">{{ s.student_email }}</div>
              </td>
              <td class="py-2 px-2 text-center">
                <AssignmentsStatusPill :status="s.status" />
              </td>
              <td class="py-2 px-2 text-center tabular-nums text-gray-600">
                <span v-if="s.points_awarded !== null">
                  {{ s.points_awarded }} / {{ a.max_points }}
                </span>
                <span v-else class="text-gray-400">—</span>
              </td>
              <td class="py-2 pl-2 text-right">
                <UiButton size="sm" variant="secondary" @click="reviewId = s.id">
                  Проверить
                </UiButton>
              </td>
            </tr>
          </tbody>
        </table>

        <AssignmentsReview
          v-if="reviewId"
          :key="reviewId"
          :submission-id="reviewId"
          :assignment="a"
          @graded="onGraded"
          @close="reviewId = null"
        />
      </div>
    </div>
  </div>
</template>
