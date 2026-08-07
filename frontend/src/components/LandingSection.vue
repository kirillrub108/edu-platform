<!-- Full-bleed rounded panel — the single composition primitive of the landing.
     `tone` picks the flat fill; `.panel-accent` in assets/landing.css inverts the
     whole typography/element scale inside it. Section order and tone map live in
     pages/index.vue, not here. -->
<script setup lang="ts">
withDefaults(
  defineProps<{ tone?: 'accent' | 'plain'; tag?: string }>(),
  { tone: 'plain', tag: 'section' },
)
</script>

<template>
  <component :is="tag" class="panel" :class="`panel-${tone}`">
    <div class="wrap">
      <slot />
    </div>
  </component>
</template>
