<script setup lang="ts">
import { BookOpen, Check, EyeOff, Info, Pencil, UserX } from 'lucide-vue-next'
import { statsHidden } from '~/stores/profile'

// No `auth` middleware on purpose: a public profile must render for a visitor
// who has never signed in. The API decides what they get to see.
const route = useRoute()
const store = useProfileStore()
const { profile, state } = storeToRefs(store)

const userId = computed(() => String(route.params.id))
watch(userId, (id) => store.fetchProfile(id), { immediate: true })

const roleLabel = computed(() => (profile.value?.role === 'teacher' ? 'Автор' : 'Студент'))
const joined = computed(() =>
  profile.value
    ? new Date(profile.value.created_at).toLocaleDateString('ru-RU', {
        month: 'long',
        year: 'numeric',
      })
    : '',
)
const hiddenStats = computed(() => !!profile.value && statsHidden(profile.value))

// Правки идут через /users/me/*, а страница читает /users/{id}/profile — это
// разные ответы, поэтому карточку надо перечитать. Только по выходу из правки,
// а не на каждое сохранение: fetchProfile переводит state в `loading`, и
// страница на миг ушла бы в скелетон, пересоздав саму форму.
const editing = ref(false)
const stopEditing = () => {
  editing.value = false
  store.fetchProfile(userId.value)
}

const visibilityNote = computed(() => {
  if (!profile.value?.is_owner) return null
  switch (profile.value.profile_visibility) {
    case 'public':
      return 'Профиль виден всем, включая незарегистрированных посетителей.'
    case 'authenticated':
      return 'Профиль виден только авторизованным пользователям.'
    case 'private':
      return 'Профиль скрыт. Его видите только вы и преподаватели ваших курсов.'
    default:
      return null
  }
})

const stats = computed(() => {
  const p = profile.value
  if (!p) return []
  if (p.teacher_stats) {
    return [
      { label: 'Курсов', value: String(p.teacher_stats.courses_count) },
      { label: 'Уроков', value: String(p.teacher_stats.lessons_count) },
      { label: 'Студентов', value: String(p.teacher_stats.students_count) },
    ]
  }
  if (p.student_stats) {
    const s = p.student_stats
    return [
      { label: 'Уроков пройдено', value: String(s.completed_lessons) },
      { label: 'Средний балл за тесты', value: s.avg_quiz_score === null ? '—' : `${s.avg_quiz_score}%` },
      {
        label: 'Средний балл за задания',
        value: s.avg_assignment_score === null ? '—' : `${s.avg_assignment_score}%`,
      },
    ]
  }
  return []
})

onMounted(restoreScroll)
</script>

