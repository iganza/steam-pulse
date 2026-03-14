"use client";

/**
 * User tier abstraction — ready for real auth without implementing it yet.
 *
 * anonymous: no account, no purchase. Current state for all users.
 * free:      signed in (future), not paid. Reserved for saved games etc.
 * pro:       paid user — active subscription or valid license key.
 */
export type UserTier = "anonymous" | "free" | "pro";

/**
 * Returns the current user's tier.
 * Today: always "anonymous". The license key flow in PremiumUnlock
 * temporarily promotes to "pro" via localStorage, so real auth can
 * slot in here later without touching call sites.
 */
export function useUserTier(): UserTier {
  return "anonymous";
}
