"use client";

import { FormEvent, useId, useRef, useState } from "react";

import { api, ApiError, Settlement, SettlementSuggestions, Traveler } from "../lib/api";

import { AuditDetails, FinancialActions, FinancialHistory, localDateTime } from "./financial-history";

import { useAuth } from "./auth";
import { SettlementConfirmation } from "./settlement-confirmation";

type Suggestion = SettlementSuggestions["suggestions"][number];
const money = (amount: number) => `NT$${new Intl.NumberFormat("en-US").format(amount)}`;

function currentLocalDateTime() {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
}

export function PaymentForm({ tripId, travelers, onRecorded, onCancel, initialPayment }: {
  tripId: string;
  travelers: Traveler[];
  initialPayment?: Settlement;
  onRecorded: () => Promise<void>;
  onCancel?: () => void;
}) {
  const [fromId, setFromId] = useState(initialPayment?.from_member_id ?? "");
  const [toId, setToId] = useState(initialPayment?.to_member_id ?? "");
  const [amount, setAmount] = useState(initialPayment ? String(initialPayment.amount) : "");
  const [occurredAt, setOccurredAt] = useState(() => initialPayment ? localDateTime(initialPayment.occurred_at) : currentLocalDateTime());
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const prefix = useId();
  const dateId = `${prefix}-payment-date`;
  const [reason, setReason] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    setError("");
    setSaved(false);
    if (initialPayment && !reason.trim()) return setError("Enter a reason.");
    const numericAmount = Number(amount);
    if (!fromId || !toId) return setError("Choose the sender and recipient.");
    if (fromId === toId) return setError("Sender and recipient must be different travelers.");
    if (!Number.isSafeInteger(numericAmount) || numericAmount <= 0) return setError("Enter a positive whole NTD amount.");
    if (!occurredAt || Number.isNaN(new Date(occurredAt).getTime())) return setError("Choose when the payment happened.");

    pending.current = true;
    setSaving(true);
    try {
      const input = {
        from_member_id: fromId,
        to_member_id: toId,
        amount: numericAmount,
        occurred_at: initialPayment && occurredAt === localDateTime(initialPayment.occurred_at)
          ? initialPayment.occurred_at : new Date(occurredAt).toISOString(),
      };
      if (initialPayment) await api.correctSettlement(tripId, initialPayment.id, reason.trim(), input);
      else await api.recordSettlement(tripId, input);
      setSaved(true);
      setFromId("");
      setToId("");
      setAmount("");
      setOccurredAt(currentLocalDateTime());
      await onRecorded();
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 0
        ? "Could not confirm whether the payment was recorded. Refresh payment history before trying again."
        : (cause as Error).message);
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  if (travelers.length < 2) return <p className="muted">Add at least two travelers to record a payment.</p>;

  return (
    <form onSubmit={submit} className="stack-form">
      {initialPayment ? <><p>Your updated payment will appear in the current list. The previous version stays in history.</p><label htmlFor={`${prefix}-reason`}>Reason</label><input id={`${prefix}-reason`} value={reason} onChange={(event) => setReason(event.target.value)} disabled={saving} required /></> : null}
      <p className="muted">Record a payment that already happened outside TripTab. Partial payments and overpayments are allowed.</p>
      <p className="muted">TripTab does not transfer money.</p>
      <>
        <div className="two-fields">
          <div><label htmlFor={`${prefix}-payment-from`}>From traveler</label><select id={`${prefix}-payment-from`} value={fromId} onChange={(event) => setFromId(event.target.value)} disabled={saving} required><option value="">Choose traveler</option>{travelers.map((traveler) => <option key={traveler.id} value={traveler.id}>{traveler.display_name}</option>)}</select></div>
          <div><label htmlFor={`${prefix}-payment-to`}>To traveler</label><select id={`${prefix}-payment-to`} value={toId} onChange={(event) => setToId(event.target.value)} disabled={saving} required><option value="">Choose traveler</option>{travelers.map((traveler) => <option key={traveler.id} value={traveler.id}>{traveler.display_name}</option>)}</select></div>
        </div>
        <label htmlFor={`${prefix}-payment-amount`}>Payment amount (NT$)</label><input id={`${prefix}-payment-amount`} type="number" min="1" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} disabled={saving} required />
      </>
      <label htmlFor={dateId}>When did the payment happen?</label><input id={dateId} type="datetime-local" step="any" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} disabled={saving} required />
      {error ? <p className="alert" role="alert">{error}</p> : null}
      <div className="payment-actions">
        {onCancel ? <button type="button" onClick={onCancel} disabled={saving}>Cancel</button> : null}
        <button type="submit" disabled={saving}>{saving ? "Recording…" : initialPayment ? "Save changes" : "Record payment"}</button>
      </div>
      {saved ? <p className="success" role="status">Payment recorded.</p> : null}
    </form>
  );
}

