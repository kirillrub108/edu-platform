<script setup lang="ts">
import {
  LogOut, Menu, X, MailWarning, Coins, Settings, Bug,
  LayoutDashboard, BarChart3, Wallet, BookOpen, ClipboardList, FileQuestion, ChevronDown, Share2,
  type LucideIcon,
} from 'lucide-vue-next'

const auth = useAuthStore()
const { user, isAuthenticated, isEmailVerified } = storeToRefs(auth)
const { logout, openVerifyPrompt } = auth

const billing = useBillingStore()
const { available } = storeToRefs(billing)
const isTeacher = computed(() => user.value?.role === 'teacher')

onMounted(async () => {
  if (!user.value) await auth.fetchMe()
  if (isTeacher.value) billing.fetchBalance()
})

// Refresh the balance whenever a teacher session appears (login, reload),
// so the header counter is always current without polling.
watch(() => user.value?.role, (role) => {
  if (role === 'teacher') billing.fetchBalance()
})

const { isOpen, triggerRef, close, toggle } = useMobileMenu()

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
}

// Mirrors of the desktop navigation: AppSidebar (teacher) and
// StudentSidebar (student). Keep both lists in sync with their source.
const TEACHER_NAV: NavItem[] = [
  { to: '/dashboard', label: 'Мои курсы', icon: LayoutDashboard },
  { to: '/analytics/quiz-results', label: 'Результаты тестов', icon: BarChart3 },
  { to: '/billing', label: 'Баланс', icon: Wallet },
]

