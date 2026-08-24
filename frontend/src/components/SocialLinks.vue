<!-- Единый блок ссылок на соцсети. URL живут только в composables/useSocialLinks.ts,
     иконки — инлайновые SVG (иконочных библиотек для брендов в проекте нет).
     Компонент используется и на тёмной accent-панели лендинга, и на светлых
     Tailwind-страницах /legal/*, поэтому все нейтральные цвета выведены из
     currentColor через color-mix — на своём фоне блок не «пропадает». -->
<script setup lang="ts">
// Тип импортируется явно: Nuxt авто-импортирует значения, на type-only экспорты
// полагаться не стоит.
import type { SocialKey } from '~/composables/useSocialLinks'

withDefaults(defineProps<{ variant?: 'compact' | 'cards' | 'menu' }>(), { variant: 'compact' })

const links = SOCIAL_LINKS

const ICON_PATHS: Record<SocialKey, string> = {
  youtube:
    'M23.5 6.2a3 3 0 0 0-2.12-2.14C19.5 3.55 12 3.55 12 3.55s-7.5 0-9.38.51A3 3 0 0 0 .5 6.2C0 8.07 0 12 0 12s0 3.93.5 5.8a3 3 0 0 0 2.12 2.14c1.88.51 9.38.51 9.38.51s7.5 0 9.38-.51A3 3 0 0 0 23.5 17.8C24 15.93 24 12 24 12s0-3.93-.5-5.8ZM9.55 15.57V8.43L15.82 12l-6.27 3.57Z',
  rutube:
    'M4 3h11.2A4.8 4.8 0 0 1 20 7.8a4.8 4.8 0 0 1-3.4 4.6L20 21h-4.3l-3-8H8v8H4V3Zm4 3.6v3.2h6.6a1.6 1.6 0 0 0 0-3.2H8Z',
  vk: 'M12.79 16.24s.28-.03.43-.19c.14-.15.13-.43.13-.43s-.02-1.3.58-1.49c.58-.19 1.34 1.26 2.14 1.81.6.43 1.06.33 1.06.33l2.14-.03s1.12-.07.59-.96c-.04-.07-.31-.66-1.59-1.87-1.34-1.26-1.16-1.06.45-3.25.99-1.33 1.38-2.14 1.26-2.49-.12-.33-.84-.24-.84-.24l-2.41.01s-.18-.02-.31.06c-.13.08-.21.26-.21.26s-.38 1.03-.89 1.91c-1.07 1.85-1.5 1.95-1.67 1.83-.41-.27-.31-1.07-.31-1.65 0-1.79.27-2.54-.52-2.73-.26-.06-.45-.11-1.12-.11-.86 0-1.58 0-1.99.2-.27.14-.48.44-.36.46.16.02.52.1.71.36.25.34.24 1.11.24 1.11s.14 2.11-.33 2.37c-.33.18-.77-.19-1.73-1.87-.49-.86-.86-1.81-.86-1.81s-.07-.18-.2-.27a.87.87 0 0 0-.37-.15l-2.29.01s-.34.01-.47.16c-.11.13-.01.42-.01.42s1.79 4.26 3.82 6.41c1.86 1.96 3.98 1.83 3.98 1.83Z',
  telegram:
    'M12 0a12 12 0 1 0 0 24 12 12 0 0 0 0-24Zm4.9 7.22c.1 0 .32.02.47.14a.5.5 0 0 1 .17.33c.02.09.04.3.02.47-.18 1.9-.96 6.5-1.36 8.62-.17.9-.5 1.2-.82 1.23-.7.07-1.23-.46-1.9-.9-1.06-.69-1.65-1.12-2.68-1.8-1.19-.78-.42-1.21.26-1.91.17-.18 3.24-2.98 3.3-3.23a.24.24 0 0 0-.05-.21c-.07-.06-.18-.04-.25-.02-.11.02-1.8 1.14-5.06 3.34-.48.33-.92.49-1.31.48-.42 0-1.25-.24-1.86-.44-.75-.24-1.35-.37-1.3-.79.03-.21.33-.43.9-.66 3.49-1.52 5.82-2.53 6.99-3.01 3.34-1.39 4.03-1.63 4.48-1.64Z',
  habr: 'M4 4h4v6h8V4h4v16h-4v-6H8v6H4V4Z',
  vc: 'M1 5h3.3l2.6 8.3L9.5 5h3.3L8.6 19H5.2L1 5Zm21.5 3.8a5.4 5.4 0 0 0-3.4-1.2c-2.5 0-4.2 1.9-4.2 4.4s1.7 4.4 4.2 4.4c1.3 0 2.5-.4 3.4-1.2v3.2c-1 .6-2.3.9-3.6.9-4.2 0-7.1-3-7.1-7.3s2.9-7.3 7.1-7.3c1.3 0 2.6.3 3.6.9v3.2Z',
}
</script>

<template>
  <ul class="social-links" :class="variant">
    <li v-for="link in links" :key="link.key">
      <a
        class="social-link"
        :href="link.href"
        :style="{ '--brand': link.brandColor }"
        :aria-label="link.label"
        :title="variant === 'compact' ? link.label : undefined"
        target="_blank"
        rel="noopener noreferrer"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path :d="ICON_PATHS[link.key]" fill="currentColor" fill-rule="evenodd" />
        </svg>
        <span v-if="variant !== 'compact'" class="social-label">{{ link.label }}</span>
      </a>
    </li>
  </ul>
</template>

<style scoped>
/* Все правила ссылок вложены в .social-links намеренно: на /legal/* блок живёт
   внутри `.legal-prose :deep(a)`, которое иначе перекрывает цвет ссылки. */
