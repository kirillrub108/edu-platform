export type SocialKey = 'youtube' | 'rutube' | 'vk' | 'telegram' | 'instagram' | 'max' | 'tiktok'

export interface SocialLink {
  key: SocialKey
  label: string
  href: string
  /** Фирменный цвет сети — используется только как hover-заливка в SocialLinks.vue. */
  brandColor: string
}

export const SOCIAL_LINKS: SocialLink[] = [
  {
    key: 'youtube',
    label: 'YouTube',
    href: 'https://www.youtube.com/@edllm_lms',
    brandColor: '#ff0000',
  },
  {
    key: 'rutube',
    label: 'Rutube',
    href: 'https://rutube.ru/channel/29785280/',
    brandColor: '#00a8ff',
  },
  {
    key: 'vk',
    label: 'VK',
    href: 'https://vk.ru/edllm',
    brandColor: '#0077ff',
  },
  {
    key: 'telegram',
    label: 'Telegram',
    href: 'https://t.me/edllm_lms',
    brandColor: '#2aabee',
  },
  {
    key: 'instagram',
    label: 'Instagram',
    href: 'https://www.instagram.com/edllm.support/',
    brandColor: '#e1306c',
  },
  {
    key: 'max',
    label: 'Max',
    href: 'https://max.ru/channel_edllm',
    brandColor: '#7747ff',
  },
  {
    key: 'tiktok',
    label: 'TikTok',
    href: 'https://www.tiktok.com/@edllm_lms',
    brandColor: '#fe2c55',
  },
]
