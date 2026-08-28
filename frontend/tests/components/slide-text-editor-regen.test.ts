/**
 * Behavioural test for SlideTextEditor's regenerate flow: it mounts the real
 * SFC and drives it through a controllable apiFetch, so it fails if the
 * regenerated text does not actually reach the textarea and the derived
 * word/duration counters.
 */
import { createApp, computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  countWords,
  estimateDurationSec,
  formatDuration,
} from '../../src/composables/useLessonDuration'

// The component uses Nuxt auto-imports as bare identifiers; in plain vitest
// those resolve through the scope chain to globalThis.
vi.stubGlobal('ref', ref)
vi.stubGlobal('computed', computed)
vi.stubGlobal('watch', watch)
vi.stubGlobal('onMounted', onMounted)
vi.stubGlobal('onUnmounted', onUnmounted)

const apiFetch = vi.fn()
vi.stubGlobal('useApi', () => ({ apiFetch }))
vi.stubGlobal('useBillingStore', () => ({
  refresh: vi.fn(async () => undefined),
  fetchBalance: vi.fn(async () => undefined),
}))
vi.stubGlobal('useAiGuard', () => ({
  ensureVerified: async (action: () => unknown) => { await action() },
}))

const SlideTextEditor = (await import('../../src/components/SlideTextEditor.vue')).default

const slideFixture = (n: number, text: string) => ({
  id: `s${n}`,
  slide_number: n,
  image_url: `http://img/${n}.png`,
  generated_text: text,
  edited_text: null,
  is_edited: false,
})

/** Flush the microtask chain that loadSlides / regenerate await. */
const flush = async () => {
  for (let i = 0; i < 8; i++) await nextTick()
}

let exposed: any = null

const mount = () => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(SlideTextEditor, { lessonId: 'L1', detailLevel: 'auto' })
  app.config.warnHandler = () => undefined
  app.component('NuxtLink', { template: '<a><slot /></a>' })
  app.component('ProgressBar', { template: '<div />' })
  exposed = app.mount(host)
  return host
}

const textarea = (host: HTMLElement) => host.querySelector('textarea') as HTMLTextAreaElement
const buttonByText = (host: HTMLElement, label: string) =>
  [...host.querySelectorAll('button')].find(b => b.textContent?.includes(label)) as HTMLButtonElement

describe('SlideTextEditor — regenerate updates the panel without a reload', () => {
  beforeEach(() => {
    apiFetch.mockReset()
    document.body.innerHTML = ''
  })

  it('replaces the textarea text and the word/duration counters in place', async () => {
    const NEW_TEXT = 'Совершенно новый текст озвучки после регенерации модели ' +
      'с существенно большим количеством слов чем было раньше здесь.'
    let resolveRegen: (v: unknown) => void = () => undefined
    const regenPromise = new Promise(r => { resolveRegen = r })

    apiFetch.mockImplementation((path: string) => {
      if (path.endsWith('/slides')) {
        return Promise.resolve({
          slides: [slideFixture(1, 'Старый текст'), slideFixture(2, 'Второй слайд')],
          total: 2,
          status: 'ready_for_edit',
        })
      }
      if (path.includes('/regenerate')) return regenPromise
      return Promise.resolve(slideFixture(1, 'Старый текст'))
    })

    const host = mount()
    await flush()
    expect(textarea(host).value).toBe('Старый текст')

    buttonByText(host, 'Регенерировать LLM').click()
    await flush()

    resolveRegen({ ...slideFixture(1, NEW_TEXT), edited_text: null })
    await flush()

    // The actual regression: text must land in the panel with no page reload.
    expect(textarea(host).value).toBe(NEW_TEXT)

    // ...and everything derived from it must recompute.
    const words = countWords(NEW_TEXT)
    expect(host.textContent).toContain(`Слов: ${words}`)
    expect(host.textContent).toContain(`${formatDuration(estimateDurationSec(words))} мин`)
  })

  it('lands the text on the requested slide even if the user navigated away', async () => {
    const NEW_TEXT = 'Регенерированный текст первого слайда'
    let resolveRegen: (v: unknown) => void = () => undefined
    const regenPromise = new Promise(r => { resolveRegen = r })

    apiFetch.mockImplementation((path: string) => {
      if (path.endsWith('/slides')) {
        return Promise.resolve({
          slides: [slideFixture(1, 'Первый'), slideFixture(2, 'Второй')],
          total: 2,
          status: 'ready_for_edit',
        })
      }
      if (path.includes('/regenerate')) return regenPromise
      return Promise.resolve(slideFixture(1, 'Первый'))
    })

    const host = mount()
    await flush()

    buttonByText(host, 'Регенерировать LLM').click()
    await flush()

    // Switch to slide 2 while the 30-60s regen is still in flight.
    buttonByText(host, 'Следующий')?.click()
    host.querySelector<HTMLButtonElement>('[aria-label="Следующий"]')?.click()
    await flush()
    expect(textarea(host).value).toBe('Второй')

    resolveRegen({ ...slideFixture(1, NEW_TEXT), edited_text: null })
    await flush()

    // Slide 2 must be untouched by slide 1's response...
    expect(textarea(host).value).toBe('Второй')

    // ...and going back shows the regenerated text, no reload involved.
    host.querySelector<HTMLButtonElement>('[aria-label="Предыдущий"]')?.click()
    await flush()
    expect(textarea(host).value).toBe(NEW_TEXT)
  })

  // The reported bug: re-running the whole analysis rewrites every slide text,
  // but the editor stays mounted (showSlideEditor is already true), so nothing
  // re-fetched and the panel showed pre-analysis text until a page reload.
  it('reloadSlides() pulls fresh texts into the still-mounted editor', async () => {
    let payload = {
      slides: [slideFixture(1, 'Текст до анализа'), slideFixture(2, 'Второй до анализа')],
      total: 2,
      status: 'ready_for_edit',
    }
    apiFetch.mockImplementation((path: string) => {
      if (path.endsWith('/slides')) return Promise.resolve(payload)
      return Promise.resolve(slideFixture(1, 'x'))
    })

    const host = mount()
    await flush()
    expect(textarea(host).value).toBe('Текст до анализа')

    // Analysis finished server-side: every slide now has new narration.
    const AFTER = 'Полностью новый текст после повторного анализа слайда'
    payload = {
      slides: [slideFixture(1, AFTER), slideFixture(2, 'Второй после анализа')],
      total: 2,
      status: 'ready_for_edit',
    }

    exposed.reloadSlides()
    await flush()

    expect(textarea(host).value).toBe(AFTER)
    expect(host.textContent).toContain(`Слов: ${countWords(AFTER)}`)
  })

  it('does not fire a second request while a regen is already in flight', async () => {
    apiFetch.mockImplementation((path: string) => {
      if (path.endsWith('/slides')) {
        return Promise.resolve({
          slides: [slideFixture(1, 'Первый')],
          total: 1,
          status: 'ready_for_edit',
        })
      }
      if (path.includes('/regenerate')) return new Promise(() => undefined)
      return Promise.resolve(slideFixture(1, 'Первый'))
    })

    const host = mount()
    await flush()

    buttonByText(host, 'Регенерировать LLM').click()
    await flush()
    buttonByText(host, 'Регенерировать LLM')?.click()
    await flush()

    const regenCalls = apiFetch.mock.calls.filter(c => String(c[0]).includes('/regenerate'))
    expect(regenCalls).toHaveLength(1)
  })
})
