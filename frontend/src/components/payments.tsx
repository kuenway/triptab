"use client";

import { FormEvent, useRef, useState } from "react";

import { api, ApiError, Settlement, SettlementSuggestions, Traveler } from "../lib/api";

type Suggestion = SettlementSuggestions["suggestions"][number];
const money = (amount: number) => `NT$${new Intl.NumberFormat("en-US").format(amount)}`;

function currentLocalDateTime() {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
}

export function PaymentForm({ tripId, travelers, suggestion, onRecorded, onCancel }: {
  tripId: string;
  travelers: Traveler[];
  suggestion?: Suggestion;
  onRecorded: () => Promise<void>;
  onCancel?: () => void;
}) {
  const [fromId, setFromId] = useState(suggestion?.from_member_id ?? "");
  const [toId, setToId] = useState(suggestion?.to_member_id ?? "");
  const [amount, setAmount] = useState(suggestion ? String(suggestion.amount) : "");
  const [occurredAt, setOccurredAt] = useState(currentLocalDateTime);
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const dateId = suggestion ? "suggested-payment-date" : "manual-payment-date";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    setError("");
    setSaved(false);
    const numericAmount = Number(amount);
    if (!fromId || !toId) return setError("Choose the sender and recipient.");
    if (fromId === toId) return setError("Sender and recipient must be different travelers.");
    if (!Number.isSafeInteger(numericAmount) || numericAmount <= 0) return setError("Enter a positive whole NTD amount.");
    if (!occurredAt || Number.isNaN(new Date(occurredAt).getTime())) return setError("Choose when the payment happened.");

    pending.current = true;
    setSaving(true);
    try {
      await api.recordSettlement(tripId, {
        from_member_id: fromId,
        to_member_id: toId,
        amount: numericAmount,
        occurred_at: new Date(occurredAt).toISOString(),
      });
      setSaved(true);
      if (!suggestion) {
        setFromId("");
        setToId("");
        setAmount("");
        setOccurredAt(currentLocalDateTime());
      }
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

  if (!suggestion && travelers.length < 2) return <p className="muted">Add at least two travelers to record a payment.</p>;

  return (
    <form onSubmit={submit} className="stack-form">
      {suggestion ? <p>This records that {suggestion.from_display_name} paid {suggestion.to_display_name} {money(suggestion.amount)} outside TripTab. Only confirm after the payment occurred.</p> : <p className="muted">Record a payment that already happened outside TripTab. Partial payments and overpayments are allowed.</p>}
      <p className="muted">TripTab does not transfer money.</p>
      {!suggestion ? <>
        <div className="two-fields">
          <div><label htmlFor="payment-from">From traveler</label><select id="payment-from" value={fromId} onChange={(event) => setFromId(event.target.value)} disabled={saving} required><option value="">Choose traveler</option>{travelers.map((traveler) => <option key={traveler.id} value={traveler.id}>{traveler.display_name}</option>)}</select></div>
          <div><label htmlFor="payment-to">To traveler</label><select id="payment-to" value={toId} onChange={(event) => setToId(event.target.value)} disabled={saving} required><option value="">Choose traveler</option>{travelers.map((traveler) => <option key={traveler.id} value={traveler.id}>{traveler.display_name}</option>)}</select></div>
        </div>
        <label htmlFor="payment-amount">Payment amount (NT$)</label><input id="payment-amount" type="number" min="1" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} disabled={saving} required />
      </> : null}
      <label htmlFor={dateId}>When did the payment happen?</label><input id={dateId} type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} disabled={saving} required />
      {error ? <p className="alert" role="alert">{error}</p> : null}
      <div className="payment-actions">
        {onCancel ? <button type="button" onClick={onCancel} disabled={saving}>Cancel</button> : null}
        <button type="submit" disabled={saving}>{saving ? "Recording…" : "Record payment"}</button>
      </div>
      {saved ? <p className="success" role="status">Payment recorded.</p> : null}
    </form>
  );
}

export function SuggestedPayments({ tripId, travelers, suggestions, onRecorded }: {
  tripId: string;
  travelers: Traveler[];
  suggestions: SettlementSuggestions;
  onRecorded: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<Suggestion | null>(null);
  if (suggestions.suggestions.length === 0) return <p className="muted">Everyone is settled up.</p>;
  return (
    <div className="balance-list">
      {suggestions.suggestions.map((suggestion) => (
        <div className="suggestion-item" key={`${suggestion.from_member_id}-${suggestion.to_member_id}`}>
          <div className="section-heading"><span className="person-name">{suggestion.from_display_name} → {suggestion.to_display_name}</span><span className="balance-value">{money(suggestion.amount)}</span></div>
          <button type="button" className="payment-button" disabled={selected !== null} onClick={() => setSelected(suggestion)}>Mark as paid</button>
        </div>
      ))}
      {selected ? <div className="confirmation-panel" role="group" aria-labelledby="payment-confirmation-heading">
        <h3 id="payment-confirmation-heading">Record payment?</h3>
        <PaymentForm tripId={tripId} travelers={travelers} suggestion={selected} onCancel={() => setSelected(null)} onRecorded={async () => { await onRecorded(); setSelected(null); }} />
      </div> : null}
    </div>
  );
}

export function PaymentHistory({ payments }: { payments: Settlement[] }) {
  if (payments.length === 0) return <p className="muted">No payments recorded yet.</p>;
  return <div className="expense-list">{payments.map((payment) => (
    <article className="expense-item" key={payment.id}>
      <div className="expense-topline"><div><h3>{payment.from_display_name} paid {payment.to_display_name}</h3><p className="muted">{new Date(payment.occurred_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</p></div><strong className="expense-amount">{money(payment.amount)}</strong></div>
    </article>
  ))}</div>;
}