.social-links {
  list-style: none;
  margin: 0;
  padding: 0;
}
.social-links.compact {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.social-links.cards {
  display: grid;
  /* minmax(0,…) — иначе иконка/подпись распирают колонку и появляется
     горизонтальный скролл на узком мобиле. */
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
@media (min-width: 540px) {
  .social-links.cards {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (min-width: 900px) {
  .social-links.cards {
    grid-template-columns: repeat(6, minmax(0, 1fr));
  }
}

.social-links .social-link {
  display: flex;
  align-items: center;
  justify-content: center;
  color: inherit;
  text-decoration: none;
  background: color-mix(in srgb, currentColor 9%, transparent);
  border: 1px solid color-mix(in srgb, currentColor 20%, transparent);
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease,
    color 0.18s ease,
    transform 0.18s ease;
}
.social-links .social-link:hover {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
  text-decoration: none;
}
.social-links .social-link:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}
.social-links .social-link svg {
  display: block;
  flex: none;
}

.social-links.compact .social-link {
  width: 40px;
  height: 40px;
  border-radius: 999px;
}
.social-links.compact .social-link svg {
  width: 20px;
  height: 20px;
}

.social-links.cards .social-link {
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 18px 8px;
  border-radius: 16px;
}
.social-links.cards .social-link:hover {
  transform: translateY(-2px);
}
.social-links.cards .social-link svg {
  width: 26px;
  height: 26px;
}
/* Вертикальный список для выпадающего меню в шапке. Заливка на hover — лёгкий
   тон бренда, а не сплошной цвет: в белом дропдауне сплошная заливка выглядит
   тяжело, и на светлых брендах (Habr, Rutube) белый текст на ней нечитаем. */
.social-links.menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.social-links.menu .social-link {
  justify-content: flex-start;
  gap: 12px;
  padding: 9px 10px;
  border-radius: 10px;
  background: transparent;
  border-color: transparent;
}
.social-links.menu .social-link:hover {
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  border-color: transparent;
  color: inherit;
}
/* Цветом бренда красится только иконка — подпись остаётся тёмной,
   иначе на светлых брендах контраст падает ниже AA. */
.social-links.menu .social-link:hover svg {
  color: var(--brand);
}
.social-links.menu .social-link svg {
  width: 20px;
  height: 20px;
}

.social-links .social-label {
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
  .social-links .social-link {
    transition: none;
  }
  .social-links.cards .social-link:hover {
    transform: none;
  }
}
</style>
