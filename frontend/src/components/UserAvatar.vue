<script setup lang="ts">
import {
  AVATAR_SIZE_CLASSES,
  avatarColorClass,
  avatarInitials,
  displayName,
  profileLink,
  type AvatarSize,
  type AvatarSubject,
} from '~/utils/avatar'

const props = withDefaults(
  defineProps<{
    /** Null renders the deleted-user placeholder rather than nothing. */
    user: AvatarSubject | null
    size?: AvatarSize
    /** Wrap in a link to /u/{id}. Off by default — most call sites are labels. */
    linked?: boolean
  }>(),
  { size: 'md', linked: false },
)

// A provider avatar is loaded straight from lh3.googleusercontent.com /
// avatars.yandex.net (never proxied), so it can 403 or disappear at any time.
// One failed load flips to initials for good.
const failed = ref(false)
watch(() => props.user?.avatar_url, () => { failed.value = false })

const src = computed(() => (failed.value ? null : props.user?.avatar_url || null))
const initials = computed(() => avatarInitials(props.user))
const tint = computed(() => avatarColorClass(props.user?.id))
const label = computed(() => displayName(props.user))
const href = computed(() => (props.linked ? profileLink(props.user) : null))
const sizeClass = computed(() => AVATAR_SIZE_CLASSES[props.size])
</script>

<template>
  <component
    :is="href ? resolveComponent('NuxtLink') : 'span'"
    :to="href || undefined"
    class="inline-block shrink-0 rounded-full overflow-hidden align-middle"
    :class="[sizeClass, href ? 'hover:opacity-80 transition-opacity' : '']"
    :title="label"
  >
    <img
      v-if="src"
      :src="src"
      :alt="label"
      loading="lazy"
      class="w-full h-full object-cover"
      @error="failed = true"
    />
    <span
      v-else
      class="w-full h-full grid place-items-center font-semibold select-none"
      :class="tint"
      aria-hidden="true"
    >{{ initials }}</span>
  </component>
</template>
