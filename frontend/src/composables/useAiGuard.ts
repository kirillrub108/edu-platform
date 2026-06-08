/**
 * Gate for AI actions. `ensureVerified` runs `action` only when the current
 * user's email is verified; otherwise it opens the global verify-email prompt
 * and the action never fires — so no request reaches the (also-gated) backend.
 */
export const useAiGuard = () => {
  const auth = useAuthStore()

  const ensureVerified = async (action: () => unknown): Promise<void> => {
    if (auth.isEmailVerified) {
      await action()
      return
    }
    auth.openVerifyPrompt()
  }

  return { ensureVerified }
}
