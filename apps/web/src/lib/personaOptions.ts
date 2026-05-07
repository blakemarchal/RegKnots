// Shared persona / role options — single source of truth as of D6.81.
//
// Background: prior to this sprint, the app had TWO different "role"
// concepts presented as nearly-identical dropdowns:
//   1. Maritime job title  (Captain / Mate / Engineer ...)  — Account + Register
//   2. Persona / context   (Mariner / Teacher / Cadet ...)  — Account only
// The second wasn't reachable at registration, so a new teacher had to
// pick "Other" at signup and only later discover the proper label
// hidden in account settings. The two dropdowns also confused users —
// both were labeled "Role" and lived two sections apart on Account.
//
// Resolution (Karynn UX feedback): drop the maritime job title from the
// user-level scope. It's already captured per-vessel via vessel.crew_role
// (which is the right scope — you're Captain of THIS ship, Mate on THAT
// one over your career). The persona/context is what genuinely belongs
// at the user level, and it's the field that grows with the product
// (study tools add `student` and `teacher_instructor` is already here).
//
// The chat prompt builder reads `users.persona`; the maritime job title
// continues to live on vessels and reaches prompts via the vessel
// profile context (no behavior change for the chat side).

export interface PersonaOption {
  /** Stable identifier persisted to users.persona (snake_case). */
  value: string
  /** Display label shown in dropdowns. */
  label: string
  /** One-line hint shown under the option in registration / account
   *  to help new users pick the right bucket. */
  hint?: string
}

export const PERSONA_OPTIONS: readonly PersonaOption[] = [
  {
    value: 'mariner_shipboard',
    label: 'Mariner / shipboard',
    hint: 'Working mariner — captain, mate, engineer, AB, oiler, etc. Your job title sits on each vessel profile.',
  },
  {
    value: 'cadet_student',
    label: 'Cadet / student',
    hint: 'Pre-license. Studying for an MMC or upgrade. Unlocks Study Tools by default.',
  },
  {
    value: 'teacher_instructor',
    label: 'Teacher / instructor',
    hint: 'Maritime educator or training-program instructor. Unlocks Study Tools by default.',
  },
  {
    value: 'shore_side_compliance',
    label: 'Shore-side compliance',
    hint: 'Marine superintendent, port captain, designated person ashore (DPA), QA/QC.',
  },
  {
    value: 'legal_consultant',
    label: 'Maritime attorney / consultant',
    hint: 'Maritime law, P&I claims, regulatory consulting.',
  },
  {
    value: 'other',
    label: 'Other',
    hint: 'Surveyor, inspector, vendor, or anything else.',
  },
] as const

/** Convenience map for converting a persisted value back to its label. */
export const PERSONA_LABELS: Record<string, string> = Object.fromEntries(
  PERSONA_OPTIONS.map((p) => [p.value, p.label]),
)

/** Personas that should automatically toggle on the Study Tools feature
 *  flag at registration. Account-level toggle still lets any user opt
 *  in/out regardless of the persona they registered with. */
export const STUDY_TOOLS_DEFAULT_PERSONAS: readonly string[] = [
  'cadet_student',
  'teacher_instructor',
] as const
