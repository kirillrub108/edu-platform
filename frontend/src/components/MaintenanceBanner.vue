<script setup lang="ts">
import { AlertTriangle } from 'lucide-vue-next'

interface MaintenanceWindow {
  start: string
  end: string
  message: string
  is_active: boolean
}

interface SystemStatus {
  status: string
  version: string
  server_time: string
  maintenance: MaintenanceWindow | null
}

// Планы правятся в .env.prod и подхватываются на следующем роллауте бэкенда,
// поэтому долго открытая вкладка должна периодически перечитывать статус.
const REFRESH_INTERVAL_MS = 10 * 60 * 1000

const { apiFetch } = useApi()
const maintenance = ref<MaintenanceWindow | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const load = async () => {
  try {
    const status = await apiFetch<SystemStatus>('/system/status')
    maintenance.value = status.maintenance
  } catch {
    // Статус — необязательная информация. Недоступен (сеть, деплой) — просто
    // не показываем баннер: ломать шапку из-за этого нельзя.
    maintenance.value = null
  }
}

onMounted(() => {
  void load()
  timer = setInterval(() => { void load() }, REFRESH_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})

const dayFormat = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' })
const timeFormat = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' })

// Время приходит в UTC, показываем в часовом поясе пользователя.
const windowLabel = computed(() => {
  const w = maintenance.value
  if (!w) return ''
  const start = new Date(w.start)
  const end = new Date(w.end)
  if (start.toDateString() === end.toDateString()) {
    return `${dayFormat.format(start)}, ${timeFormat.format(start)}–${timeFormat.format(end)}`
  }
  return `${dayFormat.format(start)} ${timeFormat.format(start)} — ${dayFormat.format(end)} ${timeFormat.format(end)}`
})
</script>

<template>
  <div
    v-if="maintenance"
    class="w-full border-b border-amber-200 bg-amber-50 text-amber-900"
    role="status"
  >
    <div class="px-4 sm:px-6 py-2 flex items-start gap-2.5 text-xs sm:text-sm">
      <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" />
      <p class="min-w-0">
        <span class="font-semibold">
          {{ maintenance.is_active ? 'Идут технические работы' : 'Плановые технические работы' }}
        </span>
        <span class="mx-1.5 text-amber-400" aria-hidden="true">·</span>
        <span class="tabular-nums">{{ windowLabel }}</span>
        <span v-if="maintenance.message" class="block sm:inline sm:ml-1.5 opacity-90">
          {{ maintenance.message }}
        </span>
        <span v-else-if="maintenance.is_active" class="block sm:inline sm:ml-1.5 opacity-90">
          Часть функций временно недоступна.
        </span>
      </p>
    </div>
  </div>
</template>
