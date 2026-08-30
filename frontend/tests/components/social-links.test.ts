/**
 * SocialLinks.vue renders every entry of SOCIAL_LINKS as a safe external link.
 *
 * @vue/test-utils isn't a dependency (npm is banned in this repo), so the SFC's
 * <template> block is compiled here with `vue/compiler-sfc` — an official
 * subpath of the `vue` package, no new dependency — and mounted into happy-dom.
 * Setup state is supplied by the harness; only the template is under test.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import * as Vue from 'vue'
import { compileTemplate, parse } from 'vue/compiler-sfc'
import { SOCIAL_LINKS } from '~/composables/useSocialLinks'

const source = readFileSync(resolve(process.cwd(), 'src/components/SocialLinks.vue'), 'utf-8')
const { descriptor } = parse(source, { filename: 'SocialLinks.vue' })
const { code, errors } = compileTemplate({
  source: descriptor.template!.content,
  id: 'social-links',
  filename: 'SocialLinks.vue',
  // `with (_ctx)` mode — lets the harness feed setup state without evaluating
  // the TS <script setup> block.
  compilerOptions: { mode: 'function', prefixIdentifiers: false, cacheHandlers: false },
})
if (errors.length) throw errors[0]
const render = new Function('Vue', code)(Vue)

const ICON_PATHS = Object.fromEntries(SOCIAL_LINKS.map((l) => [l.key, 'M0 0']))

function mount(variant: 'compact' | 'cards' | 'menu') {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = Vue.createApp({
    props: { variant: { type: String, default: 'compact' } },
    render,
    setup: () => ({ links: SOCIAL_LINKS, ICON_PATHS }),
  }, { variant })
  app.config.warnHandler = () => {}
  app.mount(host)
  return host
}

describe('SocialLinks', () => {
  it('renders every link from SOCIAL_LINKS with matching hrefs', () => {
    const anchors = [...mount('compact').querySelectorAll('a')]
    expect(anchors).toHaveLength(SOCIAL_LINKS.length)
    expect(anchors.map((a) => a.getAttribute('href'))).toEqual(SOCIAL_LINKS.map((l) => l.href))
  })

  it('opens every link in a new tab without leaking the opener', () => {
    for (const anchor of mount('compact').querySelectorAll('a')) {
      expect(anchor.getAttribute('target')).toBe('_blank')
      expect(anchor.getAttribute('rel')).toBe('noopener noreferrer')
      expect(anchor.getAttribute('aria-label')).toBeTruthy()
    }
  })

  it('labels each link by its network name and hides icons from a11y', () => {
    const host = mount('cards')
    const anchors = [...host.querySelectorAll('a')]
    expect(anchors.map((a) => a.getAttribute('aria-label'))).toEqual(
      SOCIAL_LINKS.map((l) => l.label),
    )
    expect([...host.querySelectorAll('.social-label')].map((s) => s.textContent)).toEqual(
      SOCIAL_LINKS.map((l) => l.label),
    )
    expect(host.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(SOCIAL_LINKS.length)
  })

  it('hides labels only in the compact variant', () => {
    expect(mount('compact').querySelectorAll('.social-label')).toHaveLength(0)
    for (const variant of ['cards', 'menu'] as const) {
      const host = mount(variant)
      expect(host.querySelector('.social-links')?.className).toContain(variant)
      expect(host.querySelectorAll('.social-label')).toHaveLength(SOCIAL_LINKS.length)
    }
  })

  it('adds a hover tooltip only where the label is not visible', () => {
    const titles = (v: 'compact' | 'menu') =>
      [...mount(v).querySelectorAll('a')].map((a) => a.getAttribute('title'))
    expect(titles('compact')).toEqual(SOCIAL_LINKS.map((l) => l.label))
    expect(titles('menu')).toEqual(SOCIAL_LINKS.map(() => null))
  })
})
