"use client";

import { FormEvent, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { api, ApiError, Trip } from "../lib/api";

export function NewTripDialog({ onClose, onCreated, onCheckTrips }: {
  onClose: () => void; onCreated: (trip: Trip) => void; onCheckTrips: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const pending = useRef(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const title = useId(), description = useId(), field = useId(), errorId = useId();
  const close = useCallback(() => { if (!pending.current) onClose(); }, [onClose]);

  useLayoutEffect(() => {
    const dialog = ref.current!;
    const cancel = (event: Event) => { event.preventDefault(); close(); };
    dialog.addEventListener("cancel", cancel);
    return () => dialog.removeEventListener("cancel", cancel);
  }, [close]);
  useEffect(() => {
    const dialog = ref.current!;
    const trigger = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    dialog.showModal();
    dialog.querySelector<HTMLInputElement>("input")?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || uncertain) return;
    if (!name.trim()) return setError("Enter a trip name.");
    pending.current = true; setSaving(true); setError("");
    try {
      onCreated(await api.createTrip(name.trim()));
      // Keep submission locked while navigation into the newly created Trip resolves.
    } catch (cause) {
      const unknown = !(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500;
      setUncertain(unknown);
      setError(unknown ? "Could not confirm whether the trip was created. Check your trips before trying again." : cause.message);
      pending.current = false; setSaving(false);
    }
  }

  return <dialog ref={ref} className="expense-dialog new-trip-dialog" aria-labelledby={title} aria-describedby={description}>
    <header className="expense-dialog-heading"><h2 id={title}>New trip</h2><button type="button" disabled={saving} onClick={close} aria-label="Close new trip dialog" title="Close">×</button></header>
    <form onSubmit={create} className="stack-form new-trip-form">
      <div className="new-trip-fields">
        <p id={description} className="muted">Give your shared trip a name. All amounts are in NT$.</p>
        <label htmlFor={field}>Trip name</label>
        <input id={field} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Japan 2027" required disabled={saving} aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} />
        {error ? <p id={errorId} className="alert" role="alert">{error}</p> : null}
      </div>
      <div className="payment-actions new-trip-actions"><button type="button" disabled={saving} onClick={close}>Cancel</button>{uncertain ? <button type="button" onClick={onCheckTrips}>Check your trips</button> : <button type="submit" disabled={saving}>{saving ? "Creating…" : "Create trip"}</button>}</div>
    </form>
  </dialog>;
}
