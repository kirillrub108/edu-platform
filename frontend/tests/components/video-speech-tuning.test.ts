/**
 * Guard for the SpeechKit speed/pitch controls. Same constraint as the other
 * component guards here (no @vue/test-utils, npm is banned), so this asserts the
 * source across the whole chain: composable state → page → LessonVideoSection →
 * VideoGenerationPanel, plus the "default means null" rule the backend relies on
 * to keep hints out of the request and cache keys unchanged.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(resolve(process.cwd(), rel), 'utf-8')
const composable = read('src/composables/useVideoGeneration.ts')
const page = read('src/pages/lessons/[id]/index.vue')
const section = read('src/components/LessonVideoSection.vue')
const panel = read('src/components/lesson/VideoGenerationPanel.vue')

describe('useVideoGeneration speech tuning', () => {
  it('holds speed/pitch at the SpeechKit defaults', () => {
    expect(composable).toMatch(/const selectedSpeed = ref<number>\(1\)/)
    expect(composable).toMatch(/const selectedPitch = ref<number>\(0\)/)
  })

  it('sends null at the defaults so the backend adds no hint', () => {
    expect(composable).toMatch(/speed: selectedSpeed\.value === 1 \? null : selectedSpeed\.value/)
    expect(composable).toMatch(/pitch: selectedPitch\.value === 0 \? null : selectedPitch\.value/)
  })

  it('exports both so the page can bind them', () => {
    expect(composable).toMatch(/selectedSpeed,\s*selectedPitch/)
  })
})

describe('prop chain page → section → panel', () => {
  it('page two-way binds both controls', () => {
    expect(page).toContain('v-model:selected-speed="selectedSpeed"')
    expect(page).toContain('v-model:selected-pitch="selectedPitch"')
    expect(page).toMatch(/selectedSpeed, selectedPitch/)
  })

  it('section forwards props down and events up', () => {
    expect(section).toContain(':selected-speed="selectedSpeed"')
    expect(section).toContain(':selected-pitch="selectedPitch"')
    expect(section).toContain("@update:selected-speed=\"emit('update:selectedSpeed', $event)\"")
    expect(section).toContain("@update:selected-pitch=\"emit('update:selectedPitch', $event)\"")
  })
})

describe('VideoGenerationPanel controls', () => {
  it('renders a slider per hint, disabled while generating', () => {
    expect(panel).toMatch(/type="range"[\s\S]{0,200}:value="selectedSpeed"/)
    expect(panel).toMatch(/type="range"[\s\S]{0,200}:value="selectedPitch"/)
    expect(panel.match(/:disabled="isProcessing"/g)?.length).toBeGreaterThanOrEqual(3)
  })

  it('keeps the sliders inside the ranges SpeechKit accepts', () => {
    // Speed hint: 0.1–3.0; pitchShift: -1000–1000. The UI stays well inside.
    expect(panel).toMatch(/min="0\.5"\s+max="2"/)
    expect(panel).toMatch(/min="-500"\s+max="500"/)
  })

  it('offers a reset that returns to the no-hint defaults', () => {
    expect(panel).toContain('function resetTuning')
    expect(panel).toMatch(/emit\('update:selectedSpeed', 1\)/)
    expect(panel).toMatch(/emit\('update:selectedPitch', 0\)/)
    expect(panel).toMatch(/v-if="!isDefaultTuning"/)
  })
})
