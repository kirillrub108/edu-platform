<script setup lang="ts">
import { Menu } from 'lucide-vue-next'

// Nav-driven shell for the student personal cabinet. The existing `student`
// layout (course/lesson browser) is left untouched and still serves the lesson
// viewer; this layout only wraps the cabinet's dashboard/list pages.
const cabinet = useStudentCabinetStore()
</script>

<template>
  <div class="flex flex-col h-screen overflow-hidden">
    <AppHeader />

    <div class="flex flex-1 overflow-hidden">
      <!-- Mobile backdrop -->
      <div
        v-if="cabinet.sidebarOpen"
        class="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
        @click="cabinet.sidebarOpen = false"
      />

      <!-- Sidebar: fixed drawer on mobile, static column on desktop -->
      <aside
        class="fixed inset-y-0 left-0 z-50 w-72 bg-white border-r border-gray-100 flex flex-col
               transition-transform duration-200 lg:static lg:translate-x-0"
        :class="cabinet.sidebarOpen ? 'translate-x-0' : '-translate-x-full'"
      >
        <StudentSidebar />
      </aside>

      <div class="flex-1 flex flex-col overflow-hidden">
        <!-- Mobile sub-header: burger toggles the drawer -->
        <div class="lg:hidden h-12 flex-shrink-0 bg-white border-b border-gray-100 flex items-center px-4">
          <button
            class="p-1.5 rounded-lg text-gray-600 hover:bg-gray-100 transition"
            aria-label="Открыть меню"
            @click="cabinet.sidebarOpen = true"
          >
            <Menu class="w-5 h-5" />
          </button>
        </div>

        <main class="flex-1 overflow-y-auto bg-transparent">
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>
