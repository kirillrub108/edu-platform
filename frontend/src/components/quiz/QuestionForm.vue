<script setup lang="ts">
/**
 * Teacher-facing form for the polymorphic question payload. Emits `update`
 * with the full payload on every edit; parent debounces and PATCHes.
 *
 * Adding a new question type: add a branch in defaultPayload() and a
 * template block matching `type === 'new_type'`.
 */
import type { QuestionType } from '~/composables/useQuizAuthoring'

const props = defineProps<{
  type: QuestionType
  payload: Record<string, any>
}>()

const emit = defineEmits<{
  update: [payload: Record<string, any>]
}>()

const local = reactive<Record<string, any>>({ ...props.payload })

// Sync external changes (e.g. regenerate) into local without losing reactivity.
watch(
  () => props.payload,
  (next) => {
    for (const k of Object.keys(local)) delete local[k]
    Object.assign(local, next)
  },
  { deep: true },
)

const flush = () => emit('update', JSON.parse(JSON.stringify(local)))

// ── helpers per type ──────────────────────────────────────────────────────

const addOption = () => {
  local.options = [...(local.options ?? []), '']
  flush()
}
const removeOption = (idx: number) => {
  local.options = (local.options ?? []).filter((_: any, i: number) => i !== idx)
  if (props.type === 'single_choice' && local.correct_index >= local.options.length) {
    local.correct_index = Math.max(0, local.options.length - 1)
  }
  if (props.type === 'multiple_choice') {
    local.correct_indices = (local.correct_indices ?? []).filter((i: number) => i < local.options.length)
  }
  flush()
}

const toggleMcIndex = (idx: number) => {
  const set = new Set<number>(local.correct_indices ?? [])
  if (set.has(idx)) set.delete(idx)
  else set.add(idx)
  local.correct_indices = Array.from(set).sort((a, b) => a - b)
  flush()
}

const addBlank = () => {
  local.blanks = [...(local.blanks ?? []), ['']]
  flush()
}
const removeBlank = (idx: number) => {
  local.blanks = (local.blanks ?? []).filter((_: any, i: number) => i !== idx)
  flush()
}
const addAlternative = (blankIdx: number) => {
  local.blanks[blankIdx] = [...local.blanks[blankIdx], '']
  flush()
}
const removeAlternative = (blankIdx: number, altIdx: number) => {
  local.blanks[blankIdx] = local.blanks[blankIdx].filter((_: any, i: number) => i !== altIdx)
  flush()
}

const addMatchingPair = () => {
  local.left = [...(local.left ?? []), '']
  local.right = [...(local.right ?? []), '']
  local.correct_pairs = [...(local.correct_pairs ?? []), [local.left.length - 1, local.right.length - 1]]
  flush()
}
const removeMatchingPair = (idx: number) => {
  local.left = local.left.filter((_: any, i: number) => i !== idx)
  local.right = local.right.filter((_: any, i: number) => i !== idx)
  local.correct_pairs = (local.correct_pairs ?? [])
    .filter(([li]: [number, number]) => li !== idx)
    .map(([li, ri]: [number, number]) => [li > idx ? li - 1 : li, ri > idx ? ri - 1 : ri])
  flush()
}

const moveOrderingItem = (idx: number, dir: -1 | 1) => {
  const target = idx + dir
  if (target < 0 || target >= local.items.length) return
  const items = [...local.items]
  const tmp = items[idx]; items[idx] = items[target]; items[target] = tmp
  local.items = items
  // Reset correct_order to identity (teacher will set the right order by reordering).
  local.correct_order = items.map((_: any, i: number) => i)
  flush()
}
const addOrderingItem = () => {
  local.items = [...(local.items ?? []), '']
  local.correct_order = (local.items ?? []).map((_: any, i: number) => i)
  flush()
}
const removeOrderingItem = (idx: number) => {
  local.items = local.items.filter((_: any, i: number) => i !== idx)
  local.correct_order = local.items.map((_: any, i: number) => i)
  flush()
}
</script>

