/**
 * Client-side dry-run grading for the teacher's «view as student» preview.
 * Auto-gradable types are checked against the teacher payload (which contains
 * the correct answers); open types (short_answer / essay) return null — the
 * preview shows the reference answer / rubric instead of calling the LLM.
 */

export type QuizQuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'short_answer'
  | 'essay'
  | 'matching'
  | 'ordering'
  | 'fill_blank'

export type TeacherPayload = Record<string, any>
export type QuizResponse = Record<string, any>

export const isAutoGradable = (type: QuizQuestionType): boolean =>
  type !== 'short_answer' && type !== 'essay'

const sameNumberSet = (a: number[], b: number[]): boolean => {
  if (a.length !== b.length) return false
  const sa = [...a].sort((x, y) => x - y)
  const sb = [...b].sort((x, y) => x - y)
  return sa.every((v, i) => v === sb[i])
}

const samePairSet = (a: [number, number][], b: [number, number][]): boolean => {
  if (a.length !== b.length) return false
  const key = (p: [number, number]) => `${p[0]}:${p[1]}`
  const sa = new Set(a.map(key))
  return b.every((p) => sa.has(key(p)))
}

/**
 * Returns true/false for auto-gradable types, null for open (LLM-graded) ones.
 * Mirrors the server-side grading semantics for each response shape
 * (see QuizTaker's per-type response helpers).
 */
export function gradeAutoResponse(
  type: QuizQuestionType,
  payload: TeacherPayload,
  response: QuizResponse | undefined,
): boolean | null {
  if (!isAutoGradable(type)) return null
  if (!response) return false

  switch (type) {
    case 'single_choice':
      return response.selected_index === payload.correct_index
    case 'multiple_choice':
      return sameNumberSet(response.selected_indices ?? [], payload.correct_indices ?? [])
    case 'true_false':
      return response.selected === payload.correct
    case 'matching':
      return samePairSet(response.pairs ?? [], payload.correct_pairs ?? [])
    case 'ordering': {
      const order: number[] = response.order ?? []
      const correct: number[] = payload.correct_order ?? []
      return order.length === correct.length && order.every((v, i) => v === correct[i])
    }
    case 'fill_blank': {
      const answers: string[] = response.answers ?? []
      const blanks: string[][] = payload.blanks ?? []
      const ci = payload.case_insensitive !== false
      const norm = (s: string) => (ci ? s.trim().toLowerCase() : s.trim())
      return (
        blanks.length > 0 &&
        blanks.every((accepted, i) => {
          const given = norm(answers[i] ?? '')
          return given !== '' && accepted.some((v) => norm(v) === given)
        })
      )
    }
    default:
      return false
  }
}

/** Strip answers from a teacher payload → the shape students see. */
export function toStudentPayload(
  type: QuizQuestionType,
  payload: TeacherPayload,
): Record<string, any> {
  switch (type) {
    case 'single_choice':
    case 'multiple_choice':
      return { type, prompt: payload.prompt, options: payload.options }
    case 'true_false':
    case 'short_answer':
    case 'essay':
      return { type, prompt: payload.prompt }
    case 'matching':
      return { type, prompt: payload.prompt, left: payload.left, right: payload.right }
    case 'ordering':
      return { type, prompt: payload.prompt, items: payload.items }
    case 'fill_blank':
      return {
        type,
        prompt: payload.prompt,
        blanks_count: (payload.blanks ?? []).length,
      }
  }
}
