"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth as useClerkAuth, useClerk } from "@clerk/nextjs";
import { MOCK_AUTH, MOCK_TOKEN_KEY, authApi, type User } from "./api";
import { PageSkeleton } from "../_ui";

type AuthState = {
  user: User | null;
  loading: boolean;
  reload: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

/**
 * Clerk owns the session. Once Clerk says we are signed in, /api/auth/me
 * returns the PatchLoop user (created on first call), which the rest of the
 * app reads through useAuth() exactly as before.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  return MOCK_AUTH ? <MockAuthProvider>{children}</MockAuthProvider> : <ClerkAuthProvider>{children}</ClerkAuthProvider>;
}

/** Offline mock backend only (NEXT_PUBLIC_MOCK_AUTH=1 at build time): the session is a bearer token in localStorage. Never used with Clerk. */
function MockAuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loaded, setLoaded] = useState(false);
  const reload = useCallback(async () => {
    try {
      const { user } = await authApi.me();
      setUser(user);
    } catch {
      setUser(null);
    } finally {
      setLoaded(true);
    }
  }, []);
  const signOut = useCallback(async () => {
    try {
      window.localStorage.removeItem(MOCK_TOKEN_KEY);
    } catch {
      // storage unavailable
    }
    setUser(null);
    window.location.assign("/");
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial session lookup
    reload();
  }, [reload]);
  const value = useMemo(() => ({ user, loading: !loaded, reload, signOut }), [user, loaded, reload, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function ClerkAuthProvider({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn } = useClerkAuth();
  const clerk = useClerk();
  const [user, setUser] = useState<User | null>(null);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(async () => {
    try {
      const { user } = await authApi.me();
      setUser(user);
    } catch {
      setUser(null);
    } finally {
      setLoaded(true);
    }
  }, []);

  const signOut = useCallback(async () => {
    setUser(null);
    await clerk.signOut({ redirectUrl: "/signin" });
  }, [clerk]);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- sync with Clerk session
      setUser(null);
      setLoaded(true);
      return;
    }
    reload();
  }, [isLoaded, isSignedIn, reload]);

  const loading = !isLoaded || (isSignedIn && !loaded);
  const value = useMemo(() => ({ user, loading: !!loading, reload, signOut }), [user, loading, reload, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Client-side route guard: redirects to /signin when there is no session. */
export function RequireAuth({ children, fallback }: { children: ReactNode; fallback?: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !user) router.replace(`/signin?next=${encodeURIComponent(pathname || "/dashboard")}`);
  }, [loading, user, router, pathname]);

  if (loading || !user) return <>{fallback ?? <PageSkeleton />}</>;
  return <>{children}</>;
}

export { PageSkeleton } from "../_ui";
