import { h, type VNode } from 'vue'

/**
 * Safe markdown → VNode renderer for teacher-written lesson notes.
 *
 * Deliberately builds VNodes instead of producing an HTML string for `v-html`:
 * the source is user input, so raw HTML in it must never reach the DOM as
 * markup. Anything the subset below does not recognise (HTML tags included)
 * renders as literal text.
 *
 * Supported: ATX headings, unordered/ordered lists, blockquotes, fenced code,
 * paragraphs; inline **bold**, *italic*, `code`, and [links](url) restricted to
 * the http(s)/mailto schemes.
 */

const SAFE_HREF = /^(https?:\/\/|mailto:)/i
const INLINE =
  /(\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\))/

const HEADING_CLASS: Record<number, string> = {
  1: 'text-lg font-semibold text-gray-900 mt-4 first:mt-0',
  2: 'text-base font-semibold text-gray-900 mt-4 first:mt-0',
  3: 'text-sm font-semibold text-gray-900 mt-3 first:mt-0',
}

const BULLETED = /^\s*[-*+]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/
const HEADING = /^(#{1,6})\s+(.*)$/
const QUOTED = /^\s*>\s?/

export function inlineNodes(text: string): (VNode | string)[] {
  return text
    .split(INLINE)
    .filter((piece) => piece !== '')
    .map((piece) => {
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
        // Unsafe scheme (javascript:, data:, …) → render the source verbatim.
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

export function markdownNodes(source: string): VNode[] {
  const lines = (source ?? '').replace(/\r\n/g, '\n').split('\n')
  const out: VNode[] = []
  let i = 0

  const startsBlock = (line: string): boolean =>
    HEADING.test(line) ||
    QUOTED.test(line) ||
    BULLETED.test(line) ||
    NUMBERED.test(line) ||
    line.trimStart().startsWith('```')

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
      out.push(h(`h${level + 2}`, { class: HEADING_CLASS[level] }, inlineNodes(heading[2]!.trim())))
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
          inlineNodes(body.join(' ')),
        ),
      )
      continue
    }

    if (BULLETED.test(line) || NUMBERED.test(line)) {
      const ordered = !BULLETED.test(line)
      const marker = ordered ? NUMBERED : BULLETED
      const items: VNode[] = []
      while (i < lines.length && marker.test(lines[i]!)) {
        items.push(h('li', inlineNodes(lines[i]!.replace(marker, ''))))
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
    while (i < lines.length && lines[i]!.trim() && !startsBlock(lines[i]!)) {
      paragraph.push(lines[i]!)
      i += 1
    }
    out.push(h('p', { class: 'mt-2 first:mt-0' }, inlineNodes(paragraph.join(' '))))
  }

  return out
}
