<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, Eye, EyeOff } from 'lucide-vue-next'

const props = defineProps<{
  title: string
  status: string
  isPublished: boolean
  savingTitle?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:title', value: string): void
}>()

const showStatus = computed(() =>
  ['analyzing', 'processing', 'error'].includes(props.status),
)
</script>

<template>
  <div>
    <NuxtLink
      to="/dashboard"
      class="inline-flex items-center gap-1 text-sm text-violet-700 hover:text-violet-600 font-medium transition mb-2"
    >
      <ChevronLeft class="w-4 h-4" />
      Назад к курсам
    </NuxtLink>
    <div class="flex items-center gap-3 flex-wrap">
      <InlineEdit
        :value="title"
        tag="h1"
        display-class="text-2xl font-semibold text-gray-900"
        input-class="text-2xl font-semibold text-gray-900"
        :saving="savingTitle"
        @save="emit('update:title', $event)"
      />
      <!-- Visibility (is_published) — the state the publish button toggles. -->
      <span
        class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
        :class="isPublished ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-600'"
      >
        <component :is="isPublished ? Eye : EyeOff" class="w-3.5 h-3.5" />
        {{ isPublished ? 'Опубликован' : 'Черновик' }}
      </span>
      <StatusBadge v-if="showStatus" :status="status" />
      <slot name="actions" />
    </div>
  </div>
</template>
