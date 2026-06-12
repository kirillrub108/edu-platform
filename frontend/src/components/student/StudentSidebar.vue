<script setup lang="ts">
import {
  LayoutDashboard,
  BookOpen,
  ClipboardList,
  FileQuestion,
  BarChart3,
  type LucideIcon,
} from 'lucide-vue-next'

interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  // Active when the current path starts with this prefix.
  match: string
}

const cabinet = useStudentCabinetStore()
const route = useRoute()

const items: NavItem[] = [
  { label: 'Дашборд', to: '/student/dashboard', icon: LayoutDashboard, match: '/student/dashboard' },
  { label: 'Мои курсы', to: '/student/courses', icon: BookOpen, match: '/student/courses' },
  { label: 'Задания', to: '/student/assignments', icon: ClipboardList, match: '/student/assignments' },
  { label: 'Тесты', to: '/student/quizzes', icon: FileQuestion, match: '/student/quizzes' },
  { label: 'Результаты', to: '/student/results', icon: BarChart3, match: '/student/results' },
]

const isActive = (item: NavItem) => route.path.startsWith(item.match)

// On mobile the sidebar is a drawer — collapse it after navigating.
const handleNav = () => {
  cabinet.sidebarOpen = false
}
</script>

<template>
  <nav class="flex-1 overflow-y-auto p-3 space-y-1">
    <div class="px-2 pb-3 text-xs font-semibold text-gray-400 uppercase tracking-wide">
      Личный кабинет
    </div>
    <NuxtLink
      v-for="item in items"
      :key="item.to"
      :to="item.to"
      class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition"
      :class="isActive(item)
        ? 'bg-violet-50 text-violet-700'
        : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'"
      @click="handleNav"
    >
      <component :is="item.icon" class="w-5 h-5 flex-shrink-0" />
      <span class="flex-1">{{ item.label }}</span>
    </NuxtLink>
  </nav>
</template>