export function SuggestedPayments({ tripId, travelers, suggestions, onRecorded, unavailable = false }: {
  tripId: string;
  travelers: Traveler[];
  suggestions: SettlementSuggestions | null;
  unavailable?: boolean;
  onRecorded: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<Suggestion | null>(null);
  const [message, setMessage] = useState("");
  const { user } = useAuth();
  const membership = travelers.find((traveler) => traveler.user_id === user?.id);
  const name = (id: string, displayName: string) => id === membership?.id ? "You" : displayName;
  return <>
    {message ? <p role="status" className="settlement-status">{message}</p> : null}
    {!unavailable && suggestions?.suggestions.length === 0 ? <p className="muted">No transfers suggested.</p> : <div className="transfer-list">
      {(!unavailable ? suggestions?.suggestions ?? [] : []).map((suggestion) => {
        const from = name(suggestion.from_member_id, suggestion.from_display_name);
        const to = name(suggestion.to_member_id, suggestion.to_display_name);
        return <article className="suggestion-item transfer-row" aria-label={`${from} to ${to}`} key={`${suggestion.from_member_id}-${suggestion.to_member_id}`}>
          <div className="transfer-topline"><h3 aria-label={`${from} to ${to}`}>{from} <span aria-hidden="true">→</span> {to}</h3><strong>{money(suggestion.amount)}</strong></div>
          {membership && (membership.role === "owner" || [suggestion.from_member_id, suggestion.to_member_id].includes(membership.id)) ? <button type="button" className="payment-button" onClick={() => { setMessage(""); setSelected(suggestion); }}>Mark settled<span className="sr-only">: {from} to {to}, {money(suggestion.amount)}</span></button> : null}
        </article>;
      })}
    </div>}
    {selected ? <SettlementConfirmation tripId={tripId} suggestion={selected} onClose={() => setSelected(null)} onRefresh={onRecorded} onFinished={setMessage} /> : null}
  </>;
}

export function PaymentHistory({ payments, travelers = [], tripId, onChanged }: { payments: Settlement[]; travelers?: Traveler[]; tripId?: string; onChanged?: () => Promise<void> }) {
  const { user } = useAuth();
  const owner = travelers.some((traveler) => traveler.user_id === user?.id && traveler.role === "owner");
  const amounts = Object.fromEntries(payments.map((payment) => [payment.id, money(payment.amount)]));
  return <FinancialHistory records={payments} kind="payment">{(payment) => (
    <article className="expense-item" id={`payment-${payment.id}`} key={payment.id}>
      <div className="expense-topline"><div><h3>{payment.from_display_name} settled with {payment.to_display_name}</h3><p className="muted">{new Date(payment.occurred_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</p></div><strong className="expense-amount">{money(payment.amount)}</strong></div>
      <AuditDetails record={payment} kind="payment" amounts={amounts} />
      {tripId && onChanged && (owner || payment.created_by_user_id === user?.id) ? <FinancialActions tripId={tripId} record={payment} kind="payment" onChanged={onChanged} correction={(close) => <PaymentForm tripId={tripId} travelers={travelers} initialPayment={payment} onCancel={close} onRecorded={async () => { await onChanged(); close(); }} />} /> : null}
    </article>
  )}</FinancialHistory>;
}
