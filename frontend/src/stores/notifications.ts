import { defineStore } from 'pinia'

/** One flag per notification category. Keys match the backend `User` columns
 *  and the `NotificationCategory` enum, so PATCH bodies are the same shape. */
export interface NotificationSettings {
  notify_content: boolean
  notify_feedback: boolean
  notify_submissions: boolean
}

export type NotificationCategory = keyof NotificationSettings

export const NOTIFICATION_CATEGORIES: ReadonlyArray<{
  key: NotificationCategory
  label: string
  hint: string
}> = [
  {
    key: 'notify_content',
    label: 'Готовый контент',
    hint: 'Видеолекция сгенерирована, тест готов.',
  },
  {
    key: 'notify_feedback',
    label: 'Обратная связь',
    hint: 'Комментарии преподавателя, оценки, сообщения по работам.',
  },
  {
    key: 'notify_submissions',
    label: 'Сдачи работ',
    hint: 'Студент сдал работу на проверку.',
  },
]

export const useNotificationsStore = defineStore('notifications', () => {
  const { apiFetch } = useApi()

  const settings = ref<NotificationSettings | null>(null)
  const loading = ref(false)
  const saving = ref<NotificationCategory | null>(null)
  const error = ref<string | null>(null)

  const fetchSettings = async () => {
    loading.value = true
    error.value = null
    try {
      settings.value = await apiFetch<NotificationSettings>('/notifications/settings')
    } catch (e: unknown) {
      error.value = 'Не удалось загрузить настройки уведомлений'
    } finally {
      loading.value = false
    }
  }

  /** Optimistic toggle: the switch flips immediately and rolls back if the
   *  request fails, so a flaky network can't leave the UI lying. */
  const setCategory = async (key: NotificationCategory, value: boolean) => {
    const current = settings.value
    if (!current) return
    const previous = current[key]
    settings.value = { ...current, [key]: value }
    saving.value = key
    error.value = null
    try {
      settings.value = await apiFetch<NotificationSettings>('/notifications/settings', {
        method: 'PATCH',
        body: { [key]: value },
      })
    } catch (e: unknown) {
      settings.value = { ...current, [key]: previous }
      error.value = 'Не удалось сохранить настройку'
    } finally {
      saving.value = null
    }
  }

  return { settings, loading, saving, error, fetchSettings, setCategory }
})
