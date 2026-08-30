<!-- Аватар + имя в шапке кабинета: сам по себе триггер меню
     (Профиль / Настройки / Выйти), а не ссылка. Механика поповера повторяет
     SocialLinksMenu — клик мимо, Escape, возврат фокуса, закрытие на смене
     роута. Отдельная кнопка выхода в шапке не нужна: она здесь. -->
<script setup lang="ts">
import { ChevronDown, LogOut, Settings, UserRound } from 'lucide-vue-next'

const auth = useAuthStore()
const { user } = storeToRefs(auth)
const { logout } = auth

const isOpen = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const buttonRef = ref<HTMLElement | null>(null)
const route = useRoute()

const close = (returnFocus = false) => {
  if (!isOpen.value) return
  isOpen.value = false
  if (returnFocus) buttonRef.value?.focus()
}

// pointerdown, а не click: иначе меню закрывается уже после того, как клик
// дошёл до элемента под ним.
const onPointerDown = (event: PointerEvent) => {
  if (!rootRef.value?.contains(event.target as Node)) close()
}
const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') close(true)
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeydown)
})

watch(() => route.fullPath, () => close())

const onLogout = () => {
  close()
  logout()
}

const itemClass =
  'flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition'
</script>

<template>
  <div ref="rootRef" class="relative">
    <button
      ref="buttonRef"
      type="button"
      class="flex items-center gap-2.5 -ml-1.5 pl-1.5 pr-2 py-1 rounded-lg hover:bg-gray-100 transition"
      :class="isOpen ? 'bg-gray-100' : ''"
      aria-haspopup="true"
      :aria-expanded="isOpen"
      @click="isOpen = !isOpen"
    >
      <!-- UserAvatar намеренно без `linked`: внутри кнопки ссылка ломает
           и разметку, и сам клик по триггеру. -->
      <UserAvatar :user="user" size="sm" />
      <div class="leading-tight text-left">
        <div class="text-sm font-medium text-gray-900">{{ user?.full_name || user?.email }}</div>
        <div class="text-[11px] text-gray-500">
          {{ user?.role === 'teacher' ? 'Автор' : 'Студент' }}
        </div>
      </div>
      <ChevronDown
        class="w-4 h-4 shrink-0 text-gray-400 transition-transform"
        :class="isOpen ? 'rotate-180' : ''"
      />
    </button>

    <Transition
      enter-active-class="transition duration-150"
      leave-active-class="transition duration-100"
      enter-from-class="opacity-0 -translate-y-1"
      leave-to-class="opacity-0 -translate-y-1"
    >
      <div
        v-if="isOpen"
        class="absolute right-0 top-full mt-2 z-40 w-56 rounded-xl border border-violet-100 bg-white shadow-lg p-1.5"
      >
        <NuxtLink v-if="user" :to="`/u/${user.id}`" :class="itemClass" @click="close()">
          <UserRound class="w-4 h-4 shrink-0 text-gray-400" />
          Профиль
        </NuxtLink>
        <NuxtLink to="/account" :class="itemClass" @click="close()">
          <Settings class="w-4 h-4 shrink-0 text-gray-400" />
          Настройки
        </NuxtLink>
        <div class="my-1 border-t border-gray-100" />
        <button type="button" :class="itemClass" @click="onLogout">
          <LogOut class="w-4 h-4 shrink-0 text-gray-400" />
          Выйти
        </button>
      </div>
    </Transition>
  </div>
</template>
