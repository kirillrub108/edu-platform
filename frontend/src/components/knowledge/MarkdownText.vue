<script setup lang="ts">
import { h } from 'vue'
import { markdownNodes, type MarkdownMaterial } from '~/utils/markdown'

// Notes and text-lesson bodies are user input, so their markdown is rendered as
// VNodes — never through v-html. See utils/markdown.ts for the supported subset
// and the link-scheme allowlist.
//
// `materials` is optional: notes render without one and their `material:` refs
// (if any) stay literal text. A page rendering a text lesson body passes the map
// from useLessonMaterialMap.
const props = defineProps<{
  content: string
  materials?: Record<string, MarkdownMaterial>
  onImageError?: (materialId: string) => void
}>()

const rendered = computed(() =>
  h(
    'div',
    { class: 'text-sm text-gray-800 leading-relaxed break-words' },
    markdownNodes(props.content, {
      materials: props.materials,
      onImageError: props.onImageError,
    }),
  ),
)
</script>

<template>
  <component :is="rendered" />
</template>
