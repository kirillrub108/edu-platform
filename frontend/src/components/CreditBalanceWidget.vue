<script setup lang="ts">
import { Coins, Sparkles } from 'lucide-vue-next'

const props = withDefaults(defineProps<{ collapsed?: boolean }>(), { collapsed: false })

const auth = useAuthStore()
const { user } = storeToRefs(auth)
const billing = useBillingStore()
const { available, loadingBalance, balance } = storeToRefs(billing)

const isTeacher = computed(() => user.value?.role === 'teacher')

onMounted(() => {
  if (isTeacher.value && !balance.value) billing.fetchBalance()
})
// AppHeader fetches /auth/me on mount; pick up the role once it resolves.
watch(isTeacher, (val) => {
  if (val && !balance.value) billing.fetchBalance()
})
</script>

<template>
  <template v-if="isTeacher">
    <!-- Collapsed: compact coin chip -->
    <NuxtLink
      v-if="props.collapsed"
      to="/billing"
      title="Баланс кредитов"
      class="w-10 h-10 rounded-xl bg-brand-gradient flex flex-col items-center justify-center text-white hover:opacity-90 transition"
    >
      <Coins class="w-4 h-4" />
      <span class="text-[10px] font-semibold tabular-nums leading-none mt-0.5">{{ available }}</span>
    </NuxtLink>

    <!-- Expanded: balance card -->
    <NuxtLink
      v-else
      to="/billing"
      class="block p-4 rounded-2xl bg-brand-gradient text-white hover:shadow-lg hover:shadow-violet-500/20 transition group"
    >
      <div class="flex items-center">
        <span class="text-xs opacity-80 inline-flex items-center gap-1.5">
          <Coins class="w-3.5 h-3.5" /> Доступно кредитов
        </span>
      </div>
      <div class="mt-1.5 flex items-baseline gap-1.5">
        <span v-if="loadingBalance && balance === null" class="text-2xl font-semibold">—</span>
        <span v-else class="text-3xl font-semibold tabular-nums leading-none">{{ available }}</span>
        <span class="text-xs opacity-70">кредитов</span>
      </div>
      <div
        class="mt-3 inline-flex items-center gap-1 text-xs font-medium bg-white/15 group-hover:bg-white/25 rounded-lg px-2.5 py-1.5 transition"
      >
        <Sparkles class="w-3.5 h-3.5" />
        Пополнить баланс
      </div>
    </NuxtLink>
  </template>
</template>
