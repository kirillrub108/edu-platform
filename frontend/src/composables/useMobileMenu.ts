import { onScopeDispose, ref, watch, type Ref } from 'vue'

export interface MobileMenu {
  /** Whether the mobile panel is currently shown. */
  isOpen: Ref<boolean>
  /** Bind to the toggle button (`ref="triggerRef"`) so focus can return to it. */
  triggerRef: Ref<HTMLElement | null>
  open: () => void
  close: () => void
  toggle: () => void
}

/**
 * Open/close state for a mobile navigation panel.
 *
 * Closes on route change, on Escape and on demand (backdrop tap). While open it
 * locks `body` scroll — otherwise iOS Safari scrolls the page *behind* the
 * fixed panel and the user loses their position. The previous inline value is
 * restored rather than blanked, and the cleanup also runs on scope dispose so
 * an unmount mid-navigation can never leave the page permanently unscrollable.
 */
export function useMobileMenu(): MobileMenu {
  const isOpen = ref(false)
  const triggerRef = ref<HTMLElement | null>(null)
  const route = useRoute()

  let previousOverflow = ''

  const lockScroll = () => {
    if (typeof document === 'undefined') return
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }

  const unlockScroll = () => {
    if (typeof document === 'undefined') return
    document.body.style.overflow = previousOverflow
  }

  const open = () => {
    if (isOpen.value) return
    isOpen.value = true
    lockScroll()
  }

  const close = () => {
    if (!isOpen.value) return
    isOpen.value = false
    unlockScroll()
    triggerRef.value?.focus()
  }

  const toggle = () => (isOpen.value ? close() : open())

  const onKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') close()
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('keydown', onKeydown)
  }

  watch(() => route.fullPath, () => close())

  onScopeDispose(() => {
    if (typeof document !== 'undefined') {
      document.removeEventListener('keydown', onKeydown)
    }
    if (isOpen.value) unlockScroll()
  })

  return { isOpen, triggerRef, open, close, toggle }
}
