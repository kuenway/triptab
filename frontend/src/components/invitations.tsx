"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { api, ApiError, InvitationPreview, invitationToken, Traveler, TripInvitation } from "../lib/api";
import { useAuth } from "./auth";

export function TravelerInvitations({ tripId, travelers, canManage, onChanged }: { tripId: string; travelers: Traveler[]; canManage: boolean; onChanged?: () => Promise<void> }) {
  const [invitations, setInvitations] = useState<TripInvitation[]>([]);
  const [link, setLink] = useState<{ memberId: string; url: string } | null>(null);
  const [confirmRemoval, setConfirmRemoval] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const pending = useRef(false);
  const label = useId();
  const load = useCallback(async () => { if (canManage) setInvitations(await api.listInvitations(tripId)); }, [tripId, canManage]);
  useEffect(() => { void Promise.resolve().then(load).catch(() => setError("Could not load invitations. Try refreshing the trip.")); }, [load, travelers]);

  async function change(member: Traveler, invitation?: TripInvitation, remove = false) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true); setError(""); setLink(null); setCopied(false);
    try {
      if (remove) { await api.removeTraveler(tripId, member.id); setConfirmRemoval(null); await onChanged?.(); }
      else if (invitation) await api.revokeInvitation(tripId, invitation.id);
      else {
        const created = await api.createInvitation(tripId, member.id);
        setLink({ memberId: member.id, url: `${window.location.origin}/invite#token=${encodeURIComponent(created.token)}` });
      }
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { pending.current = false; setBusy(false); }
  }

  return <div className="traveler-list">
    {travelers.map((member) => {
      const guest = member.role !== "owner" && !member.user_id;
      // The API returns newest first. Detached audit never creates a traveler row.
      const latest = invitations.find((invitation) => invitation.target_member_id === member.id);
      return <div role="group" aria-label={`Invitation for ${member.display_name}`} key={member.id} className="traveler-row">
        <span className="person-dot" aria-hidden="true">{member.display_name.charAt(0).toUpperCase()}</span>
        <div className="traveler-identity"><span className="person-name">{member.display_name}</span> <span className="strategy-pill">{member.role === "owner" ? "Owner" : guest ? "Guest" : "Member"}</span>
          {guest && canManage ? <small className="muted">{latest ? `${latest.status.charAt(0).toUpperCase()}${latest.status.slice(1)} invitation` : "No invitation"}</small> : null}
        </div>
        {guest && canManage ? <div className="traveler-actions"><button disabled={busy} onClick={() => { if (latest?.status !== "pending" || window.confirm("Generate a new invite link?\nThe current invite link will stop working.")) void change(member); }}>{latest?.status === "pending" ? "New link" : "Invite"}</button>{latest?.status === "pending" ? <button disabled={busy} aria-label="Revoke invitation" onClick={() => void change(member, latest)}>Revoke</button> : null}<button type="button" className="remove-traveler" aria-label="Remove traveler" title="Remove traveler" disabled={busy} onClick={() => { setError(""); setConfirmRemoval(member.id); }}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6" /></svg></button></div> : null}
        {confirmRemoval === member.id && guest && canManage ? <div className="traveler-detail"><p>Remove {member.display_name} from this trip? Only an unused Guest can be removed. Any invitation will be revoked.</p><div className="payment-actions"><button disabled={busy} onClick={() => void change(member, undefined, true)}>Confirm removal</button><button disabled={busy} onClick={() => setConfirmRemoval(null)}>Cancel removal</button></div></div> : null}
        {link?.memberId === member.id && guest && canManage ? <div className="stack-form traveler-detail">
          <label htmlFor={label}>Invitation link</label><input id={label} readOnly value={link.url} />
          <p className="muted">Share privately. Creating another invitation replaces this link. Closed links cannot be retrieved.</p>
          <div className="payment-actions"><button onClick={async () => { try { await navigator.clipboard.writeText(link.url); setCopied(true); } catch { setError("Could not copy. Select and copy the invitation link above."); } }}>Copy invite link</button><button onClick={() => setLink(null)}>Close invite link</button></div>
          {copied ? <p role="status">Copied invite link.</p> : null}
        </div> : null}
      </div>;
    })}
    {error ? <p role="alert" className="alert">{error}</p> : null}
  </div>;
}

export function InvitationPage() {
  const auth = useAuth();
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const inspection = useRef(0);
  const invalidateInspection = useCallback(() => { ++inspection.current; }, []);

  const inspect = useCallback(async () => {
    const generation = ++inspection.current;
    const next = invitationToken(window.location.hash);
    setToken(next); setPreview(null); setError(""); setUnavailable(false); setLoading(true);
    try {
      if (!next) { setUnavailable(true); return; }
      const result = await api.previewInvitation(next);
      if (generation === inspection.current) setPreview(result);
    } catch (cause) {
      if (generation !== inspection.current) return;
      if (cause instanceof ApiError && cause.status === 404) setUnavailable(true);
      else setError((cause as Error).message);
    } finally { if (generation === inspection.current) setLoading(false); }
  }, []);
  useEffect(() => {
    void Promise.resolve().then(inspect);
    window.addEventListener("hashchange", inspect);
    return () => { invalidateInspection(); window.removeEventListener("hashchange", inspect); };
  }, [inspect, invalidateInspection]);

  function clear() {
    invalidateInspection();
    setToken(null); setPreview(null);
    window.history.replaceState(null, "", window.location.pathname);
  }
  async function join() {
    if (!token || pending.current) return;
    pending.current = true; setSaving(true); setError("");
    try {
      const member = await api.acceptInvitation(token);
      clear(); router.replace(`/trips/${member.group_id}`);
    } catch (cause) { setError((cause as Error).message); }
    finally { pending.current = false; setSaving(false); }
  }

  return <main className="shell auth-shell">
    <header className="site-header"><Link href="/" className="wordmark">TripTab<span className="brand-dot">.</span></Link></header>
    <section className="panel stack-form">
      {loading ? <p role="status">Checking invitation…</p> : unavailable ? <><h1>Invitation unavailable</h1><p>This invitation is no longer available.</p></> : preview ? <>
        <h1>Join {preview.trip_name}</h1><p>You&apos;ve been invited to join as {preview.member_display_name}.</p>
        <p className="muted">Expires {new Date(preview.expires_at).toLocaleString()}. This links your account to this traveler and their existing trip history.</p>
        {auth.loading ? <p role="status">Checking sign-in…</p> : auth.error ? <><p role="alert">{auth.error}</p><button onClick={() => void auth.refresh()}>Retry sign-in check</button></> : auth.user ? <><p>Signed in as {auth.user.display_name}.</p><button disabled={saving} onClick={() => void join()}>{saving ? "Joining…" : `Join as ${preview.member_display_name}`}</button></> : <div className="payment-actions"><Link replace href={`/login#token=${encodeURIComponent(token!)}`}>Log in to join</Link><Link replace href={`/register#token=${encodeURIComponent(token!)}`}>Create account to join</Link></div>}
      </> : null}
      {error ? <p role="alert" className="alert">{error}</p> : null}
      {!loading && !preview && !unavailable ? <button onClick={() => void inspect()}>Retry invitation check</button> : null}
      <button disabled={saving} onClick={() => { clear(); router.replace("/"); }}>Cancel invitation</button>
    </section>
  </main>;
}
