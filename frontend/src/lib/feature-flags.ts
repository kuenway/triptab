// Next.js embeds this public visibility flag at build time; the backend enforces access.
export function passwordRecoveryEnabled(): boolean {
  return process.env.NEXT_PUBLIC_TRIPTAB_PASSWORD_RECOVERY_ENABLED === "true";
}
