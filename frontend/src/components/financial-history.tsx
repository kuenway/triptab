"use client";

import { FormEvent, ReactNode, useId, useRef, useState } from "react";

import { api, ApiError, FinancialAudit } from "../lib/api";

export function localDateTime(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, -1);
}

export function FinancialHistory<T extends FinancialAudit>({ records, kind, children, historyOnly = false }: {
  records: T[];
  kind: "expense" | "payment";
  children: (record: T) => ReactNode;
  historyOnly?: boolean;
}) {
  const current = records.filter((record) => record.status === "active");
  const history = records.filter((record) => record.status === "voided");
  return <>
    {!historyOnly && <div className="expense-list" role="group" aria-label={`Current ${kind}s`}>
      {current.length ? current.map(children) : <p className="muted">{records.length ? `No current ${kind}s. Previous records are in history.` : kind === "expense" ? "No expenses yet. Add one to start the tab." : "No payments recorded yet."}</p>}
    </div>}
    {history.length ? <details className="financial-history">
      <summary>Show {kind} history ({history.length})</summary>
      <p className="muted">Previous versions and removed {kind}s. These records are excluded from current balances.</p>
      <div className="expense-list">{history.map(children)}</div>
    </details> : null}
  </>;
}

function HistoryLink({ target, children }: { target: string; children: ReactNode }) {
  return <a href={`#${target}`} onClick={() => {
    const history = document.getElementById(target)?.closest("details");
    if (history) history.open = true;
  }}>{children}</a>;
}

export function AuditDetails({ record, kind, amounts }: {
  record: FinancialAudit & { created_at: string };
  kind: "expense" | "payment";
  amounts: Record<string, string>;
}) {
  if (record.status === "active") return record.replaces_id ? <p className="audit-details muted"><HistoryLink target={`${kind}-${record.replaces_id}`}>View edit history</HistoryLink></p> : null;
  return <div className="audit-details">
    <strong>Voided</strong>
    {record.void_reason?.trim() ? <p>{record.replaced_by_id ? "Reason" : "Note"}: {record.void_reason}</p> : null}
    <p className="muted">Recorded <time dateTime={record.created_at}>{new Date(record.created_at).toLocaleString()}</time></p>
    {record.void_created_at ? <p className="muted">Voided <time dateTime={record.void_created_at}>{new Date(record.void_created_at).toLocaleString()}</time></p> : null}
    {record.replaces_id ? <p><HistoryLink target={`${kind}-${record.replaces_id}`}>Replaces an earlier {kind}{amounts[record.replaces_id] ? ` · ${amounts[record.replaces_id]}` : ""}</HistoryLink></p> : null}
    {record.replaced_by_id ? <p><HistoryLink target={`${kind}-${record.replaced_by_id}`}>Replaced by another {kind}{amounts[record.replaced_by_id] ? ` · ${amounts[record.replaced_by_id]}` : ""}</HistoryLink></p> : null}
  </div>;
}

export function FinancialActions({ tripId, record, kind, onChanged, correction, onEdit }: {
  tripId: string;
  record: FinancialAudit & { id: string };
  kind: "expense" | "payment";
  onChanged: () => Promise<void>;
  correction: (close: () => void) => ReactNode;
  onEdit?: () => void;
}) {
  const [mode, setMode] = useState<"void" | "edit" | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState("");
  const reasonId = useId();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setSaving(true);
    setError("");
    try {
      if (kind === "expense") await api.voidExpense(tripId, record.id, reason.trim() || null);
      else await api.voidSettlement(tripId, record.id, reason.trim() || null);
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
      <button type="button" onClick={() => onEdit ? onEdit() : setMode("edit")}>Edit</button>
      <button type="button" className="delete-record" aria-label={`Delete ${kind}`} title={`Delete ${kind}`} onClick={() => { setError(""); setMode("void"); }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6" /></svg>
      </button>
    </div> : mode === "edit" ? <div className="confirmation-panel" role="group" aria-label={`Edit ${kind}`}>
      <h3>Edit {kind}</h3>{correction(() => setMode(null))}
    </div> : <form className="confirmation-panel stack-form" onSubmit={submit} aria-label={`Delete ${kind}`}>
      <h3>Delete this {kind}?</h3>
      <p>This keeps the original record in history but removes it from current balances.</p>
      <label htmlFor={reasonId}>Note (optional)</label><input id={reasonId} value={reason} onChange={(event) => setReason(event.target.value)} disabled={saving} placeholder="Add a note for your records (optional)" />
      {error ? <p className="alert" role="alert">{error}</p> : null}
      <div className="payment-actions"><button type="button" disabled={saving} onClick={() => setMode(null)}>Cancel</button><button type="submit" disabled={saving}>{saving ? "Deleting…" : `Confirm delete ${kind}`}</button></div>
    </form>}
  </div>;
}
