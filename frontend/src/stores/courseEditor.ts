import { defineStore } from 'pinia'

interface DraftToast {
  courseId: string
}

/**
 * Session-scoped UI state for the course editor. The draft-leave reminder is
 * shown at most ONCE per browser session — the flag lives here (Pinia), not in
 * localStorage, so it resets on a fresh session and never persists.
 */
export const useCourseEditorStore = defineStore('courseEditor', () => {
  const draftReminderShown = ref(false)
  const draftToast = ref<DraftToast | null>(null)

  /**
   * Queue the leave reminder, but only the first time per session and only when
   * the course actually has unpublished content. No-op otherwise.
   */
  const maybeShowDraftReminder = (courseId: string, hasDrafts: boolean): void => {
    if (!hasDrafts || draftReminderShown.value) return
    draftReminderShown.value = true
    draftToast.value = { courseId }
  }

  const dismissDraftToast = (): void => {
    draftToast.value = null
  }

  return { draftReminderShown, draftToast, maybeShowDraftReminder, dismissDraftToast }
})
