import { defineStore } from 'pinia'

export type AssignmentStatus = 'draft' | 'published'
export type SubmissionStatus = 'draft' | 'submitted' | 'graded' | 'returned'
export type AttachmentKind = 'submission' | 'feedback'

export interface Attachment {
  id: string
  kind: AttachmentKind
  original_filename: string
  content_type: string | null
  size_bytes: number
  created_at: string
  download_url: string
}

export interface ThreadMessage {
  id: string
  body: string
  author: { id: string; full_name: string | null; role: 'teacher' | 'student' }
  created_at: string
}

export interface StudentSubmission {
  id: string
  assignment_id: string
  text_content: string | null
  status: SubmissionStatus
  submitted_at: string | null
  points_awarded: number | null
  score: number | null
  feedback: string | null
  graded_at: string | null
  attachments: Attachment[]
  messages: ThreadMessage[]
}

export interface TeacherSubmission extends StudentSubmission {
  enrollment_id: string
  student_id: string
  student_name: string | null
  student_email: string
}

export interface SubmissionSummary {
  id: string
  student_id: string
  student_name: string | null
  student_email: string
  status: SubmissionStatus
  submitted_at: string | null
  points_awarded: number | null
  score: number | null
  attachment_count: number
}

export interface AssignmentTeacher {
  id: string
  lesson_id: string
  title: string
  prompt: string
  max_points: number
  due_at: string | null
  status: AssignmentStatus
  attachments_enabled: boolean
  max_files: number
  allowed_ext: string[]
  max_file_mb: number
  pass_threshold: number | null
  created_at: string
  updated_at: string
  submission_count: number
  pending_count: number
}

export interface AssignmentStudent {
  id: string
  lesson_id: string
  title: string
  prompt: string
  max_points: number
  due_at: string | null
  attachments_enabled: boolean
  max_files: number
  allowed_ext: string[]
  max_file_mb: number
  pass_threshold: number | null
  my_submission: StudentSubmission | null
}

export interface AssignmentCreatePayload {
  title: string
  prompt: string
  max_points: number
  due_at?: string | null
  attachments_enabled?: boolean
  max_files?: number
  allowed_ext?: string[] | null
  max_file_mb?: number
  pass_threshold?: number | null
}

interface ListState<T> {
  items: T[]
  loading: boolean
  error: string | null
}

function emptyState<T>(): ListState<T> {
  return { items: [], loading: false, error: null }
}

export function assignmentErrorMessage(err: any, fallback: string): string {
  const status = err?.response?.status
  if (status === 429) return 'Слишком часто, подождите минуту'
  const detail = err?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.code) return ASSIGNMENT_ERROR_CODES[detail.code] ?? detail.code
  return fallback
}

// Machine-readable backend `detail.code` → human Russian message.
export const ASSIGNMENT_ERROR_CODES: Record<string, string> = {
  empty_submission: 'Добавьте текст ответа или прикрепите файл',
  submission_locked: 'Работа уже проверена — нельзя изменить',
  submission_not_submitted: 'Студент ещё не сдал работу',
  points_out_of_range: 'Балл вне допустимого диапазона',
  too_many_files: 'Превышено число файлов',
  file_too_large: 'Файл слишком большой',
  extension_not_allowed: 'Недопустимый тип файла',
  attachments_disabled: 'Вложения отключены для этого задания',
}

