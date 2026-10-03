"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, FormEvent, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { api, ApiError, AUTH_EXPIRED_EVENT, AuthState, CurrentUser } from "../lib/api";

type Authentication = {
  user: CurrentUser | null;
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
  signedIn: (state: AuthState) => void;
  logout: () => Promise<void>;
};
const AuthContext = createContext<Authentication | null>(null);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider is required");
  return context;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const state = await api.getMe();
      setUser(state.user);
    } catch (cause) {
      setUser(null);
      if (!(cause instanceof ApiError && cause.status === 401)) setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(refresh);
    const expired = () => { setUser(null); setError(""); };
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
  }, [refresh]);

  return <AuthContext.Provider value={{ user, loading, error, refresh,
    signedIn: (state) => { setUser(state.user); setLoading(false); setError(""); },
    logout: async () => { await api.logout(); setUser(null); },
  }}>{children}</AuthContext.Provider>;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const router = useRouter();
  useEffect(() => { if (!auth.loading && !auth.user && !auth.error) router.replace("/login"); }, [auth.loading, auth.user, auth.error, router]);
  if (auth.error) return <main className="shell"><p role="alert" className="alert">{auth.error}</p><button onClick={() => void auth.refresh()}>Retry sign-in check</button></main>;
  if (auth.loading || !auth.user) return <main className="shell"><p role="status">{auth.loading ? "Checking sign-in…" : "Redirecting to login…"}</p><Link href="/login">Sign in</Link></main>;
  return children;
}

export function AccountMenu() {
  const { user, logout } = useAuth();
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  return <div className="account-menu">
    <span>{user?.display_name}</span>
    <button disabled={saving} onClick={async () => { setSaving(true); setError(""); try { await logout(); } catch (cause) { setError((cause as Error).message); } finally { setSaving(false); } }}>Log out</button>
    {error ? <p role="alert" className="alert">{error}</p> : null}
  </div>;
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const auth = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const registering = mode === "register";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || auth.loading) return;
    pending.current = true;
    setSaving(true);
    setError("");
    try {
      const state = registering ? await api.register(email.trim(), password, name.trim()) : await api.login(email.trim(), password);
      auth.signedIn(state);
      setPassword("");
      router.push("/");
    } catch (cause) {
      setPassword("");
      setError((cause as Error).message);
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  return <main className="shell auth-shell">
    <header className="site-header"><Link href="/" className="wordmark">TripTab<span className="brand-dot">.</span></Link></header>
    <section className="panel"><h1>{registering ? "Create your account" : "Welcome back"}</h1><p className="muted">Keep your trips and shared expenses together.</p>
      <form className="stack-form" onSubmit={submit}>
        <fieldset disabled={saving || auth.loading} className="stack-form form-fields">
          {registering ? <><label htmlFor="auth-name">Display name</label><input id="auth-name" autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} maxLength={100} required /></> : null}
          <label htmlFor="auth-email">Email</label><input id="auth-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={254} required />
          <label htmlFor="auth-password">Password</label><input id="auth-password" type="password" autoComplete={registering ? "new-password" : "current-password"} minLength={registering ? 12 : 1} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} required />
          {registering ? <p className="muted">Use at least 12 characters.</p> : null}
        </fieldset>
        {error ? <p role="alert" className="alert">{error}</p> : null}
        <button disabled={saving || auth.loading} type="submit">{saving ? "Please wait…" : registering ? "Register" : "Log in"}</button>
      </form>
      <p>{registering ? "Already have an account? " : "New to TripTab? "}<Link href={registering ? "/login" : "/register"}>{registering ? "Log in" : "Create an account"}</Link></p>
    </section>
  </main>;
}
