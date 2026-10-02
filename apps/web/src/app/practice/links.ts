// 2026-10-02 — sign-up links from /practice. src=practice is the first-touch
// attribution code (lib/attribution.ts → users.signup_source 'src:practice');
// /admin counts these signups under Growth. utm_content says which button.
export function signupHref(placement: string): string {
  return `/register?src=practice&utm_content=${placement}`
}
