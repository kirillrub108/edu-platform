import { h, type VNode } from 'vue'

/**
 * Safe markdown → VNode renderer for teacher-written content: lesson notes and
 * the body of a text lesson (one renderer for both — there is no second one).
 *
 * Deliberately builds VNodes instead of producing an HTML string for `v-html`:
 * the source is user input, so raw HTML in it must never reach the DOM as
 * markup. Anything the subset below does not recognise (HTML tags included)
 * renders as literal text.
 *
 * Supported: ATX headings, unordered/ordered lists, blockquotes, fenced code,
 * pipe tables, paragraphs; inline **bold**, *italic*, `code`, images and
 * [links](url) restricted to the http(s)/mailto/material: schemes.
 *
 * `material:{uuid}` is resolved ONLY against the materials of the lesson being
 * rendered, passed in by the caller. A uuid that is missing from that map —
 * another lesson's material, or one deleted since the text was written — falls
 * back to literal text: never a broken link, never a network request.
 */

export interface MarkdownMaterial {
  id: string
  title: string
  /** Freshly signed download URL; expires, so the caller may swap it in. */
  url: string
  contentType: string | null
}

export interface MarkdownOptions {
  /** Materials of the current lesson, keyed by lower-case uuid. */
  materials?: Record<string, MarkdownMaterial>
  /** Called when an inline image fails to load (typically an expired signature). */
  onImageError?: (materialId: string) => void
}

const SAFE_HREF = /^(https?:\/\/|mailto:)/i
const MATERIAL_HREF = /^material:([0-9a-f-]{36})$/i
const INLINE =
  /(!\[[^\]\n]*\]\([^)\s]+\)|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\))/

const HEADING_CLASS: Record<number, string> = {
  1: 'text-lg font-semibold text-gray-900 mt-4 first:mt-0',
  2: 'text-base font-semibold text-gray-900 mt-4 first:mt-0',
  3: 'text-sm font-semibold text-gray-900 mt-3 first:mt-0',
}

const BULLETED = /^\s*[-*+]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/
const HEADING = /^(#{1,6})\s+(.*)$/
const QUOTED = /^\s*>\s?/
// A table is a row of cells followed by a dash-only delimiter row.
const TABLE_ROW = /\|/
const TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/

const IMAGE_CONTENT = /^image\//i

function lookupMaterial(
  href: string,
  materials: Record<string, MarkdownMaterial> | undefined,
): MarkdownMaterial | null {
  const ref = MATERIAL_HREF.exec(href)
  if (!ref) return null
  return materials?.[ref[1]!.toLowerCase()] ?? null
}

function attachmentChip(material: MarkdownMaterial, label: string): VNode {
  return h(
    'a',
    {
      href: material.url,
      target: '_blank',
      rel: 'noopener noreferrer',
      download: material.title,
      class:
        'inline-flex items-center gap-1.5 max-w-full align-middle px-2.5 py-1 my-0.5 rounded-lg border border-violet-100 bg-violet-50 text-violet-700 text-[0.95em] no-underline hover:bg-violet-100 transition',
    },
    [h('span', { class: 'shrink-0', 'aria-hidden': 'true' }, '📎'), h('span', { class: 'truncate' }, label)],
  )
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

export function inlineNodes(text: string, options: MarkdownOptions = {}): (VNode | string)[] {
  return text
    .split(INLINE)
    .filter((piece) => piece !== '')
    .map((piece) => {
      // Images first: `![alt](target)` would otherwise partially match a link.
      const image = /^!\[([^\]]*)\]\(([^)\s]+)\)$/.exec(piece)
      if (image) {
        const [, alt, href] = image
        const material = lookupMaterial(href!, options.materials)
        if (material) {
          // A non-image material referenced with image syntax degrades to the
          // download chip rather than a guaranteed-broken <img>.
          if (!IMAGE_CONTENT.test(material.contentType ?? '')) {
            return attachmentChip(material, alt || material.title)
          }
          return h('img', {
            src: material.url,
            alt: alt || material.title,
            loading: 'lazy',
            class: 'block max-w-full h-auto my-3 rounded-xl border border-gray-100',
            onError: () => options.onImageError?.(material.id),
          })
        }
        if (MATERIAL_HREF.test(href!)) return piece // unknown/foreign uuid → literal
        if (!SAFE_HREF.test(href!)) return piece
        return h('img', {
          src: href,
          alt: alt || '',
          loading: 'lazy',
          class: 'block max-w-full h-auto my-3 rounded-xl border border-gray-100',
        })
      }
      if (
        (piece.startsWith('**') && piece.endsWith('**') && piece.length > 4) ||
        (piece.startsWith('__') && piece.endsWith('__') && piece.length > 4)
      ) {
        return h('strong', piece.slice(2, -2))
      }
      if (piece.startsWith('`') && piece.endsWith('`') && piece.length > 2) {
        return h(
          'code',
          { class: 'px-1 py-0.5 rounded bg-gray-100 text-[0.9em] text-violet-700' },
          piece.slice(1, -1),
        )
      }
      if (
        ((piece.startsWith('*') && piece.endsWith('*')) ||
          (piece.startsWith('_') && piece.endsWith('_'))) &&
        piece.length > 2
      ) {
        return h('em', piece.slice(1, -1))
      }
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(piece)
      if (link) {
        const [, label, href] = link
        const material = lookupMaterial(href!, options.materials)
        if (material) return attachmentChip(material, label!)
        // Unknown material, or an unsafe scheme (javascript:, data:, …) →
        // render the source verbatim.
        if (MATERIAL_HREF.test(href!)) return piece
        if (!SAFE_HREF.test(href!)) return piece
        return h(
          'a',
          {
            href,
            target: '_blank',
            rel: 'noopener noreferrer',
            class: 'text-violet-600 underline underline-offset-2 hover:text-violet-700 break-words',
          },
          label,
        )
      }
      return piece
    })
}

