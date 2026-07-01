<!-- Reusable "Написать нам" link to the support Google Form, used in
     LandingNav, AppHeader and LandingFooter. Class/attrs fall through to
     the root <a>, so each caller can style it like its surrounding nav items. -->
<script setup lang="ts">
withDefaults(defineProps<{ label?: string }>(), { label: 'Написать нам' })
</script>

<template>
  <a :href="SUPPORT_FORM_URL" target="_blank" rel="noopener noreferrer">
    <slot>{{ label }}</slot>
  </a>
</template>
