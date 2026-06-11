<!-- Landing sticky nav (design_handoff_edllm). Distinct from the app's AppHeader:
     the public landing is anonymous, so the only actions are login / register.
     The `.scrolled` state is toggled by useLandingMotion on scroll. -->
<template>
  <header class="nav">
    <div class="wrap">
      <NuxtLink class="brand" to="/">
        <span class="mark">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M12 3 2 8l10 5 8-4v6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M6 11v4c0 1.2 2.7 3 6 3s6-1.8 6-3v-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
        Edllm
      </NuxtLink>
      <nav class="nav-right">
        <NuxtLink class="nav-link" to="/login">Войти</NuxtLink>
        <NuxtLink class="btn btn-primary" to="/register">Создать аккаунт</NuxtLink>
      </nav>
    </div>
  </header>
</template>
