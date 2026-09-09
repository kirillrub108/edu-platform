<script setup lang="ts">
/**
 * Student's course-wide knowledge base. Same component as the teacher's tab —
 * the server prunes draft modules/lessons out of the tree and returns
 * can_edit=false, so read-only here is the server's decision, not a role guess.
 */
definePageMeta({ layout: 'student', middleware: ['auth'] })

const route = useRoute()
const courseId = computed(() => route.params.courseId as string)
</script>

<template>
  <div class="p-6 max-w-4xl mx-auto space-y-6">
    <h1 class="text-2xl font-semibold text-gray-900">База знаний курса</h1>
    <KnowledgeCourseTree :course-id="courseId" />
  </div>
</template>
