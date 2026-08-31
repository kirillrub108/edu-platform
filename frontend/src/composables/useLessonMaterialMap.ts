import type { MarkdownMaterial } from '~/utils/markdown'

/**
 * The `material:{uuid}` resolution map for a lesson's markdown.
 *
 * Any page rendering lesson markdown must call this — the map is an EXPLICIT
 * requirement of that page, never something inherited from KnowledgePanel
 * happening to be mounted nearby. Both consumers share the same store cache, so
 * this is still one request per lesson; removing the panel from a page can no
 * longer make images silently stop resolving.
 */
export const useLessonMaterialMap = (lessonId: Ref<string> | ComputedRef<string>) => {
  const store = useLessonKnowledgeStore()
  const state = computed(() => store.getState(lessonId.value))

  const materials = computed<Record<string, MarkdownMaterial>>(() =>
    Object.fromEntries(
      state.value.materials.map((m) => [
        m.id.toLowerCase(),
        {
          id: m.id,
          title: m.title || m.original_filename,
          url: m.download_url,
          contentType: m.content_type,
        },
      ]),
    ),
  )

  // Body rendering waits on this: markdown must not paint before the map exists,
  // or every inline image flashes unresolved on first frame.
  const ready = computed(() => state.value.loaded)

  const onImageError = (materialId: string) => {
    const url = materials.value[materialId.toLowerCase()]?.url
    if (url) store.refreshExpiredUrls(lessonId.value, url)
  }

  watch(lessonId, (id) => store.ensureLoaded(id), { immediate: true })

  return { materials, ready, onImageError }
}
