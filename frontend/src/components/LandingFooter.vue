<!-- Footer (design_handoff_edllm). Brand + Продукт (in-page anchors) +
     Аккаунт (auth routes) + bottom bar. -->
<template>
  <footer>
    <div class="wrap">
      <div class="foot">
        <div class="brandcol">
          <NuxtLink class="brand" to="/">
            <span class="mark">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path d="M12 3 2 8l10 5 8-4v6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M6 11v4c0 1.2 2.7 3 6 3s6-1.8 6-3v-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </span>
            Edllm
          </NuxtLink>
          <p class="desc">
            Превращаем презентации в озвученные видеолекции автоматически — ИИ-анализ слайдов и нейросетевая озвучка.
          </p>
        </div>
        <div>
          <h5>Продукт</h5>
          <ul>
            <li><a href="#how">Как это работает</a></li>
            <li><a href="#why">Зачем нужно</a></li>
            <li><a href="#pricing">Тарифы</a></li>
          </ul>
        </div>
        <div>
          <h5>Аккаунт</h5>
          <ul>
            <li><NuxtLink to="/register">Создать аккаунт</NuxtLink></li>
            <li><NuxtLink to="/login">Войти</NuxtLink></li>
          </ul>
        </div>
      </div>
      <div class="foot-bottom">
        <span>© {{ year }} Edllm. Все права защищены.</span>
        <span>PPTX → MP4 · нейросетевая озвучка</span>
      </div>
    </div>
  </footer>
</template>

<script setup lang="ts">
const year = new Date().getFullYear()
</script>
