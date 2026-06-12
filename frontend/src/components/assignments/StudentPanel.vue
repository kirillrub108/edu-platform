<script setup lang="ts">
import { ChevronDown, ClipboardList } from 'lucide-vue-next'
import { formatAssignmentDateTime } from '~/utils/assignments'

const props = defineProps<{ lessonId: string }>()

const store = useAssignmentsStore()
const state = computed(() => store.studentState(props.lessonId))
const expandedId = ref<string | null>(null)

const toggle = (id: string) => {
  expandedId.value = expandedId.value === id ? null : id
}

watch(
  () => props.lessonId,
  (id) => {
    if (id) void store.fetchStudent(id)
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
    <p v-else-if="state.items.length === 0" class="text-sm text-gray-400">
      Заданий для этого урока пока нет.
    </p>

    <div v-else class="space-y-3">
      <div
        v-for="a in state.items"
        :key="a.id"
        class="border border-gray-100 rounded-xl overflow-hidden"
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
          <AssignmentsStatusPill :status="a.my_submission?.status ?? 'not_started'" />
          <ChevronDown
            class="w-4 h-4 text-gray-400 transition-transform"
            :class="expandedId === a.id && 'rotate-180'"
          />
        </button>
        <div v-if="expandedId === a.id" class="px-4 pb-4 pt-1 border-t border-gray-100">
          <AssignmentsSubmit :key="a.id" :assignment="a" />
        </div>
      </div>
    </div>
  </section>
</template>
