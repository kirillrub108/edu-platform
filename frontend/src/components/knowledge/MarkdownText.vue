<script setup lang="ts">
import { h } from 'vue'
import { markdownNodes } from '~/utils/markdown'

// Notes are user input, so their markdown is rendered as VNodes — never through
// v-html. See utils/markdown.ts for the supported subset and the link-scheme
// allowlist.
const props = defineProps<{ content: string }>()

const rendered = computed(() =>
  h(
    'div',
    { class: 'text-sm text-gray-800 leading-relaxed break-words' },
    markdownNodes(props.content),
  ),
)
</script>

<template>
  <component :is="rendered" />
</template>
