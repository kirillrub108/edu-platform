<!-- Stat banner (design_handoff_edllm). Numbers count up when the banner scrolls
     into view (useLandingMotion reads data-from/data-to/data-suffix on .big).
     Static placeholders describing product capability — no usage claims. -->
<template>
  <section class="section-pad" style="padding-top: 20px">
    <div class="wrap">
      <div class="banner-wrap reveal">
        <div class="banner">
          <div class="blabel">Создано для преподавателей, методистов и онлайн-школ</div>
          <div class="stats">
            <div class="stat">
              <div class="sic">
                <svg class="icon" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="9" stroke="#fff" stroke-width="2" />
                  <path d="M12 7v5l3.5 2" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </div>
              <div class="big" data-from="0" data-to="2" data-suffix="–5 мин">2–5 мин</div>
              <div class="cap">на сборку одной видеолекции</div>
            </div>
            <div class="stat">
              <div class="sic">
                <svg class="icon" viewBox="0 0 24 24" fill="none">
                  <path d="M13 3 4 14h6l-1 7 9-11h-6z" stroke="#fff" stroke-width="2" stroke-linejoin="round" />
                </svg>
              </div>
              <div class="big" data-from="0" data-to="10" data-suffix="×">10×</div>
              <div class="cap">экономия времени против ручной записи</div>
            </div>
            <div class="stat">
              <div class="sic">
                <svg class="icon" viewBox="0 0 24 24" fill="none">
                  <rect x="3" y="5" width="18" height="12" rx="2" stroke="#fff" stroke-width="2" />
                  <path d="M8 21h8" stroke="#fff" stroke-width="2" stroke-linecap="round" />
                </svg>
              </div>
              <div class="big" data-from="0" data-to="1080" data-suffix="p">1080p</div>
              <div class="cap">HD-видео с синхронной озвучкой</div>
            </div>
            <div class="stat">
              <div class="sic">
                <svg class="icon" viewBox="0 0 24 24" fill="none">
                  <path d="M5 4v3m0 13v-3m0 0a5 5 0 0 0 5-5m9-3v3m0 13v-3M14 7a5 5 0 0 1 5 5" stroke="#fff" stroke-width="2" stroke-linecap="round" />
                  <path d="M5 14a3 3 0 0 1 0-6m14 8a3 3 0 0 0 0-6" stroke="#fff" stroke-width="2" stroke-linecap="round" />
                </svg>
              </div>
              <div class="big" style="font-size: clamp(24px, 2.7vw, 34px)">PPTX → MP4</div>
              <div class="cap">полностью автоматический конвейер</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
