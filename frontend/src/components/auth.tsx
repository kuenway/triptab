"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, FormEvent, ReactNode, useCallback, useContext, useEffect, useId, useRef, useState } from "react";

import { api, ApiError, AUTH_EXPIRED_EVENT, AuthState, CurrentUser, invitationToken } from "../lib/api";

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
      if (!(cause instanceof ApiError && cause.status === 401)) setError("Could not check your sign-in. Please try again.");
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

export function AuthShell({ children }: { children: ReactNode }) {
  return <main className="shell auth-shell">
    <header className="auth-brand"><Link href="/" className="wordmark">TripTab<span className="brand-dot">.</span></Link><p className="muted">Split expenses with friends.</p></header>
    {children}
  </main>;
}

function AuthStatus() {
  const auth = useAuth();
  return <AuthShell><section className="panel stack-form auth-status">
    {auth.error ? <><p role="alert" className="alert">{auth.error}</p><button onClick={() => void auth.refresh()}>Retry sign-in check</button></> : <p role="status" aria-live="polite">Loading…</p>}
  </section></AuthShell>;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const router = useRouter();
  useEffect(() => { if (!auth.loading && !auth.user && !auth.error) router.replace("/login"); }, [auth.loading, auth.user, auth.error, router]);
  if (auth.error || auth.loading || !auth.user) return <AuthStatus />;
  return children;
}

export function AccountMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const action = useRef<HTMLButtonElement>(null);
  const id = useId();
  const initial = `${user?.display_name ?? ""} ${user?.email ?? ""}`.match(/[\p{L}\p{N}]/u)?.[0].toUpperCase();
  useEffect(() => {
    if (!open) return;
    action.current?.focus();
    const close = () => { setOpen(false); trigger.current?.focus(); };
    const outside = (event: MouseEvent) => { if (!container.current?.contains(event.target as Node)) close(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); close(); } };
    document.addEventListener("click", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("click", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="account-menu" ref={container}>
    <button className="account-trigger" ref={trigger} aria-label="Account menu" title="Account menu" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
      {initial ? <span aria-hidden="true">{initial}</span> : <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></svg>}
    </button>
    {open ? <div id={id} className="account-popover" role="group" aria-label="Your account">
      <p className="muted">Signed in as</p>{user?.display_name ? <p className="account-name">{user.display_name}</p> : null}<p className="account-identity">{user?.email}</p>
      <Link className="account-link" href="/account" onClick={() => setOpen(false)}>Account</Link>
      <button ref={action} disabled={saving} onClick={async () => { setSaving(true); setError(""); try { await logout(); } catch (cause) { setError((cause as Error).message); } finally { setSaving(false); } }}>Sign out</button>
      {error ? <p role="alert" className="alert">{error}</p> : null}
    </div> : null}
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
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  useEffect(() => { void Promise.resolve().then(() => setInviteToken(invitationToken(window.location.hash))); }, []);

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
      const token = invitationToken(window.location.hash);
      if (token) {
        window.history.replaceState(null, "", window.location.pathname);
        router.replace(`/invite#token=${encodeURIComponent(token)}`);
      } else router.push("/");
    } catch (cause) {
      setPassword("");
      setError((cause as Error).message);
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  if (auth.loading || auth.error) return <AuthStatus />;

  return <AuthShell>
    <section className="panel"><h1>{registering ? "Create your account" : "Sign in"}</h1><p className="muted">{registering ? "Start sharing your trip expenses." : "Welcome back to your shared trips."}</p>
      <form className="stack-form" onSubmit={submit}>
        <fieldset disabled={saving || auth.loading} className="stack-form form-fields">
          {registering ? <><label htmlFor="auth-name">Display name</label><input id="auth-name" autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} maxLength={100} required /></> : null}
          <label htmlFor="auth-email">Email</label><input id="auth-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={254} required />
          <label htmlFor="auth-password">Password</label><input id="auth-password" type="password" autoComplete={registering ? "new-password" : "current-password"} minLength={registering ? 12 : 1} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} required />
          {registering ? <p className="muted">Use at least 12 characters. Passphrases are welcome. No special symbols are required.</p> : null}
        </fieldset>
        {error ? <p role="alert" className="alert">{error}</p> : null}
        <button disabled={saving || auth.loading} type="submit">{saving ? "Please wait…" : registering ? "Register" : "Sign in"}</button>
      </form>
      {!registering ? <p><Link href="/forgot-password">Forgot password?</Link></p> : null}
      <p>{registering ? "Already have an account? " : "New to TripTab? "}<Link replace={Boolean(inviteToken)} href={`${registering ? "/login" : "/register"}${inviteToken ? `#token=${encodeURIComponent(inviteToken)}` : ""}`}>{registering ? "Sign in" : "Create an account"}</Link></p>
      {inviteToken ? <p><Link replace href="/invite">Cancel invitation</Link></p> : null}
    </section>
  </AuthShell>;
}
