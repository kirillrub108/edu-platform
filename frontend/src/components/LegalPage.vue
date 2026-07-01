<!-- Shared chrome + typography for the /legal/* documents. Each page passes
     its LegalDocumentMeta and slots in semantic content (h2/h3/p/ul/ol);
     styling is applied here so every document looks identical. -->
<script setup lang="ts">
import type { LegalDocumentMeta } from '~/utils/legal'

const props = defineProps<{ doc: LegalDocumentMeta }>()

useHead({ title: `${props.doc.title} — Edllm` })
</script>

<template>
  <article class="mx-auto max-w-3xl py-2">
    <NuxtLink
      to="/"
      class="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-violet-700 transition"
    >
      ← На главную
    </NuxtLink>

    <header class="mt-4 mb-8 border-b border-gray-100 pb-6">
      <h1 class="text-2xl font-semibold text-gray-900 sm:text-3xl">{{ doc.title }}</h1>
      <p class="mt-2 text-sm text-gray-500">
        Редакция от {{ doc.updatedAt }} · версия {{ doc.version }}
      </p>
    </header>

    <div class="legal-prose text-gray-700">
      <slot />
    </div>

    <footer class="mt-10 border-t border-gray-100 pt-6 text-sm text-gray-500">
      По всем вопросам:
      <a
        :href="`mailto:${LEGAL_CONTACTS.supportEmail}`"
        class="font-medium text-violet-700 hover:underline"
      >{{ LEGAL_CONTACTS.supportEmail }}</a>
    </footer>
  </article>
</template>

<style scoped>
.legal-prose :deep(h2) {
  margin-top: 2rem;
  margin-bottom: 0.75rem;
  font-size: 1.125rem;
  font-weight: 600;
  color: #111827;
}
.legal-prose :deep(h3) {
  margin-top: 1.25rem;
  margin-bottom: 0.5rem;
  font-size: 1rem;
  font-weight: 600;
  color: #1f2937;
}
.legal-prose :deep(p) {
  margin-bottom: 0.75rem;
  line-height: 1.7;
}
.legal-prose :deep(ul),
.legal-prose :deep(ol) {
  margin: 0.5rem 0 1rem;
  padding-left: 1.5rem;
  line-height: 1.7;
}
.legal-prose :deep(ul) {
  list-style: disc;
}
.legal-prose :deep(ol) {
  list-style: decimal;
}
.legal-prose :deep(li) {
  margin-bottom: 0.35rem;
}
.legal-prose :deep(a) {
  color: #6d28d9;
  font-weight: 500;
}
.legal-prose :deep(a:hover) {
  text-decoration: underline;
}
.legal-prose :deep(strong) {
  font-weight: 600;
  color: #111827;
}
.legal-prose :deep(dl) {
  margin: 0.5rem 0 1rem;
}
.legal-prose :deep(dt) {
  font-size: 0.8125rem;
  color: #6b7280;
}
.legal-prose :deep(dd) {
  margin: 0 0 0.75rem;
  font-weight: 500;
  color: #111827;
}
</style>
