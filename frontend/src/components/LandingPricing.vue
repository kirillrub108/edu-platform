<script setup lang="ts">
import { Coins, Film, RefreshCw, PiggyBank, Gift, ArrowRight } from 'lucide-vue-next'

const { packs, operationCosts, videoPricing, creditFacts, trial } = useLandingPricing()
const vReveal = useScrollReveal()

const factIcons = [Coins, RefreshCw, PiggyBank]
</script>

<template>
  <section id="pricing" class="px-6 py-20 max-w-6xl mx-auto scroll-mt-20">
    <div v-reveal class="text-center max-w-2xl mx-auto">
      <span class="text-xs font-semibold uppercase tracking-wider text-violet-600">Тарифы</span>
      <h2 class="mt-2 text-2xl md:text-3xl font-semibold tracking-tight">Оплата по кредитам — без подписок</h2>
      <p class="mt-3 text-gray-600">
        Покупаете кредиты разово и тратите их только на ИИ-операции. Остаток не сгорает.
      </p>
    </div>

    <!-- free trial banner -->
    <div
      v-reveal
      class="mt-10 flex flex-col items-center gap-3 rounded-2xl border border-violet-100 bg-violet-50/60 px-6 py-4 text-center sm:flex-row sm:text-left"
    >
      <div class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-violet-700 shadow-sm ring-1 ring-violet-100">
        <Gift class="h-5 w-5" />
      </div>
      <p class="text-sm text-gray-700">
        <span class="font-semibold text-gray-900">Старт бесплатно.</span>
        Триал на {{ trial.lectures }} лекции и {{ trial.quizzes }} теста — без карты, дальше операции
        оплачиваются кредитами.
      </p>
    </div>

    <!-- credit packs -->
    <div class="mt-5 grid grid-cols-2 lg:grid-cols-4 gap-4">
      <div
        v-for="(p, i) in packs"
        :key="p.credits"
        v-reveal
        :data-reveal-delay="i * 60"
        class="rounded-2xl border border-violet-100 bg-white p-5 shadow-soft transition-all duration-200 hover:-translate-y-1 hover:shadow-soft-hover"
      >
        <div class="inline-flex items-center gap-1.5 text-xl font-semibold tabular-nums text-gray-900">
          <Coins class="h-4 w-4 text-violet-500" />{{ p.credits }} кр.
        </div>
        <div class="mt-1 text-lg font-medium text-gray-900">{{ p.price }}</div>
        <div class="mt-0.5 text-xs text-gray-400">≈ {{ p.perCredit }} за кредит</div>
      </div>
    </div>
    <p class="mt-3 text-center text-xs text-gray-400">
      Кредиты покупаются в личном кабинете после регистрации. Оплата картой через ЮKassa.
    </p>

    <!-- operation costs + credit mechanics -->
    <div class="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-5">
      <div v-reveal class="rounded-2xl border border-violet-100 bg-white p-6 shadow-soft md:p-8">
        <h3 class="font-semibold text-gray-900">Стоимость операций</h3>
        <p class="mt-1 text-xs text-gray-500">Сколько кредитов списывается за каждое действие.</p>

        <div class="mt-4 rounded-xl border border-violet-100 bg-violet-50/50 p-4 text-xs leading-relaxed text-gray-600">
          <div class="inline-flex items-center gap-1.5 font-medium text-gray-800">
            <Film class="h-3.5 w-3.5 text-violet-500" />Видеолекция
          </div>
          <div class="mt-1.5">
            Текст-режим: {{ videoPricing.textBase }} кр. + 1 кр. за слайд + 1 кр. за каждые
            {{ videoPricing.charsPerCredit }} знаков озвучки.
          </div>
          <div>
            Авто-режим: {{ videoPricing.autoBase }} кр. + 1 кр. за слайд
            (≈ {{ videoPricing.autoCharsPerSlide }} знаков на слайд).
          </div>
          <div class="mt-1 text-gray-500">
            <template v-for="(ex, i) in videoPricing.examples" :key="ex.slides">
              <span v-if="i"> · </span>{{ ex.slides }} слайдов ≈ {{ ex.lo }}–{{ ex.hi }} кр.
            </template>
          </div>
        </div>

        <ul class="mt-4 divide-y divide-gray-100">
          <li
            v-for="op in operationCosts"
            :key="op.label"
            class="flex items-center justify-between gap-4 py-3"
          >
            <span class="text-sm text-gray-600">{{ op.label }}</span>
            <span
              class="shrink-0 rounded-lg px-2.5 py-1 text-sm font-semibold tabular-nums"
              :class="op.free ? 'bg-emerald-100 text-emerald-700' : 'bg-violet-50 text-violet-700'"
            >
              {{ op.free ? 'бесплатно' : `${op.cost} кр.` }}
            </span>
          </li>
        </ul>
      </div>

      <div v-reveal :data-reveal-delay="90" class="rounded-2xl border border-violet-100 bg-gradient-to-br from-violet-50 to-white p-6 shadow-soft md:p-8">
        <h3 class="font-semibold text-gray-900">Как работают кредиты</h3>
        <ul class="mt-5 space-y-5">
          <li v-for="(fact, i) in creditFacts" :key="fact.title" class="flex gap-3.5">
            <div class="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white text-violet-700 shadow-sm ring-1 ring-violet-100">
              <component :is="factIcons[i]" class="h-[18px] w-[18px]" />
            </div>
            <div>
              <div class="text-sm font-medium text-gray-900">{{ fact.title }}</div>
              <p class="mt-0.5 text-sm leading-relaxed text-gray-500">{{ fact.body }}</p>
            </div>
          </li>
        </ul>
      </div>
    </div>

    <p class="mt-8 text-center text-sm text-gray-500">
      Готовы попробовать?
      <NuxtLink
        to="/register"
        class="group inline-flex items-center gap-1 rounded font-medium text-violet-700 hover:text-violet-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-600 focus-visible:ring-offset-2"
      >
        Создать аккаунт
        <ArrowRight class="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
      </NuxtLink>
    </p>
  </section>
</template>
