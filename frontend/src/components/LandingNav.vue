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
        <NuxtLink class="nav-link" to="/login">Войти</NuxtLink>
        <NuxtLink class="btn btn-primary" to="/register">Создать аккаунт</NuxtLink>
      </nav>
    </div>
  </header>
</template>
