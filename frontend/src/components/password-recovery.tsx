"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError, invitationToken } from "../lib/api";
import { passwordRecoveryEnabled } from "../lib/feature-flags";
import { AuthShell } from "./auth";

export function ForgotPassword() {
  return passwordRecoveryEnabled() ? <ForgotPasswordForm /> : <RecoveryUnavailable />;
}

export function ResetPassword() {
  return passwordRecoveryEnabled() ? <ResetPasswordForm /> : <RecoveryUnavailable />;
}

function RecoveryUnavailable() {
  useEffect(() => {
    const clearFragment = () => {
      if (window.location.hash) window.history.replaceState(window.history.state, "", window.location.pathname);
    };
    clearFragment();
    window.addEventListener("hashchange", clearFragment);
    return () => window.removeEventListener("hashchange", clearFragment);
  }, []);
  return <AuthShell><section className="panel recovery-panel">
    <h1>Password recovery unavailable</h1>
    <p role="status">Password recovery is currently unavailable.</p>
    <Link href="/login">Back to Sign in</Link>
  </section></AuthShell>;
}

function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || sent) return;
    pending.current = true; setSending(true); setError("");
    try { await api.forgotPassword(email.trim()); setSent(true); }
    catch (cause) {
      setError(cause instanceof ApiError && cause.status === 429
        ? "Too many requests. Please wait before requesting another link."
        : "Could not confirm the request. Check your email before requesting another link.");
    } finally { pending.current = false; setSending(false); }
  }
  return <AuthShell><section className="panel recovery-panel">
    {sent ? <><h1>Check your email</h1><p role="status">If an account exists for this email, we’ve sent a password reset link.</p><p className="muted">The link expires in 30 minutes. Requesting a new link replaces the previous one.</p></>
      : <><h1>Reset your password</h1><p className="muted">Enter the email you use for TripTab.</p>
        <form className="stack-form" onSubmit={submit}>
          <label htmlFor="recovery-email">Email</label>
          <input id="recovery-email" type="email" autoComplete="email" maxLength={254} required disabled={sending} value={email} onChange={event => setEmail(event.target.value)} aria-describedby={error ? "forgot-error" : undefined} />
          {error ? <p role="alert" id="forgot-error" className="alert">{error}</p> : null}
          <button disabled={sending} type="submit">{sending ? "Sending…" : "Send reset link"}</button>
        </form></>}
    <p><Link href="/login">Back to Sign in</Link></p>
  </section></AuthShell>;
}

function ResetPasswordForm() {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const captured = useRef(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState("");
  const [errorField, setErrorField] = useState("new");
  const pending = useRef(false);
  useEffect(() => {
    function capture() {
      if (pending.current) return;
      // Also handle a second email link opening this already-mounted page.
      const value = invitationToken(window.location.hash);
      window.history.replaceState(window.history.state, "", window.location.pathname);
      void Promise.resolve().then(() => {
        setToken(value); setPassword(""); setConfirm("");
        setSuccess(false); setUncertain(false); setError("");
      });
    }
    if (!captured.current) { captured.current = true; capture(); }
    window.addEventListener("hashchange", capture);
    return () => window.removeEventListener("hashchange", capture);
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || !token || uncertain || success) return;
    setError("");
    if (password !== confirm) { setErrorField("confirm"); setError("New passwords do not match."); return; }
    pending.current = true; setSaving(true);
    try {
      await api.resetPassword(token, password);
      setSuccess(true); setToken(null); setPassword(""); setConfirm("");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 400) {
        setToken(null); setPassword(""); setConfirm("");
      } else if (!(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500) {
        setUncertain(true); setToken(null); setPassword(""); setConfirm("");
      } else {
        setErrorField("new");
        setError(cause.status === 429 ? "Too many requests. Please wait before trying again." : cause.message);
      }
    } finally { pending.current = false; setSaving(false); }
  }
  return <AuthShell><section className="panel recovery-panel">
    {success ? <><h1>Password reset</h1><p role="status">Your password has been changed. Sign in with your new password.</p><Link className="button-link" href="/login">Sign in</Link></>
      : uncertain ? <><h1>Check before trying again</h1><p role="alert">Could not confirm whether your password was reset. Try signing in with your new password before requesting another link.</p><p><Link href="/login">Sign in</Link></p><Link href="/forgot-password">Request a new reset link</Link></>
      : token === undefined ? <p role="status" aria-live="polite">Loading…</p>
      : !token ? <><h1>Reset link unavailable</h1><p>This reset link is invalid or has expired.</p><Link href="/forgot-password">Request a new reset link</Link></>
      : <><h1>Choose a new password</h1><p className="muted">Use at least 12 characters. Passphrases are welcome. Resetting your password signs you out everywhere.</p>
        <form className="stack-form" onSubmit={submit}>
          <fieldset className="stack-form form-fields" disabled={saving}>
            <label htmlFor="reset-new">New password</label>
            <input id="reset-new" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={password} onChange={event => setPassword(event.target.value)} aria-invalid={Boolean(error && errorField === "new")} aria-describedby={error && errorField === "new" ? "reset-error" : undefined} />
            <label htmlFor="reset-confirm">Confirm new password</label>
            <input id="reset-confirm" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={confirm} onChange={event => setConfirm(event.target.value)} aria-invalid={Boolean(error && errorField === "confirm")} aria-describedby={error && errorField === "confirm" ? "reset-error" : undefined} />
          </fieldset>
          {error ? <p role="alert" id="reset-error" className="alert">{error}</p> : null}
          <button disabled={saving} type="submit">{saving ? "Resetting…" : "Reset password"}</button>
        </form><p><Link href="/login">Back to Sign in</Link></p></>}
  </section></AuthShell>;
}
