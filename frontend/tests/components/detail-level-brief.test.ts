/**
 * Behavioural test for the author brief folded into DetailLevelPicker: it
 * mounts the real SFC, so it fails if a preset chip stops filling the field or
 * an over-limit brief still reaches the save handler (the backend answers 422).
 */
import { createApp, computed, nextTick, ref, watch } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// The component uses Nuxt auto-imports as bare identifiers; in plain vitest
// those resolve through the scope chain to globalThis.
vi.stubGlobal('ref', ref)
vi.stubGlobal('computed', computed)
vi.stubGlobal('watch', watch)

const DetailLevelPicker = (await import('../../src/components/lesson/DetailLevelPicker.vue')).default

const BRIEF_MAX_CHARS = 1000

let root: HTMLElement
const saveBrief = vi.fn()

const mount = (narrationBrief = '') => {
  root = document.createElement('div')
  document.body.appendChild(root)
  createApp(DetailLevelPicker, {
    isManual: false,
    options: [{ value: 'auto', label: 'Средне', hint: 'по умолчанию' }],
    detailLevel: 'auto',
    durationLabels: { auto: '~10 мин' },
    actualDurationLabel: null,
    hasContent: true,
    error: '',
    narrationBrief,
    briefError: '',
    onSaveBrief: saveBrief,
  }).mount(root)
}

const byText = (selector: string, text: string) =>
  [...root.querySelectorAll<HTMLElement>(selector)].find((el) => el.textContent?.includes(text))

const openBrief = async () => {
  byText('button', 'Уточнения для ИИ')!.click()
  await nextTick()
}

const textarea = () => root.querySelector('textarea')!

const type = async (value: string) => {
  const el = textarea()
  el.value = value
  el.dispatchEvent(new Event('input'))
  await nextTick()
}

beforeEach(() => {
  saveBrief.mockClear()
  document.body.innerHTML = ''
})

describe('DetailLevelPicker author brief', () => {
  it('keeps the default path one click away — the field starts collapsed', () => {
    mount()
    expect(root.querySelector('textarea')).toBeNull()
  })

  it('inserts a preset into the field and does not duplicate it', async () => {
    mount()
    await openBrief()

    const chip = byText('button', 'Аудитория — 9 класс')!
    chip.click()
    await nextTick()
    expect(textarea().value).toBe('Аудитория — 9 класс')

    byText('button', 'Больше практических примеров')!.click()
    await nextTick()
    expect(textarea().value).toBe('Аудитория — 9 класс\nБольше практических примеров')

    chip.click()
    await nextTick()
    expect(textarea().value).toBe('Аудитория — 9 класс\nБольше практических примеров')
  })

  it('counts characters against the limit', async () => {
    mount()
    await openBrief()
    await type('абв')
    expect(root.textContent).toContain(`3 / ${BRIEF_MAX_CHARS}`)
  })

  it('saves a brief on blur', async () => {
    mount()
    await openBrief()
    await type('Аудитория — 9 класс')
    textarea().dispatchEvent(new Event('blur'))
    await nextTick()
    expect(saveBrief).toHaveBeenCalledWith('Аудитория — 9 класс')
  })

  it('blocks the save once the brief is over the limit', async () => {
    mount()
    await openBrief()
    await type('я'.repeat(BRIEF_MAX_CHARS + 1))
    textarea().dispatchEvent(new Event('blur'))
    await nextTick()

    expect(saveBrief).not.toHaveBeenCalled()
    expect(root.textContent).toContain('Слишком длинно')
  })

  it('opens itself when the lesson already carries a brief', () => {
    mount('Аудитория — 9 класс')
    expect(textarea().value).toBe('Аудитория — 9 класс')
  })

  it('stays hidden in manual mode — the brief only steers the vision analysis', async () => {
    root = document.createElement('div')
    document.body.appendChild(root)
    createApp(DetailLevelPicker, {
      isManual: true,
      options: [{ value: 'auto', label: 'Как есть', hint: '' }],
      detailLevel: 'auto',
      durationLabels: {},
      actualDurationLabel: null,
      hasContent: true,
      error: '',
    }).mount(root)
    await nextTick()
    expect(byText('button', 'Уточнения для ИИ')).toBeUndefined()
  })
})
