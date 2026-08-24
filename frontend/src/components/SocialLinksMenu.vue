<!-- Кнопка «Мы в соц. сетях» с выпадающим меню. Живёт в шапке кабинета
     (AppHeader), поэтому закрывается по клику мимо, Escape, смене роута и
     выбору ссылки. Ссылки берутся из SocialLinks — здесь только поповер. -->
<script setup lang="ts">
import { Share2 } from 'lucide-vue-next'

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
</script>

<template>
  <div ref="rootRef" class="relative">
    <button
      ref="buttonRef"
      type="button"
      class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-gray-700 bg-gray-50 border border-gray-200 hover:bg-gray-100 transition"
      :class="isOpen ? '!bg-violet-50 !border-violet-100 !text-violet-700' : ''"
      aria-label="Мы в соц. сетях"
      title="Мы в соц. сетях"
      aria-haspopup="true"
      :aria-expanded="isOpen"
      @click="isOpen = !isOpen"
    >
      <Share2 class="w-3.5 h-3.5 shrink-0" />
      <!-- Ниже lg шапка и так плотная — остаётся иконка, название уезжает
           в aria-label/title. -->
      <span class="hidden lg:inline whitespace-nowrap">Мы в соц. сетях</span>
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
        <SocialLinks variant="menu" @click="close()" />
      </div>
    </Transition>
  </div>
</template>
