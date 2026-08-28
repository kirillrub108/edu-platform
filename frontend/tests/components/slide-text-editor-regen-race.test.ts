/**
 * Cross-file wiring guard. The in-panel behaviour is covered for real by
 * slide-text-editor-regen.test.ts (which mounts the SFC); what a single-component
 * mount cannot see is the chain that tells an already-open editor to re-fetch
 * after an analysis run: useVisionAnalysis → LessonUploadSection → VisionPanel →
 * SlideTextEditor. That chain is what broke, so assert every link exists.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(resolve(process.cwd(), rel), 'utf-8')
const editor = read('src/components/SlideTextEditor.vue')
const visionPanel = read('src/components/lesson/VisionPanel.vue')
const uploadSection = read('src/components/LessonUploadSection.vue')
const analysis = read('src/composables/useVisionAnalysis.ts')

describe('reloadSlides is exposed all the way up the panel chain', () => {
  it('SlideTextEditor exposes it', () => {
    expect(editor).toMatch(/defineExpose\(\{[^}]*reloadSlides: loadSlides/)
  })

  it('VisionPanel and LessonUploadSection forward it', () => {
    expect(visionPanel).toMatch(/reloadSlides: \(\) => slideEditorRef\.value\?\.reloadSlides\(\)/)
    expect(uploadSection).toMatch(/reloadSlides: \(\) => innerVisionRef\.value\?\.reloadSlides\(\)/)
  })

  it('every analysis-completion path calls it', () => {
    // SSE terminal, task-status SUCCESS, and the no-task-id status poll.
    expect(analysis.match(/panelRef\.value\?\.reloadSlides\(\)/g)).toHaveLength(3)
  })

  it('does not reload on the cancel/error paths, which restore instead', () => {
    const cancelled = analysis.match(/const onCancelledTerminal[\s\S]*?\n  \}/)?.[0] ?? ''
    expect(cancelled).toContain('restoreFromSnapshot')
    expect(cancelled).not.toContain('reloadSlides')
  })
})

describe('regenerate write ordering', () => {
  it('lets a landed regenerate win over an autosave that was already in flight', () => {
    expect(editor).toMatch(/const epoch = epochOf\(slide\.id\)/)
    expect(editor).toMatch(/if \(epochOf\(slide\.id\) === epoch\)/)
    expect(editor).toMatch(/regenEpoch\.set\(slide\.id, epochOf\(slide\.id\) \+ 1\)/)
  })

  it('does not abort an in-flight regen just because the viewed slide changed', () => {
    const watchBlock = editor.match(/watch\(currentIdx, \(\) => \{[\s\S]*?\}\)/)?.[0] ?? ''
    expect(watchBlock).not.toContain('regenController')
  })
})