<template>
  <div class="space-y-3">
    <label class="block">
      <span class="text-xs text-gray-500">Формулировка</span>
      <textarea
        v-model="local.prompt"
        rows="2"
        class="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
        @input="flush"
      />
    </label>

    <!-- single_choice -->
    <template v-if="type === 'single_choice'">
      <div class="space-y-1">
        <div
          v-for="(opt, i) in local.options ?? []"
          :key="i"
          class="flex items-center gap-2"
        >
          <input
            type="radio"
            :checked="local.correct_index === i"
            @change="() => { local.correct_index = i; flush() }"
          />
          <input
            v-model="local.options[i]"
            class="flex-1 rounded-lg border border-gray-200 px-2 py-1 text-sm"
            placeholder="Вариант"
            @input="flush"
          />
          <button type="button" class="text-xs text-red-500" @click="removeOption(i)">✕</button>
        </div>
        <button type="button" class="text-xs text-violet-600" @click="addOption">+ вариант</button>
      </div>
    </template>

    <!-- multiple_choice -->
    <template v-if="type === 'multiple_choice'">
      <div class="space-y-1">
        <div
          v-for="(opt, i) in local.options ?? []"
          :key="i"
          class="flex items-center gap-2"
        >
          <input
            type="checkbox"
            :checked="(local.correct_indices ?? []).includes(i)"
            @change="() => toggleMcIndex(i)"
          />
          <input
            v-model="local.options[i]"
            class="flex-1 rounded-lg border border-gray-200 px-2 py-1 text-sm"
            placeholder="Вариант"
            @input="flush"
          />
          <button type="button" class="text-xs text-red-500" @click="removeOption(i)">✕</button>
        </div>
        <button type="button" class="text-xs text-violet-600" @click="addOption">+ вариант</button>
      </div>
    </template>

    <!-- true_false -->
    <template v-if="type === 'true_false'">
      <div class="flex gap-3 text-sm">
        <label class="flex items-center gap-1">
          <input
            type="radio"
            :checked="local.correct === true"
            @change="() => { local.correct = true; flush() }"
          /> Верно
        </label>
        <label class="flex items-center gap-1">
          <input
            type="radio"
            :checked="local.correct === false"
            @change="() => { local.correct = false; flush() }"
          /> Неверно
        </label>
      </div>
    </template>

    <!-- short_answer -->
    <template v-if="type === 'short_answer'">
      <label class="block">
        <span class="text-xs text-gray-500">Эталонный ответ</span>
        <input
          v-model="local.reference_answer"
          class="mt-1 w-full rounded-lg border border-gray-200 px-2 py-1 text-sm"
          @input="flush"
        />
      </label>
      <label class="block">
        <span class="text-xs text-gray-500">Критерии (необязательно)</span>
        <input
          v-model="local.rubric"
          class="mt-1 w-full rounded-lg border border-gray-200 px-2 py-1 text-sm"
          @input="flush"
        />
      </label>
    </template>

    <!-- essay -->
    <template v-if="type === 'essay'">
      <label class="block">
        <span class="text-xs text-gray-500">Критерии оценки</span>
        <textarea
          v-model="local.rubric"
          rows="2"
          class="mt-1 w-full rounded-lg border border-gray-200 px-2 py-1 text-sm"
          @input="flush"
        />
      </label>
    </template>

    <!-- matching -->
    <template v-if="type === 'matching'">
      <div class="space-y-1">
        <div
          v-for="(_l, i) in local.left ?? []"
          :key="i"
          class="flex items-center gap-2"
        >
          <input
            v-model="local.left[i]"
            class="flex-1 rounded-lg border border-gray-200 px-2 py-1 text-sm"
            placeholder="Слева"
            @input="flush"
          />
          <span class="text-gray-400">→</span>
          <input
            v-model="local.right[i]"
            class="flex-1 rounded-lg border border-gray-200 px-2 py-1 text-sm"
            placeholder="Справа (правильная пара)"
            @input="flush"
          />
          <button type="button" class="text-xs text-red-500" @click="removeMatchingPair(i)">✕</button>
        </div>
        <button type="button" class="text-xs text-violet-600" @click="addMatchingPair">+ пара</button>
        <p class="text-xs text-gray-400">Студент увидит обе колонки в перемешанном порядке.</p>
      </div>
    </template>

    <!-- ordering -->
    <template v-if="type === 'ordering'">
      <div class="space-y-1">
        <div
          v-for="(_it, i) in local.items ?? []"
          :key="i"
          class="flex items-center gap-2"
        >
          <span class="text-xs text-gray-400 w-4">{{ i + 1 }}.</span>
          <input
            v-model="local.items[i]"
            class="flex-1 rounded-lg border border-gray-200 px-2 py-1 text-sm"
            placeholder="Шаг"
            @input="flush"
          />
          <button type="button" class="text-xs" :disabled="i === 0" @click="moveOrderingItem(i, -1)">↑</button>
          <button
            type="button"
            class="text-xs"
            :disabled="i === local.items.length - 1"
            @click="moveOrderingItem(i, 1)"
          >↓</button>
          <button type="button" class="text-xs text-red-500" @click="removeOrderingItem(i)">✕</button>
        </div>
        <button type="button" class="text-xs text-violet-600" @click="addOrderingItem">+ шаг</button>
        <p class="text-xs text-gray-400">Порядок выше = правильный.</p>
      </div>
    </template>

    <!-- fill_blank -->
    <template v-if="type === 'fill_blank'">
      <p class="text-xs text-gray-400">В формулировке используйте маркер <code>___</code> для каждого пропуска.</p>
      <div
        v-for="(alts, bi) in local.blanks ?? []"
        :key="bi"
        class="rounded-lg bg-gray-50 p-2 space-y-1"
      >
        <div class="flex items-center justify-between">
          <span class="text-xs text-gray-500">Пропуск {{ bi + 1 }} (принимаемые варианты)</span>
          <button type="button" class="text-xs text-red-500" @click="removeBlank(bi)">удалить пропуск</button>
        </div>
        <div
          v-for="(_alt, ai) in alts"
          :key="ai"
          class="flex items-center gap-2"
        >
          <input
            v-model="local.blanks[bi][ai]"
            class="flex-1 rounded-lg border border-gray-200 px-2 py-1 text-sm"
            placeholder="Вариант ответа"
            @input="flush"
          />
          <button type="button" class="text-xs text-red-500" @click="removeAlternative(bi, ai)">✕</button>
        </div>
        <button type="button" class="text-xs text-violet-600" @click="addAlternative(bi)">+ вариант</button>
      </div>
      <button type="button" class="text-xs text-violet-600" @click="addBlank">+ пропуск</button>
      <label class="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          :checked="local.case_insensitive ?? true"
          @change="(e: any) => { local.case_insensitive = e.target.checked; flush() }"
        /> Игнорировать регистр
      </label>
    </template>
  </div>
</template>
