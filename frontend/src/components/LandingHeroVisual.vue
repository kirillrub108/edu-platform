<template>
  <ClientOnly>
    <LandingScene />
    <template #fallback>
      <LandingScene />
    </template>
  </ClientOnly>
</template>
