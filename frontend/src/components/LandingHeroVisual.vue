<script setup lang="ts">
// Decides between the WebGL motif and the static CSS scene. The prerendered
// HTML and every incapable client (reduced-motion, touch / narrow, low-core, or
// no WebGL) get the lightweight CSS scene; capable desktops upgrade to 3D after
// mount. `<ClientOnly>`'s #fallback keeps the CSS scene in the SSG output.

const mode = ref<'fallback' | '3d'>('fallback')

function canRender3d(): boolean {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
  if (window.matchMedia('(pointer: coarse)').matches) return false
  if (window.innerWidth < 768) return false
  if ((navigator.hardwareConcurrency ?? 4) < 4) return false
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}

onMounted(() => {
  if (canRender3d()) mode.value = '3d'
})
</script>

<template>
  <ClientOnly>
    <LandingScene3d v-if="mode === '3d'" @fail="mode = 'fallback'" />
    <LandingScene v-else />
    <template #fallback>
      <LandingScene />
    </template>
  </ClientOnly>
</template>
