<!-- "От PPTX до видеоурока" — the conveyor pipeline (design_handoff_edllm).
     Conveyor line + traveling pulse-dot are CSS; card micro-tilt is wired by
     useLandingMotion. Inline SVGs are the design's exact icons. -->
<template>
  <section class="section-pad" id="how">
    <div class="wrap">
      <div class="section-head center reveal">
        <span class="eyebrow">Как это работает</span>
        <h2 class="h2">От PPTX до видеоурока</h2>
        <p class="sub">Четыре шага от файла презентации до опубликованной видеолекции.</p>
      </div>
      <div class="steps">
        <div class="pulse-dot"></div>

        <div class="step reveal">
          <div class="step-top">
            <span class="ic">
              <svg class="icon" viewBox="0 0 24 24" fill="none">
                <path d="M12 16V4m0 0L7 9m5-5 5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M5 19h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              </svg>
            </span>
            <span class="num">01</span>
          </div>
          <h3>Загрузите PPTX</h3>
          <p>Презентация и текст доклада. Никаких шаблонов и ручных настроек.</p>
        </div>

        <div class="step reveal">
          <div class="step-top">
            <span class="ic">
              <svg class="icon" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="3.2" stroke="currentColor" stroke-width="2" />
                <path d="M12 5V3m0 18v-2M5 12H3m18 0h-2M6.5 6.5 5 5m14 14-1.5-1.5M17.5 6.5 19 5M5 19l1.5-1.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              </svg>
            </span>
            <span class="num">02</span>
          </div>
          <h3>ИИ-анализ слайдов</h3>
          <p>ИИ распознаёт и осмысляет каждый слайд и готовит закадровый текст.</p>
        </div>

        <div class="step reveal">
          <div class="step-top">
            <span class="ic">
              <svg class="icon" viewBox="0 0 24 24" fill="none">
                <path d="M4 9v6h4l5 4V5L8 9H4z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" />
                <path d="M17 8.5a4 4 0 0 1 0 7M19.5 6a7 7 0 0 1 0 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              </svg>
            </span>
            <span class="num">03</span>
          </div>
          <h3>Нейросетевая озвучка</h3>
          <p>Синтез речи проговаривает текст естественным голосом — без диктора.</p>
        </div>

        <div class="step reveal">
          <div class="step-top">
            <span class="ic">
              <svg class="icon" viewBox="0 0 24 24" fill="none">
                <path d="M12 3 2 8l10 5 8-4v6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M6 11v4c0 1.2 2.7 3 6 3s6-1.8 6-3v-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </span>
            <span class="num">04</span>
          </div>
          <h3>Видеоурок студентам</h3>
          <p>Готовое MP4 публикуется студентам — с тестами и автопроверкой.</p>
        </div>
      </div>
    </div>
  </section>
</template>
