<!-- FAQ accordion. Presentational only, content hardcoded — no API/Pinia.
     Single item open at a time; CSS grid-rows drives the expand animation so
     no height measurement is needed (see .faq-panel in assets/landing.css). -->
<script setup lang="ts">
interface FaqItem {
  question: string
  answer: string
}

const items: FaqItem[] = [
  {
    question: 'Что такое автогенерация урока?',
    answer:
      'Вы загружаете PPTX и текст лекции — ИИ анализирует слайды, пишет закадровый текст и озвучивает его нейросетевым синтезом речи. На выходе — готовый MP4-видеоурок, без камеры и монтажа.',
  },
  {
    question: 'Зачем мне это?',
    answer:
      'Подготовка видеолекции вручную — это часы записи и монтажа. Edllm сокращает этот путь до нескольких минут: вы публикуете готовый урок вместо того, чтобы тратить вечер на озвучку и склейку.',
  },
  {
    question: 'Нужно ли самому снимать видео или записывать голос?',
    answer:
      'Нет. Достаточно презентации и текста лекции — озвучку и видеоряд ИИ соберёт сам. Если у вас уже есть готовая запись, её тоже можно загрузить напрямую, без прогона через пайплайн.',
  },
  {
    question: 'Как проверяются знания студентов?',
    answer:
      'К любому уроку можно сгенерировать или собрать вручную квиз с несколькими типами вопросов — от выбора ответа до эссе. Открытые ответы бесплатно проверяет ИИ, с ограничением на число попыток в день.',
  },
  {
    question: 'Что если студенту нужно сдать файл, а не пройти тест?',
    answer:
      'Для этого есть задания: вы формулируете задачу, студент прикладывает файл, вы выставляете оценку — и можете обсудить сдачу со студентом прямо в теме под ней.',
  },
  {
    question: 'Как отслеживать успеваемость группы?',
    answer:
      'В журнале оценок собраны все результаты по курсу, а аналитика по каждому уроку показывает попытки, средний балл и процент прохождения квизов.',
  },
  {
    question: 'Как устроена оплата?',
    answer:
        'Сейчас сервис работает бесплатно. Для дополнительных кредитов свяжитесь с нами во вкладке "Баланс".'
      //'По кредитам, без подписки: кредиты тратятся только на ИИ-операции и не сгорают. Есть бесплатный триал на несколько лекций и тестов — без привязки карты.',
  },
]

const baseId = useId()
const openIndex = ref<number | null>(null)

function toggle(i: number) {
  openIndex.value = openIndex.value === i ? null : i
}
</script>

<template>
  <section class="section-pad" id="faq">
    <div class="wrap">
      <div class="section-head center reveal">
        <span class="eyebrow">Вопросы и ответы</span>
        <h2 class="h2">Частые вопросы</h2>
        <p class="sub">Не нашли ответ? Зарегистрируйтесь и попробуйте — первые уроки и тесты бесплатны.</p>
      </div>

      <div class="faq reveal">
        <div v-for="(item, i) in items" :key="item.question" class="faq-item">
          <h3 class="faq-heading">
            <button
              :id="`${baseId}-btn-${i}`"
              type="button"
              class="faq-q"
              :aria-expanded="openIndex === i"
              :aria-controls="`${baseId}-panel-${i}`"
              @click="toggle(i)"
            >
              <span>{{ item.question }}</span>
              <span class="faq-icon" :class="{ open: openIndex === i }" aria-hidden="true">—</span>
            </button>
          </h3>
          <div
            :id="`${baseId}-panel-${i}`"
            class="faq-panel"
            :class="{ open: openIndex === i }"
            :inert="openIndex !== i"
          >
            <div class="faq-panel-inner">
              <p class="faq-a">{{ item.answer }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
