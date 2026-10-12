"use client";

import Link from "next/link";
import { FormEvent, useRef, useState } from "react";
import { useAuth } from "./auth";
import { api, ApiError } from "../lib/api";

export function AccountSettings() {
  const { user } = useAuth();
  return <main className="shell account-shell">
    <header className="site-header"><Link href="/" className="wordmark">TripTab<span className="brand-dot">.</span></Link><Link className="back-link" href="/">← All trips</Link></header>
    <div className="account-workspace"><h1>Account</h1>
      <section className="panel" aria-labelledby="profile-heading"><h2 id="profile-heading">Profile</h2><ProfileForm />
        <div className="account-email"><h3>Email</h3><p>{user?.email}</p><p className="muted">Used to sign in.</p></div>
      </section>
      <section className="panel" aria-labelledby="security-heading"><h2 id="security-heading">Security</h2><PasswordForm /></section>
    </div>
  </main>;
}

function ProfileForm() {
  const auth = useAuth();
  const [name, setName] = useState(auth.user?.display_name ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || uncertain) return;
    setSaved(false); setError("");
    if (name.length > 0 && !name.trim()) { setError("Enter a name or leave it empty."); return; }
    pending.current = true; setSaving(true);
    try {
      const state = await api.updateProfile(name.trim() || null);
      auth.signedIn(state); setName(state.user.display_name ?? ""); setSaved(true);
    } catch (cause) {
      const unknown = !(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500;
      setUncertain(unknown);
      setError(unknown ? "Could not confirm whether your name was saved. Check your account before trying again." : (cause as Error).message);
    } finally { pending.current = false; setSaving(false); }
  }
  async function recheck() {
    if (pending.current) return;
    pending.current = true; setSaving(true);
    try { const state = await api.getMe(); auth.signedIn(state); setName(state.user.display_name ?? ""); setUncertain(false); setError(""); }
    catch { setError("Could not check your account. Please try checking again."); }
    finally { pending.current = false; setSaving(false); }
  }
  return <form className="stack-form account-form" onSubmit={submit}>
    <label htmlFor="account-name">Name</label>
    <input id="account-name" autoComplete="name" maxLength={100} value={name} disabled={saving} aria-invalid={Boolean(error && !uncertain)} aria-describedby={`account-name-help${error ? " account-name-error" : ""}`} onChange={event => { setName(event.target.value); setSaved(false); }} />
    <p id="account-name-help" className="muted">Used as your default name when you create a new trip. Existing Tripmate names won’t change. Leave blank to use your email-based default.</p>
    {error ? <p id="account-name-error" role="alert" className="alert">{error}</p> : null}
    {saved ? <p role="status" className="success">Name saved.</p> : null}
    {uncertain ? <button type="button" disabled={saving} onClick={() => void recheck()}>Check account</button> : <button disabled={saving} type="submit">{saving ? "Saving…" : "Save"}</button>}
  </form>;
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [errorField, setErrorField] = useState("new");
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef(false);
  function clear() { setCurrent(""); setNext(""); setConfirm(""); }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || uncertain) return;
    setSaved(false); setError("");
    if (next !== confirm) { setErrorField("confirm"); setError("New passwords do not match."); return; }
    pending.current = true; setSaving(true);
    try { await api.changePassword(current, next); clear(); setSaved(true); }
    catch (cause) {
      const unknown = !(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500;
      setUncertain(unknown);
      setErrorField((cause as Error).message === "Current password is incorrect." ? "current" : "new");
      setError(unknown ? "Could not confirm whether your password changed. It may have changed. Verify which password works by signing in on another browser before trying again." : (cause as Error).message);
    } finally { pending.current = false; setSaving(false); }
  }
  const fields = [
    { id: "current", label: "Current password", value: current, change: setCurrent, complete: "current-password", min: 1 },
    { id: "new", label: "New password", value: next, change: setNext, complete: "new-password", min: 12 },
    { id: "confirm", label: "Confirm new password", value: confirm, change: setConfirm, complete: "new-password", min: 12 },
  ];
  return <form className="stack-form account-form" onSubmit={submit}>
    <h3>Change password</h3>
    <fieldset className="stack-form form-fields" disabled={saving}>
      {fields.map(field => <div className="stack-form" key={field.id}><label htmlFor={`password-${field.id}`}>{field.label}</label>
        <input id={`password-${field.id}`} type="password" autoComplete={field.complete} minLength={field.min} maxLength={128} required value={field.value} onChange={event => field.change(event.target.value)} aria-invalid={Boolean(error && !uncertain && errorField === field.id)} aria-describedby={error && errorField === field.id ? "password-error" : undefined} />
      </div>)}
    </fieldset>
    <p className="muted">Use at least 12 characters. Passphrases are welcome. Other signed-in sessions will be signed out.</p>
    {error ? <p id="password-error" role="alert" className="alert">{error}</p> : null}
    {saved ? <p role="status" className="success">Password changed. Other sessions have been signed out.</p> : null}
    {uncertain ? <button type="button" onClick={() => { clear(); setUncertain(false); setError(""); }}>Clear password fields</button> : <button disabled={saving} type="submit">{saving ? "Changing…" : "Change password"}</button>}
  </form>;
}
