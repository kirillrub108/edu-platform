/**
 * Behaviour guard for the mobile navigation menu. The header burger used to
 * flip a ref that nothing rendered; these tests pin the state machine that
 * replaced it — including the body scroll lock, which must never survive the
 * menu (a stuck `overflow: hidden` makes the whole app unscrollable).
 */
import { effectScope, nextTick, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const route = reactive({ fullPath: '/dashboard' })
vi.stubGlobal('useRoute', () => route)

const { useMobileMenu } = await import('~/composables/useMobileMenu')

/** Runs the composable in a disposable scope so onScopeDispose is exercised. */
const mount = () => {
  const scope = effectScope()
  const menu = scope.run(() => useMobileMenu())!
  return { menu, dispose: () => scope.stop() }
}

beforeEach(() => {
  route.fullPath = '/dashboard'
  document.body.style.overflow = ''
})

describe('useMobileMenu', () => {
  it('toggles open and closed', () => {
    const { menu, dispose } = mount()
    expect(menu.isOpen.value).toBe(false)

    menu.toggle()
    expect(menu.isOpen.value).toBe(true)

    menu.toggle()
    expect(menu.isOpen.value).toBe(false)
    dispose()
  })

  it('locks body scroll while open and restores it on close', () => {
    const { menu, dispose } = mount()

    menu.open()
    expect(document.body.style.overflow).toBe('hidden')

    menu.close()
    expect(document.body.style.overflow).toBe('')
    dispose()
  })

  it('restores a pre-existing body overflow value rather than blanking it', () => {
    document.body.style.overflow = 'clip'
    const { menu, dispose } = mount()

    menu.open()
    expect(document.body.style.overflow).toBe('hidden')
    menu.close()
    expect(document.body.style.overflow).toBe('clip')
    dispose()
  })

  it('closes on route change', async () => {
    const { menu, dispose } = mount()
    menu.open()

    route.fullPath = '/billing'
    await nextTick()

    expect(menu.isOpen.value).toBe(false)
    expect(document.body.style.overflow).toBe('')
    dispose()
  })

  it('closes on Escape', () => {
    const { menu, dispose } = mount()
    menu.open()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(menu.isOpen.value).toBe(false)
    expect(document.body.style.overflow).toBe('')
    dispose()
  })

  it('ignores other keys', () => {
    const { menu, dispose } = mount()
    menu.open()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))

    expect(menu.isOpen.value).toBe(true)
    dispose()
  })

  it('unlocks body scroll when unmounted while still open', () => {
    const { menu, dispose } = mount()
    menu.open()
    expect(document.body.style.overflow).toBe('hidden')

    dispose()

    expect(document.body.style.overflow).toBe('')
  })

  it('stops listening for Escape after dispose', () => {
    const { menu, dispose } = mount()
    dispose()

    menu.open()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(menu.isOpen.value).toBe(true)
    document.body.style.overflow = ''
  })
})
