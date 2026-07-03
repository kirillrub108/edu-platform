<script setup lang="ts">
definePageMeta({ layout: 'student', middleware: ['auth'] })

const route = useRoute()
const courseId = computed(() => route.params.courseId as string)
const lessonId = computed(() => route.params.lessonId as string)
</script>

<template>
  <StudentLessonView :course-id="courseId" :lesson-id="lessonId" />
</template>