const STUDENT_NAV: NavItem[] = [
  { to: '/student/dashboard', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/student/courses', label: 'Мои курсы', icon: BookOpen },
  { to: '/student/assignments', label: 'Задания', icon: ClipboardList },
  { to: '/student/quizzes', label: 'Тесты', icon: FileQuestion },
  { to: '/student/results', label: 'Результаты', icon: BarChart3 },
]

const mobileNav = computed<NavItem[]>(() => {
  if (!isAuthenticated.value) return []
  return isTeacher.value ? TEACHER_NAV : STUDENT_NAV
})

// Аккордеон соцсетей в мобильной шторке. Схлопывается вместе со шторкой,
// чтобы при следующем открытии список не занимал пол-экрана.
const isSocialOpen = ref(false)
watch(isOpen, (open) => {
  if (!open) isSocialOpen.value = false
})

const handleVerifyPrompt = () => {
  close()
  openVerifyPrompt()
}

const handleLogout = () => {
  close()
  logout()
}
</script>

<template>
  <header class="bg-white border-b border-violet-100 sticky top-0 z-30">
    <MaintenanceBanner />

    <div class="px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
      <NuxtLink to="/" class="flex items-center min-w-0">
        <AppLogo />
      </NuxtLink>

<div v-if="isAuthenticated" class="hidden md:flex items-center gap-3">
        <SupportContactLink
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-gray-700 bg-gray-50 border border-gray-200 hover:bg-gray-100 transition"
        >
          <Bug class="w-3.5 h-3.5" />
          Написать нам
        </SupportContactLink>
        <SocialLinksMenu />
        <NuxtLink
          v-if="isTeacher"
          to="/billing"
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold text-violet-700 bg-violet-50 border border-violet-100 hover:bg-violet-100 transition tabular-nums"
          title="Баланс кредитов"
        >
          <Coins class="w-3.5 h-3.5" />
          {{ available }}
        </NuxtLink>
        <button
          v-if="user && !isEmailVerified"
          type="button"
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 hover:bg-amber-100 transition"
          title="Подтвердите email, чтобы открыть AI-функции"
          @click="openVerifyPrompt"
        >
          <MailWarning class="w-3.5 h-3.5" />
          Почта не подтверждена
        </button>
        <UserMenu />
      </div>

      <div v-else class="hidden md:flex items-center gap-2">
        <SupportContactLink
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-gray-700 bg-gray-50 border border-gray-200 hover:bg-gray-100 transition"
        >
          <Bug class="w-3.5 h-3.5" />
          Написать нам
        </SupportContactLink>
        <SocialLinksMenu class="mr-2" />
        <NuxtLink
          to="/login"
          class="px-4 py-2 rounded-xl text-sm font-medium text-gray-700 hover:text-violet-700 transition"
        >
          Войти
        </NuxtLink>
        <NuxtLink
          to="/register"
          class="px-5 py-2.5 rounded-xl text-sm font-medium bg-brand-gradient text-white shadow-sm hover:brightness-110 transition"
        >
          Создать аккаунт
        </NuxtLink>
      </div>

      <div class="md:hidden flex items-center gap-1.5 shrink-0">
        <NuxtLink
          v-if="isAuthenticated && isTeacher"
          to="/billing"
          class="flex items-center gap-1 px-2.5 h-11 rounded-lg text-xs font-semibold text-violet-700 bg-violet-50 border border-violet-100 tabular-nums"
          aria-label="Баланс кредитов"
        >
          <Coins class="w-3.5 h-3.5" />
          {{ available }}
        </NuxtLink>
        <button
          ref="triggerRef"
          type="button"
          class="w-11 h-11 grid place-items-center rounded-lg text-gray-700 hover:bg-gray-100 transition"
          aria-label="Меню"
          aria-controls="mobile-menu"
          :aria-expanded="isOpen"
          @click="toggle"
        >
          <Menu class="w-6 h-6" />
        </button>
      </div>
    </div>

    <!-- Teleported to body so the sticky header's stacking context can never
         clip or cover the drawer. -->
    <Teleport to="body">
      <Transition
        :duration="150"
        enter-active-class="transition-opacity duration-150"
        leave-active-class="transition-opacity duration-150"
        enter-from-class="opacity-0"
        leave-to-class="opacity-0"
      >
        <div
          v-if="isOpen"
          class="md:hidden fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
          @click="close"
        />
      </Transition>

      <Transition
        :duration="200"
        enter-active-class="transition-transform duration-200"
        leave-active-class="transition-transform duration-200"
        enter-from-class="translate-x-full"
        leave-to-class="translate-x-full"
      >
        <div
          v-if="isOpen"
          id="mobile-menu"
          role="dialog"
          aria-modal="true"
          aria-label="Главное меню"
          class="md:hidden fixed inset-y-0 right-0 z-50 w-[85%] max-w-xs bg-white shadow-xl
                 flex flex-col overflow-y-auto overscroll-contain"
          style="padding-bottom: env(safe-area-inset-bottom)"
        >
          <div class="h-16 shrink-0 flex items-center justify-between px-4 border-b border-violet-100">
            <span class="text-sm font-semibold text-gray-900">Меню</span>
            <button
              type="button"
              class="w-11 h-11 -mr-2 grid place-items-center rounded-lg text-gray-500 hover:bg-gray-100 transition"
              aria-label="Закрыть меню"
              @click="close"
            >
              <X class="w-5 h-5" />
            </button>
          </div>

          <NuxtLink
            v-if="isAuthenticated"
            to="/account"
            class="shrink-0 px-4 py-3 flex items-center gap-3 border-b border-gray-100 hover:bg-gray-50 transition"
          >
            <UserAvatar :user="user" size="md" />
            <div class="min-w-0 leading-tight">
              <div class="text-sm font-medium text-gray-900 truncate">
                {{ user?.full_name || user?.email }}
              </div>
              <div class="text-[11px] text-gray-500">
                {{ isTeacher ? 'Автор' : 'Студент' }}
              </div>
            </div>
          </NuxtLink>

          <nav v-if="mobileNav.length" class="p-2 flex flex-col gap-0.5">
            <NuxtLink
              v-for="item in mobileNav"
              :key="item.to"
              :to="item.to"
              class="flex items-center gap-3 px-3 min-h-[44px] rounded-xl text-sm font-medium text-gray-700 hover:bg-violet-50 hover:text-violet-700 transition"
              active-class="!text-violet-700 !bg-violet-50"
            >
              <component :is="item.icon" class="w-5 h-5 shrink-0" />
              <span class="min-w-0 truncate">{{ item.label }}</span>
            </NuxtLink>
          </nav>

          <div class="mt-auto p-2 border-t border-gray-100 flex flex-col gap-0.5">
            <button
              v-if="isAuthenticated && user && !isEmailVerified"
              type="button"
              class="flex items-center gap-3 px-3 min-h-[44px] rounded-xl text-sm font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 transition text-left"
              @click="handleVerifyPrompt"
            >
              <MailWarning class="w-5 h-5 shrink-0" />
              <span class="min-w-0">Почта не подтверждена</span>
            </button>

            <template v-if="isAuthenticated">
              <button
                type="button"
                class="flex items-center gap-3 px-3 min-h-[44px] rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 transition text-left"
                @click="handleLogout"
              >
                <LogOut class="w-5 h-5 shrink-0" />
                Выйти
              </button>
            </template>
            <template v-else>
              <NuxtLink
                to="/login"
                class="flex items-center px-3 min-h-[44px] rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 transition"
              >
                Войти
              </NuxtLink>
              <NuxtLink
                to="/register"
                class="flex items-center justify-center px-3 min-h-[44px] rounded-xl text-sm font-medium bg-brand-gradient text-white shadow-sm"
              >
                Создать аккаунт
              </NuxtLink>
            </template>

            <button
              type="button"
              class="flex items-center gap-3 px-3 min-h-[44px] rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 transition text-left"
              aria-controls="mobile-social"
              :aria-expanded="isSocialOpen"
              @click="isSocialOpen = !isSocialOpen"
            >
              <Share2 class="w-5 h-5 shrink-0" />
              <span class="min-w-0 flex-1">Мы в соц. сетях</span>
              <ChevronDown
                class="w-4 h-4 shrink-0 text-gray-400 transition-transform duration-200"
                :class="isSocialOpen ? 'rotate-180' : ''"
              />
            </button>
            <!-- Раскрытие на grid-rows вместо max-height: не нужно угадывать
                 высоту списка, анимация чисто на CSS. -->
            <div
              id="mobile-social"
              class="grid transition-all duration-200"
              :class="isSocialOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
            >
              <div class="overflow-hidden pl-5">
                <SocialLinks variant="menu" @click="close()" />
              </div>
            </div>

            <SupportContactLink
              class="flex items-center gap-3 px-3 min-h-[44px] rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 transition"
            >
              <Bug class="w-5 h-5 shrink-0" />
              Написать нам
            </SupportContactLink>

            <NuxtLink
              v-if="isAuthenticated"
              to="/account"
              class="flex items-center gap-3 px-3 min-h-[44px] rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 transition"
            >
              <Settings class="w-5 h-5 shrink-0" />
              <span class="min-w-0 truncate">Настройки аккаунта</span>
            </NuxtLink>
          </div>
        </div>
      </Transition>
    </Teleport>
  </header>
</template>
