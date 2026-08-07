<!-- Final CTA (design_handoff_edllm). Sits on its own plain panel — the panel is
     the surface, so .final only handles centering.
     Panel/tone wrapper lives in pages/index.vue (LandingSection). -->
<template>
  <div class="final reveal">
    <h2 class="h2">Превратите презентацию в видеокурс<br />уже сегодня</h2>
    <p class="sub center">
      Загрузите PPTX и получите озвученную видеолекцию — ИИ соберёт её без съёмок и монтажа.
    </p>
    <div class="hero-cta">
      <NuxtLink class="btn btn-primary" to="/register">Создать аккаунт</NuxtLink>
      <NuxtLink class="btn btn-ghost" to="/login">Войти</NuxtLink>
    </div>
  </div>
</template>
