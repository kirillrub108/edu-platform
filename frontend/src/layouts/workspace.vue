<template>
  <div>
    <AppHeader />
    <div class="flex">
      <AppSidebar />
      <main class="flex-1 min-w-0 px-6 lg:px-10 py-8">
        <slot />
      </main>
    </div>
  </div>
</template>
