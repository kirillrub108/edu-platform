/**
 * Safe markdown rendering for lesson notes.
 *
 * The load-bearing property is that note content NEVER becomes markup: the
 * renderer emits VNodes, so any HTML (or a javascript: link) in the source must
 * come out as visible text. Rendered through vue/server-renderer — no
 * @vue/test-utils in this project (npm is banned, see CLAUDE.md).
 */
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'

import { markdownNodes } from '../../src/utils/markdown'

const render = async (source: string): Promise<string> => {
  const Comp = defineComponent({ render: () => h('div', markdownNodes(source)) })
  return renderToString(createSSRApp(Comp))
}

describe('block rendering', () => {
  it('renders headings below the page level (h3..h5)', async () => {
    const html = await render('# Один\n## Два\n#### Четыре')
    expect(html).toContain('<h3')
    expect(html).toContain('Один')
    expect(html).toContain('<h4')
    // Deeper levels clamp at h5 so a note never outranks the page outline.
    expect(html).toContain('<h5')
  })

  it('renders unordered and ordered lists', async () => {
    const bullets = await render('- первый\n- второй')
    expect(bullets).toContain('<ul')
    expect((bullets.match(/<li/g) ?? []).length).toBe(2)

    const numbered = await render('1. первый\n2. второй')
    expect(numbered).toContain('<ol')
    expect((numbered.match(/<li/g) ?? []).length).toBe(2)
  })

  it('renders blockquotes and fenced code', async () => {
    expect(await render('> цитата')).toContain('<blockquote')

    const code = await render('```\nconst x = 1\n```')
    expect(code).toContain('<pre')
    expect(code).toContain('const x = 1')
  })

  it('keeps markdown syntax literal inside a fenced block', async () => {
    const html = await render('```\n# not a heading\n- not a list\n```')
    expect(html).not.toContain('<h3')
    expect(html).not.toContain('<ul')
    expect(html).toContain('# not a heading')
  })

  it('joins consecutive lines into one paragraph and splits on blank lines', async () => {
    const html = await render('строка один\nстрока два\n\nвторой абзац')
    expect((html.match(/<p/g) ?? []).length).toBe(2)
  })

  it('renders empty content without crashing', async () => {
    expect(await render('')).toBe('<div></div>')
  })
})

describe('inline rendering', () => {
  it('renders bold, italic and code spans', async () => {
    const html = await render('**жирный** и *курсив* и `код`')
    expect(html).toContain('<strong>жирный</strong>')
    expect(html).toContain('<em>курсив</em>')
    expect(html).toContain('код</code>')
  })

  it('renders http links with noopener', async () => {
    const html = await render('[док](https://example.com/a)')
    expect(html).toContain('href="https://example.com/a"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('target="_blank"')
  })
})

describe('safety', () => {
  it('renders raw HTML as text, never as markup', async () => {
    const html = await render('<script>alert(1)<\/script> и <img src=x onerror=alert(1)>')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
    // …it shows up escaped instead.
    expect(html).toContain('&lt;script&gt;')
  })

  it('does not linkify a javascript: URL', async () => {
    const html = await render('[клик](javascript:alert(1))')
    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain('<a')
    expect(html).toContain('javascript:alert(1)')
  })

  it('does not linkify a data: URL', async () => {
    const html = await render('[клик](data:text/html,<script>alert(1)<\/script>)')
    expect(html).not.toContain('<a')
    expect(html).not.toContain('<script>')
  })

  it('escapes HTML that appears inside a fenced code block', async () => {
    const html = await render('```\n<script>alert(1)<\/script>\n```')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
})
