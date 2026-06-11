<script setup lang="ts">
// The 46 audio-wave bars are rendered into the prerendered HTML (not created in
// JS like the design's app.js) so the markup is SSR-complete; useLandingMotion
// then animates their heights on the client.
const waveBars = 46
</script>

<template>
  <section class="hero">
    <div class="wrap">
      <h1 class="reveal">
        Видеолекции из презентаций<span class="l2 grad-text">за минуты, а не часы</span>
      </h1>
      <p class="lead reveal">
        Загрузите презентацию — ИИ проанализирует слайды, напишет закадровый текст и озвучит его
        <b>нейросетевым синтезом речи</b>. На выходе — готовое MP4 без съёмок и монтажа.
      </p>
      <div class="hero-cta reveal">
        <span class="cta-pulse">
          <NuxtLink class="btn btn-primary" to="/register">Создать аккаунт <span class="arrow">→</span></NuxtLink>
        </span>
        <NuxtLink class="btn btn-ghost" to="/login">
          <svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
          Войти
        </NuxtLink>
      </div>
      <p class="micro reveal">
        Без съёмочной студии и монтажа · 4–8 часов работы превращаются в 2–5 минут
      </p>

      <!-- 3D player stage -->
      <div class="stage reveal">
        <div class="prim" style="width: 120px; height: 120px; left: -90px; top: -40px" data-parallax="0.22"></div>
        <div class="prim" style="width: 80px; height: 80px; right: -70px; bottom: -30px; border-radius: 24px" data-parallax="0.3"></div>

        <div class="player">
          <div class="player-card">
            <div class="win-bar"><i></i><i></i><i></i><span class="url"></span></div>
            <div class="screen">
              <div class="slide-left">
                <div class="kicker">Слайд 04 / 18</div>
                <div class="stitle">Нейросети в образовании</div>
                <div class="bars"><span></span><span></span><span></span></div>
              </div>
              <div class="slide-right">
                <div class="play-btn">
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                </div>
              </div>
              <div class="wave" aria-hidden="true">
                <span v-for="n in waveBars" :key="n"></span>
              </div>
            </div>
          </div>

          <!-- floating chips -->
          <div class="chip c1">
            <span class="ci">
              <svg class="icon" viewBox="0 0 24 24" fill="none">
                <path d="M12 16V4m0 0L7 9m5-5 5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M5 19h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              </svg>
            </span>slides.pptx
          </div>
          <div class="chip c2">
            <span class="ci">
              <svg class="icon" viewBox="0 0 24 24" fill="none">
                <path d="M3 12h3l2-5 4 12 2-7h5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </span>озвучка
          </div>
          <div class="chip c3">
            <span class="ci">
              <svg class="icon" viewBox="0 0 24 24" fill="none">
                <path d="M12 4v12m0 0 5-5m-5 5-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M5 20h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              </svg>
            </span>MP4 · <span class="dim">1080p</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
