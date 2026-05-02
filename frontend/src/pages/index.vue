<script setup lang="ts">
const { isAuthenticated, user, fetchMe } = useAuth()
onMounted(() => {
  if (!user.value) fetchMe()
})
</script>

<template>
  <section class="text-center py-16">
    <h1 class="text-4xl font-bold mb-4">AI-платформа учебного контента</h1>
    <p class="text-gray-600 max-w-xl mx-auto mb-8">
      Загрузите слайды и текст лекции — получите видеокурс с озвучкой и доступом для студентов.
    </p>
    <div class="flex gap-3 justify-center">
      <NuxtLink v-if="!isAuthenticated" to="/register" class="px-5 py-2 bg-brand text-white rounded">
        Начать
      </NuxtLink>
      <NuxtLink
        v-else
        :to="user?.role === 'teacher' ? '/dashboard' : '/student/dashboard'"
        class="px-5 py-2 bg-brand text-white rounded"
      >
        В кабинет
      </NuxtLink>
    </div>
  </section>
</template>
