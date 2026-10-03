"use client";

import { FormEvent, ReactNode, useId, useRef, useState } from "react";

import { api, ApiError, FinancialAudit } from "../lib/api";

export function localDateTime(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, -1);
}

export function AuditDetails({ record, kind }: { record: FinancialAudit; kind: "expense" | "payment" }) {
  return <div className="audit-details">
    <strong>{record.status === "voided" ? "Voided · excluded from current balances" : "Active"}</strong>
    {record.void_reason ? <p>Reason: {record.void_reason}</p> : null}
    {record.void_created_at ? <p className="muted">Voided {new Date(record.void_created_at).toLocaleString()}</p> : null}
    {record.replaces_id ? <p><a href={`#${kind}-${record.replaces_id}`}>Replaces original {kind}</a></p> : null}
    {record.replaced_by_id ? <p><a href={`#${kind}-${record.replaced_by_id}`}>Replaced by another {kind}</a></p> : null}
  </div>;
}

export function FinancialActions({ tripId, record, kind, onChanged, correction }: {
  tripId: string;
  record: FinancialAudit & { id: string };
  kind: "expense" | "payment";
  onChanged: () => Promise<void>;
  correction: (close: () => void) => ReactNode;
}) {
  const [mode, setMode] = useState<"void" | "correct" | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState("");
  const reasonId = useId();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    if (!reason.trim()) return setError("Enter a reason.");
    pending.current = true;
    setSaving(true);
    setError("");
    try {
      if (kind === "expense") await api.voidExpense(tripId, record.id, reason.trim());
      else await api.voidSettlement(tripId, record.id, reason.trim());
      await onChanged();
      setMode(null);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 0
        ? "Could not confirm whether the record was voided. Refresh history before trying again."
        : (cause as Error).message);
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  if (record.status === "voided") return null;
  return <div className="audit-actions">
    {mode === null ? <div className="payment-actions">
      <button type="button" onClick={() => setMode("correct")}>Correct</button>
      <button type="button" onClick={() => { setError(""); setMode("void"); }}>Void</button>
    </div> : mode === "correct" ? <div className="confirmation-panel" role="group" aria-label={`Correct ${kind}`}>
      <h3>Correct {kind}</h3>{correction(() => setMode(null))}
    </div> : <form className="confirmation-panel stack-form" onSubmit={submit} aria-label={`Void ${kind}`}>
      <h3>Void this {kind}?</h3>
      <p>This keeps the original record in history but removes it from current balances.</p>
      <label htmlFor={reasonId}>Reason</label><input id={reasonId} value={reason} onChange={(event) => setReason(event.target.value)} disabled={saving} required />
      {error ? <p className="alert" role="alert">{error}</p> : null}
      <div className="payment-actions"><button type="button" disabled={saving} onClick={() => setMode(null)}>Cancel</button><button type="submit" disabled={saving}>{saving ? "Voiding…" : `Confirm void ${kind}`}</button></div>
    </form>}
  </div>;
}
