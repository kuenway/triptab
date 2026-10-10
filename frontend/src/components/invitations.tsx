"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { api, ApiError, InvitationPreview, invitationToken, Traveler, TripInvitation } from "../lib/api";
import { useAuth } from "./auth";

export function TravelerInvitations({ tripId, travelers }: { tripId: string; travelers: Traveler[] }) {
  const [invitations, setInvitations] = useState<TripInvitation[]>([]);
  const [link, setLink] = useState<{ memberId: string; url: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const pending = useRef(false);
  const label = useId();
  const load = useCallback(async () => { setInvitations(await api.listInvitations(tripId)); }, [tripId]);
  useEffect(() => { void Promise.resolve().then(load).catch(() => setError("Could not load invitations. Try refreshing the trip.")); }, [load, travelers]);

  async function change(member: Traveler, invitation?: TripInvitation) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true); setError(""); setLink(null); setCopied(false);
    try {
      if (invitation) await api.revokeInvitation(tripId, invitation.id);
      else {
        const created = await api.createInvitation(tripId, member.id);
        setLink({ memberId: member.id, url: `${window.location.origin}/invite#token=${encodeURIComponent(created.token)}` });
      }
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { pending.current = false; setBusy(false); }
  }

  return <div className="stack-form">
    {travelers.filter((member) => member.role !== "owner").map((member) => {
      // The API returns newest first; history remains available to the owner.
      const latest = invitations.find((invitation) => invitation.target_member_id === member.id);
      return <div role="group" aria-label={`Invitation for ${member.display_name}`} key={member.id} className="stack-form">
        <p>{member.display_name}: {latest ? `${latest.status.charAt(0).toUpperCase()}${latest.status.slice(1)} invitation` : "No invitation"}</p>
        {!member.user_id ? <div className="payment-actions"><button disabled={busy} onClick={() => void change(member)}>Invite to TripTab</button>{latest?.status === "pending" ? <button disabled={busy} onClick={() => void change(member, latest)}>Revoke invitation</button> : null}</div> : null}
        {link?.memberId === member.id && !member.user_id ? <div className="stack-form">
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
