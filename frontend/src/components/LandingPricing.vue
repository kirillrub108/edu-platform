<script setup lang="ts">
// Pricing values come from useLandingPricing (mirrors backend constants) so the
// numbers can't drift from the authenticated tariffs page; the design markup is
// reproduced around them. The 3rd pack (500 кр.) is the highlighted "best" one.
const { packs, operationCosts, videoPricing, creditFacts, trial } = useLandingPricing()
</script>

<template>
  <section class="section-pad" id="pricing">
    <div class="wrap">
      <div class="section-head center reveal">
        <span class="eyebrow">Тарифы</span>
        <h2 class="h2">Оплата по кредитам — без подписок</h2>
        <p class="sub">Покупаете кредиты разово и тратите их только на ИИ-операции. Остаток не сгорает.</p>
      </div>

      <div class="trial reveal">
        <span class="gift">
          <svg class="icon" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="9" width="16" height="11" rx="1.5" stroke="currentColor" stroke-width="2" />
            <path d="M4 13h16M12 9v11M12 9c-2 0-3.5-1-3.5-2.5S9.5 4 12 6c2.5-2 3.5-1 3.5.5S14 9 12 9z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" />
          </svg>
        </span>
        <span>
          <b>Старт бесплатно.</b> Триал на {{ trial.lectures }} лекции и {{ trial.quizzes }} теста — без карты,
          дальше операции оплачиваются кредитами.
        </span>
      </div>

      <div class="packs">
        <div
          v-for="(p, i) in packs"
          :key="p.credits"
          class="pack reveal"
          :class="{ best: i === 2 }"
        >
          <div v-if="i === 2" class="ribbon">Выгодно</div>
          <div class="pk-top"><span class="tag">◆</span> {{ p.credits }} кр.</div>
          <div class="price">{{ p.price }}</div>
          <div class="per">≈ {{ p.perCredit }} за кредит</div>
        </div>
      </div>
      <p class="pay-note reveal">Кредиты покупаются в личном кабинете после регистрации. Оплата картой через ЮKassa.</p>

      <div class="price-grid">
        <div class="pbox reveal">
          <h3>Стоимость операций</h3>
          <p class="pdesc">Сколько кредитов списывается за каждое действие.</p>
          <div class="innerbox">
            <div class="ititle"><span class="d"></span> Видеолекция</div>
            <p>
              Текст-режим: {{ videoPricing.textBase }} кр. + 1 кр. за слайд + 1 кр. за каждые
              {{ videoPricing.charsPerCredit }} знаков озвучки.<br />
              Авто-режим: {{ videoPricing.autoBase }} кр. + 1 кр. за слайд
              (≈ {{ videoPricing.autoCharsPerSlide }} знаков на слайд).<br />
              <template v-for="(ex, i) in videoPricing.examples" :key="ex.slides">
                <span v-if="i"> · </span>{{ ex.slides }} слайдов ≈ {{ ex.lo }}–{{ ex.hi }} кр.
              </template>
            </p>
          </div>
          <div v-for="op in operationCosts" :key="op.label" class="prow">
            <span>{{ op.label }}</span>
            <span v-if="op.free" class="free">бесплатно</span>
            <span v-else class="cr">{{ op.cost }} кр.</span>
          </div>
        </div>

        <div class="pbox reveal">
          <h3>Как работают кредиты</h3>
          <p class="pdesc">Прозрачная модель: платите только за результат.</p>
          <div class="howlist" style="margin-top: 18px">
            <div class="how">
              <span class="hic">
                <svg class="icon" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" />
                  <path d="M9.5 9.5a2.5 2.5 0 1 1 3.2 2.4c-.6.2-.7.5-.7 1.1m0 2.5h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
                </svg>
              </span>
              <div>
                <h4>{{ creditFacts[0].title }}</h4>
                <p>{{ creditFacts[0].body }}</p>
              </div>
            </div>
            <div class="how">
              <span class="hic">
                <svg class="icon" viewBox="0 0 24 24" fill="none">
                  <path d="M4 7a8 8 0 0 1 14-2m2-2v4h-4M20 17a8 8 0 0 1-14 2m-2 2v-4h4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </span>
              <div>
                <h4>{{ creditFacts[1].title }}</h4>
                <p>{{ creditFacts[1].body }}</p>
              </div>
            </div>
            <div class="how">
              <span class="hic">
                <svg class="icon" viewBox="0 0 24 24" fill="none">
                  <path d="M12 21s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.6-7 10-7 10z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" />
                </svg>
              </span>
              <div>
                <h4>{{ creditFacts[2].title }}</h4>
                <p>{{ creditFacts[2].body }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <p class="try-line reveal">
        Готовы попробовать? <NuxtLink to="/register">Создать аккаунт →</NuxtLink>
      </p>
    </div>
  </section>
</template>
