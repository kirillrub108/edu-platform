<!-- Landing sticky nav (design_handoff_edllm). Distinct from the app's AppHeader:
     the public landing is anonymous, so the only actions are login / register.
     The `.scrolled` state is toggled by useLandingMotion on scroll. -->
<template>
  <header class="nav">
    <div class="wrap">
      <NuxtLink class="brand" to="/">
        <AppLogo />
      </NuxtLink>
      <nav class="nav-right">
        <SupportContactLink class="nav-link contact-link">
          <Bug class="icon" :size="16" />
          Написать нам
        </SupportContactLink>
        <span class="nav-sep contact-link" aria-hidden="true" />
        <SocialLinksMenu class="contact-link" variant="landing" />
        <span class="nav-sep contact-link" aria-hidden="true" />
        <NuxtLink class="nav-link" to="/login">Войти</NuxtLink>
        <span class="nav-sep" aria-hidden="true" />
        <NuxtLink class="btn btn-primary" to="/register">Создать аккаунт</NuxtLink>
      </nav>
    </div>
  </header>
</template>

<script setup lang="ts">
import { Bug } from 'lucide-vue-next'
</script>

<style scoped>
/* Лаконичные разделители между пунктами nav-right — используют тот же
   --line, что и граница шапки при скролле. */
.nav-sep {
  width: 1px;
  height: 16px;
  background: var(--line);
}
</style>
