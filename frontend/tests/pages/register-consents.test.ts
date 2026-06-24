/**
 * Guards the registration form's consent gating.
 *
 * Same constraint as the other page specs: there is no component-mount harness
 * here (@vue/test-utils isn't a dependency and npm is banned), so this asserts
 * that register.vue wires the consent contract correctly — three never-prechecked
 * checkboxes, submit gated on the two mandatory ones only (marketing excluded),
 * and the legal links opening in a new tab.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const registerPage = resolve(process.cwd(), 'src/pages/register.vue')

describe('register consent gating', () => {
  const source = readFileSync(registerPage, 'utf-8')

  it('initialises all three consent checkboxes unchecked', () => {
    expect(source).toContain('const acceptedPrivacy = ref(false)')
    expect(source).toContain('const acceptedTerms = ref(false)')
    expect(source).toContain('const acceptedMarketing = ref(false)')
    // No checkbox may ever start ticked.
    expect(source).not.toMatch(/accepted\w+ = ref\(true\)/)
  })

  it('gates submission on both mandatory consents and excludes marketing', () => {
    expect(source).toContain(
      'const consentsGiven = computed(() => acceptedPrivacy.value && acceptedTerms.value)',
    )
    expect(source).not.toContain('acceptedMarketing.value && ')
    expect(source).not.toContain('&& acceptedMarketing.value')
    expect(source).toContain(':disabled="!consentsGiven"')
  })

  it('binds each checkbox to its own consent flag', () => {
    expect(source).toContain('v-model="acceptedPrivacy"')
    expect(source).toContain('v-model="acceptedTerms"')
    expect(source).toContain('v-model="acceptedMarketing"')
  })

  it('opens the legal documents in a new tab', () => {
    expect(source).toMatch(/to="\/legal\/privacy"\s+target="_blank"/)
    expect(source).toMatch(/to="\/legal\/terms"\s+target="_blank"/)
  })

  it('forwards the consent flags through the store register action', () => {
    expect(source).toContain('accepted_privacy: acceptedPrivacy.value')
    expect(source).toContain('accepted_terms: acceptedTerms.value')
    expect(source).toContain('accepted_marketing: acceptedMarketing.value')
  })
})