export function markdownNodes(source: string, options: MarkdownOptions = {}): VNode[] {
  const lines = (source ?? '').replace(/\r\n/g, '\n').split('\n')
  const out: VNode[] = []
  let i = 0

  const isTableStart = (index: number): boolean =>
    TABLE_ROW.test(lines[index] ?? '') && TABLE_SEP.test(lines[index + 1] ?? '')

  const startsBlock = (index: number): boolean => {
    const line = lines[index]!
    return (
      HEADING.test(line) ||
      QUOTED.test(line) ||
      BULLETED.test(line) ||
      NUMBERED.test(line) ||
      line.trimStart().startsWith('```') ||
      isTableStart(index)
    )
  }

  while (i < lines.length) {
    const line = lines[i]!

    if (!line.trim()) {
      i += 1
      continue
    }

    // Fenced code — everything up to the closing fence stays literal.
    if (line.trimStart().startsWith('```')) {
      const body: string[] = []
      i += 1
      while (i < lines.length && !lines[i]!.trimStart().startsWith('```')) {
        body.push(lines[i]!)
        i += 1
      }
      i += 1 // closing fence (or EOF)
      out.push(
        h(
          'pre',
          {
            class:
              'mt-3 p-3 rounded-xl bg-gray-900 text-gray-100 text-xs overflow-x-auto whitespace-pre',
          },
          h('code', body.join('\n')),
        ),
      )
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      // Cap at h3-equivalent and render as h3..h5 so a note never competes with
      // the page's own h1/h2 in the document outline.
      const level = Math.min(heading[1]!.length, 3)
      out.push(
        h(`h${level + 2}`, { class: HEADING_CLASS[level] }, inlineNodes(heading[2]!.trim(), options)),
      )
      i += 1
      continue
    }

    if (QUOTED.test(line)) {
      const body: string[] = []
      while (i < lines.length && QUOTED.test(lines[i]!)) {
        body.push(lines[i]!.replace(QUOTED, ''))
        i += 1
      }
      out.push(
        h(
          'blockquote',
          { class: 'mt-3 pl-3 border-l-2 border-violet-200 text-gray-600 italic' },
          inlineNodes(body.join(' '), options),
        ),
      )
      continue
    }

    // Pipe table. Escaped pipes are not supported — a `\|` inside a cell splits
    // it, which is acceptable for hand-written teacher content.
    if (isTableStart(i)) {
      const header = splitRow(lines[i]!)
      i += 2 // header + delimiter
      const rows: string[][] = []
      while (i < lines.length && lines[i]!.trim() && TABLE_ROW.test(lines[i]!)) {
        rows.push(splitRow(lines[i]!))
        i += 1
      }
      out.push(
        h('div', { class: 'my-3 overflow-x-auto' }, [
          h('table', { class: 'min-w-full text-sm border-collapse' }, [
            h('thead', [
              h(
                'tr',
                header.map((cell) =>
                  h(
                    'th',
                    {
                      class:
                        'border border-gray-200 bg-gray-50 px-3 py-2 text-left font-semibold text-gray-900',
                    },
                    inlineNodes(cell, options),
                  ),
                ),
              ),
            ]),
            h(
              'tbody',
              rows.map((row) =>
                h(
                  'tr',
                  header.map((_cell, idx) =>
                    h(
                      'td',
                      { class: 'border border-gray-200 px-3 py-2 align-top text-gray-800' },
                      inlineNodes(row[idx] ?? '', options),
                    ),
                  ),
                ),
              ),
            ),
          ]),
        ]),
      )
      continue
    }

    if (BULLETED.test(line) || NUMBERED.test(line)) {
      const ordered = !BULLETED.test(line)
      const marker = ordered ? NUMBERED : BULLETED
      const items: VNode[] = []
      while (i < lines.length && marker.test(lines[i]!)) {
        items.push(h('li', inlineNodes(lines[i]!.replace(marker, ''), options)))
        i += 1
      }
      out.push(
        h(
          ordered ? 'ol' : 'ul',
          { class: `mt-2 pl-5 space-y-1 ${ordered ? 'list-decimal' : 'list-disc'}` },
          items,
        ),
      )
      continue
    }

    // Paragraph: consecutive non-blank lines that start no other block.
    const paragraph: string[] = []
    while (i < lines.length && lines[i]!.trim() && !startsBlock(i)) {
      paragraph.push(lines[i]!)
      i += 1
    }
    out.push(h('p', { class: 'mt-2 first:mt-0' }, inlineNodes(paragraph.join(' '), options)))
  }

  return out
}