<template>
  <div class="px-4 sm:px-6 py-8 sm:py-10 flex justify-center">
    <div class="w-full max-w-3xl">
      <div v-if="state === 'loading'" class="space-y-4">
        <SkeletonCard />
        <SkeletonCard />
      </div>

      <div
        v-else-if="state === 'not_found'"
        class="rounded-2xl border border-gray-100 bg-white p-10 text-center shadow-soft"
      >
        <UserX class="mx-auto h-10 w-10 text-gray-300" />
        <h1 class="mt-4 text-lg font-semibold text-gray-900">Профиль недоступен</h1>
        <p class="mx-auto mt-2 max-w-sm text-sm text-gray-500">
          Такого профиля нет или его владелец закрыл доступ.
        </p>
        <NuxtLink
          to="/"
          class="mt-5 inline-block rounded-xl bg-violet-700 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-violet-600"
        >
          На главную
        </NuxtLink>
      </div>

      <div
        v-else-if="state === 'error'"
        class="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700"
      >
        Не удалось загрузить профиль. Попробуйте обновить страницу.
      </div>

      <template v-else-if="profile">
        <p
          v-if="profile.is_owner && visibilityNote"
          class="mb-4 flex items-start gap-2 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800"
        >
          <Info class="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Это ваш профиль. {{ visibilityNote }}
            <template v-if="!profile.show_profile_stats">
              Статистику другие не видят — вы видите её всегда.
            </template>
            <NuxtLink to="/account?tab=privacy" class="ml-1 font-medium underline">Настроить</NuxtLink>
          </span>
        </p>

        <div
          v-if="editing"
          class="rounded-2xl border border-violet-200 bg-white p-6 sm:p-8 shadow-soft"
        >
          <div class="mb-6 flex items-center justify-between gap-3">
            <h1 class="text-base font-semibold text-gray-900">Редактирование профиля</h1>
            <UiButton type="button" variant="secondary" size="sm" @click="stopEditing">
              <Check class="mr-1.5 h-4 w-4" />
              Готово
            </UiButton>
          </div>
          <ProfileSettingsForm />
        </div>

        <div v-else class="rounded-2xl border border-gray-100 bg-white p-6 sm:p-8 shadow-soft">
          <div class="flex flex-col items-center gap-4 text-center sm:flex-row sm:text-left">
            <UserAvatar :user="profile" size="lg" />
            <div class="min-w-0 flex-1">
              <h1 class="truncate text-xl font-semibold text-gray-900">
                {{ profile.full_name || 'Без имени' }}
              </h1>
              <p class="mt-1 text-sm text-gray-500">
                {{ roleLabel }} · на платформе с {{ joined }}
              </p>
            </div>
            <UiButton
              v-if="profile.is_owner"
              type="button"
              variant="secondary"
              size="sm"
              class="shrink-0"
              @click="editing = true"
            >
              <Pencil class="mr-1.5 h-4 w-4" />
              Редактировать
            </UiButton>
          </div>

          <p v-if="profile.bio" class="mt-5 whitespace-pre-line text-sm leading-relaxed text-gray-700">
            {{ profile.bio }}
          </p>
        </div>

        <div v-if="stats.length" class="mt-4 grid grid-cols-3 gap-3">
          <div
            v-for="stat in stats"
            :key="stat.label"
            class="rounded-2xl border border-gray-100 bg-white p-4 text-center shadow-soft"
          >
            <div class="text-xl font-semibold text-gray-900">{{ stat.value }}</div>
            <div class="mt-1 text-[11px] leading-tight text-gray-500">{{ stat.label }}</div>
          </div>
        </div>

        <p
          v-else-if="hiddenStats"
          class="mt-4 flex items-center gap-2 rounded-xl border border-gray-100 bg-gray-50 px-4 py-3 text-sm text-gray-500"
        >
          <EyeOff class="h-4 w-4 shrink-0" />
          Пользователь скрыл статистику.
        </p>

        <section class="mt-6">
          <h2 class="mb-3 text-base font-semibold text-gray-900">
            {{ profile.role === 'teacher' ? 'Курсы автора' : 'Курсы' }}
          </h2>

          <p
            v-if="!profile.courses.length"
            class="rounded-2xl border border-gray-100 bg-white px-4 py-8 text-center text-sm text-gray-500 shadow-soft"
          >
            Пока нет курсов.
          </p>

          <ul v-else class="space-y-3">
            <li
              v-for="course in profile.courses"
              :key="course.id"
              class="flex gap-4 rounded-2xl border border-gray-100 bg-white p-4 shadow-soft"
            >
              <img
                v-if="course.cover_image_url"
                :src="course.cover_image_url"
                :alt="course.title"
                loading="lazy"
                class="h-16 w-24 shrink-0 rounded-xl object-cover"
              />
              <div
                v-else
                class="grid h-16 w-24 shrink-0 place-items-center rounded-xl bg-violet-50 text-violet-300"
              >
                <BookOpen class="h-6 w-6" />
              </div>

              <div class="min-w-0 flex-1">
                <h3 class="truncate text-sm font-medium text-gray-900">{{ course.title }}</h3>
                <p v-if="course.description" class="mt-0.5 line-clamp-2 text-xs text-gray-500">
                  {{ course.description }}
                </p>
                <p class="mt-1 text-xs text-gray-400">{{ course.lessons_count }} уроков</p>

                <div v-if="course.progress_percent !== null" class="mt-2">
                  <ProgressBar :value="course.progress_percent" :total="100" />
                  <p class="mt-1 text-[11px] text-gray-500">
                    Пройдено {{ course.progress_percent }}%
                  </p>
                </div>
              </div>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </div>
</template>
