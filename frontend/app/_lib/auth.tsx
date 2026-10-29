"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { authApi, type User } from "./api";
import { PageSkeleton } from "../_ui";

type AuthState = {
  user: User | null;
  loading: boolean;
  reload: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const reload = useCallback(async () => {
    try {
      const { user } = await authApi.me();
      setUser(user);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Cookies are cleared server-side; ignore network errors here.
    }
    setUser(null);
    router.push("/signin");
  }, [router]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial session check
    reload();
  }, [reload]);

  const value = useMemo(() => ({ user, loading, reload, signOut }), [user, loading, reload, signOut]);
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
