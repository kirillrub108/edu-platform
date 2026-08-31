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

// ── Images, tables and `material:` resolution (text lessons) ─────────────────

const MATERIAL_ID = 'a1b2c3d4-e5f6-4788-9a0b-c1d2e3f4a5b6'
const OTHER_ID = '0f0e0d0c-0b0a-4908-8706-050403020100'

const materials = {
  [MATERIAL_ID]: {
    id: MATERIAL_ID,
    title: 'Схема алгоритма',
    url: 'http://localhost:8000/files/materials/l1/scheme.png?sig=abc',
    contentType: 'image/png',
  },
  [OTHER_ID]: {
    id: OTHER_ID,
    title: 'Методичка.pdf',
    url: 'http://localhost:8000/files/materials/l1/manual.pdf?sig=def',
    contentType: 'application/pdf',
  },
}

const renderWith = async (
  source: string,
  options: Parameters<typeof markdownNodes>[1] = {},
): Promise<string> => {
  const Comp = defineComponent({ render: () => h('div', markdownNodes(source, options)) })
  return renderToString(createSSRApp(Comp))
}

describe('images', () => {
  it('renders an external https image', async () => {
    const html = await renderWith('![схема](https://example.com/a.png)')
    expect(html).toContain('<img')
    expect(html).toContain('src="https://example.com/a.png"')
    expect(html).toContain('alt="схема"')
    expect(html).toContain('loading="lazy"')
  })

  it('resolves material: to the signed URL from the lesson map', async () => {
    const html = await renderWith(`![схема](material:${MATERIAL_ID})`, { materials })
    expect(html).toContain('src="http://localhost:8000/files/materials/l1/scheme.png?sig=abc"')
    expect(html).toContain('alt="схема"')
  })

  it('never stores a signed URL — only the material ref is in the source', async () => {
    const source = `![схема](material:${MATERIAL_ID})`
    expect(source).not.toContain('sig=')
    // …and without a map the ref stays inert text rather than a request.
    const html = await renderWith(source)
    expect(html).not.toContain('<img')
  })

  it('escapes the alt text instead of letting it become markup', async () => {
    const html = await renderWith('![" onerror="alert(1)](https://example.com/a.png)')
    expect(html).not.toContain('onerror="alert(1)"')
    expect(html).toContain('&quot;')
  })

  it('degrades a non-image material referenced as an image to a download chip', async () => {
    const html = await renderWith(`![методичка](material:${OTHER_ID})`, { materials })
    expect(html).not.toContain('<img')
    expect(html).toContain('href="http://localhost:8000/files/materials/l1/manual.pdf?sig=def"')
  })

  it('cuts a javascript: image target', async () => {
    const html = await renderWith('![x](javascript:alert(1))')
    expect(html).not.toContain('<img')
    expect(html).toContain('javascript:alert(1)')
  })
})

describe('material: references', () => {
  it('renders an attachment as a download chip, not a bare link', async () => {
    const html = await renderWith(`[Методичка](material:${OTHER_ID})`, { materials })
    expect(html).toContain('href="http://localhost:8000/files/materials/l1/manual.pdf?sig=def"')
    expect(html).toContain('download="Методичка.pdf"')
    expect(html).toContain('Методичка')
  })

  it('renders an unknown uuid as plain text — no link, no request', async () => {
    const html = await renderWith(
      '[Пропало](material:99999999-9999-4999-8999-999999999999)',
      { materials },
    )
    expect(html).not.toContain('<a')
    expect(html).toContain('material:99999999-9999-4999-8999-999999999999')
  })

  it("does not resolve another lesson's material when it is absent from the map", async () => {
    const html = await renderWith(`![чужая](material:${MATERIAL_ID})`, { materials: {} })
    expect(html).not.toContain('<img')
    expect(html).not.toContain('<a')
    expect(html).toContain(`material:${MATERIAL_ID}`)
  })

  it('rejects a malformed material ref', async () => {
    const html = await renderWith('[x](material:not-a-uuid)', { materials })
    expect(html).not.toContain('<a')
    expect(html).toContain('material:not-a-uuid')
  })
})

describe('scheme allowlist', () => {
  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    'JAVASCRIPT:alert(1)',
    'data:text/html;base64,PHNjcmlwdD4=',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
  ])('cuts %s', async (href) => {
    const html = await renderWith(`[клик](${href})`)
    expect(html).not.toContain('<a')
    expect(html).not.toContain(`href="${href}"`)
  })

  it('keeps a link whose target contains whitespace or a newline literal', async () => {
    // The inline pattern excludes whitespace in the target, so such a source is
    // never treated as a link in the first place.
    const html = await renderWith('[клик](java\nscript:alert(1))')
    expect(html).not.toContain('<a')
  })

  it('still allows http(s) and mailto', async () => {
    expect(await renderWith('[a](https://example.com)')).toContain('<a')
    expect(await renderWith('[a](http://example.com)')).toContain('<a')
    expect(await renderWith('[a](mailto:teacher@example.com)')).toContain('<a')
  })
})

describe('tables', () => {
  it('renders a pipe table with a header and body', async () => {
    const html = await renderWith('| Тема | Часы |\n| --- | --- |\n| Алгоритмы | 4 |\n| Графы | 2 |')
    expect(html).toContain('<table')
    expect((html.match(/<th[\s>]/g) ?? []).length).toBe(2)
    expect((html.match(/<tr[\s>]/g) ?? []).length).toBe(3)
    expect(html).toContain('Алгоритмы')
    expect(html).toContain('Графы')
  })

  it('renders inline markup inside cells', async () => {
    const html = await renderWith('| A | B |\n| --- | --- |\n| **жирный** | `код` |')
    expect(html).toContain('<strong>жирный</strong>')
    expect(html).toContain('код</code>')
  })

  it('leaves a dash line that follows no table row as ordinary content', async () => {
    const html = await renderWith('просто текст\n---')
    expect(html).not.toContain('<table')
  })
})
