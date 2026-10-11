/**
 * What the signed-in user may see (AUTH_BLUEPRINT § 11). These only HIDE UI: the API is the
 * decision, and answers 403 whatever the screen shows.
 *
 * Affordance parity: gate each control on EXACTLY the code its endpoint enforces (the *_CODES maps
 * beside each API module, e.g. ROLE_CODES in ./rbac), never on a broad flag such as is_staff. A
 * button the API will refuse is a bug; so is a hidden button the API would have allowed.
 *
 * Client-only in practice: the session is an httpOnly cookie, so Me exists only in the browser
 * (NEXTJS_STANDARDS.md § 3). The pure functions are safe anywhere; the hook needs a client
 * component.
 */
import { useEffect, useState } from "react";

import { fetchMe, type Me } from "./auth";

export function isSuperuser(me: Me | null | undefined): boolean {
  return me?.is_superuser === true;
}

/** A superuser's `permissions` already lists the whole catalog; the flag also covers new codes. */
export function can(me: Me | null | undefined, code: string): boolean {
  if (!me) return false;
  return isSuperuser(me) || me.permissions.includes(code);
}

export function canAny(me: Me | null | undefined, codes: readonly string[]): boolean {
  return codes.some((code) => can(me, code));
}

export type Permissions = {
  /** The user, or null when signed out. Undefined while loading. */
  me: Me | null | undefined;
  loading: boolean;
  /** The server could not be reached; nothing is known about the user. */
  failed: boolean;
  can: (code: string) => boolean;
  canAny: (codes: readonly string[]) => boolean;
};

/** Loads /me once per mount. */
export function usePermissions(): Permissions {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchMe()
      .then((value) => {
        if (active) setMe(value);
      })
      .catch(() => {
        if (active) {
          setMe(null);
          setFailed(true);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  return {
    me,
    loading: me === undefined,
    failed,
    can: (code) => can(me, code),
    canAny: (codes) => canAny(me, codes),
  };
}
