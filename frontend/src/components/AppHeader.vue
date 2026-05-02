<script setup lang="ts">
const { user, isAuthenticated, logout, fetchMe } = useAuth()

onMounted(() => {
  if (!user.value) fetchMe()
})
</script>

<template>
  <header class="bg-white border-b border-gray-200">
    <div class="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
      <NuxtLink to="/" class="font-semibold text-brand">Edu Platform</NuxtLink>
      <nav class="flex items-center gap-4 text-sm">
        <template v-if="isAuthenticated">
          <NuxtLink v-if="user?.role === 'teacher'" to="/dashboard">Dashboard</NuxtLink>
          <NuxtLink v-else to="/student/dashboard">My courses</NuxtLink>
          <span class="text-gray-500">{{ user?.email }}</span>
          <button class="text-gray-700 hover:text-brand" @click="logout">Logout</button>
        </template>
        <template v-else>
          <NuxtLink to="/login">Login</NuxtLink>
          <NuxtLink to="/register" class="text-brand">Register</NuxtLink>
        </template>
      </nav>
    </div>
  </header>
</template>
