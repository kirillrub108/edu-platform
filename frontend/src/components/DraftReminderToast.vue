<script setup lang="ts">
import { FileText, X } from 'lucide-vue-next'

// Rendered once at the app root (see app.vue) so it survives the navigation
// away from the course editor that triggers it.
const store = useCourseEditorStore()
const { draftToast } = storeToRefs(store)

// "Опубликовать" takes the teacher back to the course editor, where the
// per-module / per-lesson publish buttons live (the content tab is the default).
const goToCourse = async (): Promise<void> => {
  const courseId = draftToast.value?.courseId
  store.dismissDraftToast()
  if (courseId) await navigateTo(`/courses/${courseId}`)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="draft-toast">
      <div
        v-if="draftToast"
        class="fixed bottom-4 right-4 z-[55] w-full max-w-sm flex items-start gap-3 bg-white border border-gray-200 rounded-xl shadow-lg px-4 py-3"
      >
        <div class="w-8 h-8 rounded-lg bg-gray-100 text-gray-500 grid place-items-center shrink-0">
          <FileText class="w-4 h-4" />
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm text-gray-800">
            В курсе остались неопубликованные модули или уроки — студенты их не видят.
          </p>
          <button
            type="button"
            class="mt-1 text-sm font-medium text-brand hover:underline"
            @click="goToCourse"
          >
            Опубликовать
          </button>
        </div>
        <button
          type="button"
          class="text-gray-300 hover:text-gray-500 transition shrink-0"
          aria-label="Закрыть"
          @click="store.dismissDraftToast()"
        >
          <X class="w-4 h-4" />
        </button>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.draft-toast-enter-active,
.draft-toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.draft-toast-enter-from,
.draft-toast-leave-to {
  opacity: 0;
  transform: translateY(0.5rem);
}
</style>
