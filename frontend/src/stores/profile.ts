import { defineStore } from 'pinia'
import type { ProfileVisibility } from '~/stores/auth'

export interface ProfileCourse {
  id: string
  title: string
  description: string | null
  cover_image_url: string | null
  lessons_count: number
  /** Student profiles only. */
  progress_percent: number | null
}

export interface TeacherStats {
  courses_count: number
  lessons_count: number
  students_count: number
}

export interface StudentStats {
  completed_lessons: number
  avg_quiz_score: number | null
  avg_assignment_score: number | null
}

export interface PublicProfile {
  id: string
  full_name: string | null
  bio: string | null
  role: 'teacher' | 'student'
  created_at: string
  avatar_url: string | null
  courses: ProfileCourse[]
  /** Null when the owner turned stats off — identity and courses still render. */
  teacher_stats: TeacherStats | null
  student_stats: StudentStats | null
  is_owner: boolean
  profile_visibility: ProfileVisibility | null
  show_profile_stats: boolean | null
}

/**
 * The three states /u/{id} can be in. A hidden profile is indistinguishable
 * from a missing one by design — the API answers 404 for both, so the UI has
 * nothing to tell apart and must not pretend otherwise.
 */
export type ProfileState = 'loading' | 'ready' | 'not_found' | 'error'

export const resolveProfileState = (
  status: number | null | undefined,
): Exclude<ProfileState, 'loading' | 'ready'> => (status === 404 ? 'not_found' : 'error')

/** True when the viewer is looking at a profile whose owner hid the numbers. */
export const statsHidden = (profile: PublicProfile): boolean =>
  profile.teacher_stats === null && profile.student_stats === null

export const useProfileStore = defineStore('profile', () => {
  const { apiFetch } = useApi()

  const profile = ref<PublicProfile | null>(null)
  const state = ref<ProfileState>('loading')

  const fetchProfile = async (userId: string) => {
    state.value = 'loading'
    profile.value = null
    try {
      profile.value = await apiFetch<PublicProfile>(`/users/${userId}/profile`)
      state.value = 'ready'
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status
      state.value = resolveProfileState(status)
    }
  }

  return { profile, state, fetchProfile }
})
