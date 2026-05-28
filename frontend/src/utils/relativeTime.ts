const rtf = new Intl.RelativeTimeFormat('ru', { numeric: 'auto' })
const dateFmt = new Intl.DateTimeFormat('ru', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

export function relativeTime(iso: string | Date): string {
  const target = typeof iso === 'string' ? new Date(iso) : iso
  const diffSec = Math.round((target.getTime() - Date.now()) / 1000)
  const abs = Math.abs(diffSec)

  if (abs < 60) return rtf.format(diffSec, 'second')
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), 'hour')
  if (abs < 86400 * 7) return rtf.format(Math.round(diffSec / 86400), 'day')

  return dateFmt.format(target)
}