export const useAssignmentsStore = defineStore('assignments', () => {
  const { apiFetch } = useApi()

  const teacherByLesson = ref<Record<string, ListState<AssignmentTeacher>>>({})
  const studentByLesson = ref<Record<string, ListState<AssignmentStudent>>>({})

  const teacherState = (lessonId: string): ListState<AssignmentTeacher> => {
    if (!teacherByLesson.value[lessonId]) teacherByLesson.value[lessonId] = emptyState()
    return teacherByLesson.value[lessonId]!
  }
  const studentState = (lessonId: string): ListState<AssignmentStudent> => {
    if (!studentByLesson.value[lessonId]) studentByLesson.value[lessonId] = emptyState()
    return studentByLesson.value[lessonId]!
  }

  // ── Teacher ────────────────────────────────────────────────────────────────

  const fetchTeacher = async (lessonId: string): Promise<void> => {
    const state = teacherState(lessonId)
    state.loading = true
    state.error = null
    try {
      const res = await apiFetch<{ items: AssignmentTeacher[]; total: number }>(
        `/lessons/${lessonId}/assignments`,
      )
      state.items = res.items
    } catch (err: any) {
      state.error = assignmentErrorMessage(err, 'Не удалось загрузить задания')
    } finally {
      state.loading = false
    }
  }

  const create = async (
    lessonId: string,
    payload: AssignmentCreatePayload,
  ): Promise<AssignmentTeacher> => {
    const state = teacherState(lessonId)
    try {
      const created = await apiFetch<AssignmentTeacher>(`/lessons/${lessonId}/assignments`, {
        method: 'POST',
        body: payload,
      })
      state.items = [...state.items, created]
      return created
    } catch (err: any) {
      state.error = assignmentErrorMessage(err, 'Не удалось создать задание')
      throw err
    }
  }

  const update = async (
    lessonId: string,
    assignmentId: string,
    payload: Partial<AssignmentCreatePayload>,
  ): Promise<AssignmentTeacher> => {
    const state = teacherState(lessonId)
    try {
      const updated = await apiFetch<AssignmentTeacher>(`/assignments/${assignmentId}`, {
        method: 'PATCH',
        body: payload,
      })
      const idx = state.items.findIndex((a) => a.id === assignmentId)
      if (idx >= 0) state.items[idx] = updated
      return updated
    } catch (err: any) {
      state.error = assignmentErrorMessage(err, 'Не удалось сохранить')
      throw err
    }
  }

  const setStatus = async (
    lessonId: string,
    assignmentId: string,
    action: 'publish' | 'unpublish',
  ): Promise<AssignmentTeacher> => {
    const state = teacherState(lessonId)
    const updated = await apiFetch<AssignmentTeacher>(
      `/assignments/${assignmentId}/${action}`,
      { method: 'POST' },
    )
    const idx = state.items.findIndex((a) => a.id === assignmentId)
    if (idx >= 0) state.items[idx] = updated
    return updated
  }

  const remove = async (lessonId: string, assignmentId: string): Promise<void> => {
    const state = teacherState(lessonId)
    const prev = state.items
    state.items = state.items.filter((a) => a.id !== assignmentId)
    try {
      await apiFetch(`/assignments/${assignmentId}`, { method: 'DELETE' })
    } catch (err: any) {
      state.items = prev
      state.error = assignmentErrorMessage(err, 'Не удалось удалить')
      throw err
    }
  }

  const fetchSubmissions = async (assignmentId: string): Promise<SubmissionSummary[]> => {
    const res = await apiFetch<{ items: SubmissionSummary[]; total: number }>(
      `/assignments/${assignmentId}/submissions`,
    )
    return res.items
  }

  const fetchSubmission = (submissionId: string): Promise<TeacherSubmission> =>
    apiFetch<TeacherSubmission>(`/submissions/${submissionId}`)

  const grade = (
    submissionId: string,
    payload: { points_awarded: number; feedback: string | null },
  ): Promise<TeacherSubmission> =>
    apiFetch<TeacherSubmission>(`/submissions/${submissionId}/grade`, {
      method: 'POST',
      body: payload,
    })

  const reopen = (submissionId: string): Promise<TeacherSubmission> =>
    apiFetch<TeacherSubmission>(`/submissions/${submissionId}/reopen`, { method: 'POST' })

  const postTeacherMessage = (submissionId: string, body: string): Promise<ThreadMessage> =>
    apiFetch<ThreadMessage>(`/submissions/${submissionId}/messages`, {
      method: 'POST',
      body: { body },
    })

  const uploadFeedbackFile = (submissionId: string, file: File): Promise<Attachment> => {
    const form = new FormData()
    form.append('file', file)
    return apiFetch<Attachment>(`/submissions/${submissionId}/feedback-files`, {
      method: 'POST',
      body: form,
    })
  }

  // ── Student ──────────────────────────────────────────────────────────────────

  const fetchStudent = async (lessonId: string): Promise<void> => {
    const state = studentState(lessonId)
    state.loading = true
    state.error = null
    try {
      const res = await apiFetch<{ items: AssignmentStudent[]; total: number }>(
        `/students/lessons/${lessonId}/assignments`,
      )
      state.items = res.items
    } catch (err: any) {
      state.error = assignmentErrorMessage(err, 'Не удалось загрузить задания')
    } finally {
      state.loading = false
    }
  }

  const getStudentAssignment = (assignmentId: string): Promise<AssignmentStudent> =>
    apiFetch<AssignmentStudent>(`/students/assignments/${assignmentId}`)

  const saveDraft = (
    assignmentId: string,
    text: string | null,
  ): Promise<StudentSubmission> =>
    apiFetch<StudentSubmission>(`/students/assignments/${assignmentId}/submission`, {
      method: 'PUT',
      body: { text_content: text },
    })

  const submitStudent = (
    assignmentId: string,
    text: string | null,
  ): Promise<StudentSubmission> =>
    apiFetch<StudentSubmission>(
      `/students/assignments/${assignmentId}/submission/submit`,
      { method: 'POST', body: { text_content: text } },
    )

  const uploadStudentFile = (assignmentId: string, file: File): Promise<Attachment> => {
    const form = new FormData()
    form.append('file', file)
    return apiFetch<Attachment>(
      `/students/assignments/${assignmentId}/submission/files`,
      { method: 'POST', body: form },
    )
  }

  const deleteStudentFile = (submissionId: string, attachmentId: string): Promise<void> =>
    apiFetch(`/students/submissions/${submissionId}/files/${attachmentId}`, {
      method: 'DELETE',
    })

  const postStudentMessage = (submissionId: string, body: string): Promise<ThreadMessage> =>
    apiFetch<ThreadMessage>(`/students/submissions/${submissionId}/messages`, {
      method: 'POST',
      body: { body },
    })

  return {
    teacherByLesson,
    studentByLesson,
    teacherState,
    studentState,
    // teacher
    fetchTeacher,
    create,
    update,
    setStatus,
    remove,
    fetchSubmissions,
    fetchSubmission,
    grade,
    reopen,
    postTeacherMessage,
    uploadFeedbackFile,
    // student
    fetchStudent,
    getStudentAssignment,
    saveDraft,
    submitStudent,
    uploadStudentFile,
    deleteStudentFile,
    postStudentMessage,
  }
})
