"use client";

import { FormEvent, useLayoutEffect, useId, useRef, useState } from "react";
import { api, ApiError, Expense, ExpenseInput, Traveler } from "../lib/api";
import { useAuth } from "./auth";
import { localDateTime } from "./financial-history";

const money = (amount: number) => `NT$${new Intl.NumberFormat("en-US").format(amount)}`;

export function ExpenseForm({ tripId, travelers, onCreated, initialExpense, onCancel, onDraftStateChange }: { tripId: string; travelers: Traveler[]; onCreated: () => void | Promise<void>; initialExpense?: Expense; onCancel?: () => void; onDraftStateChange?: (state: { dirty: boolean; saving: boolean }) => void }) {
  const { user } = useAuth();
  const ownMemberId = travelers.find((member) => member.user_id === user?.id)?.id ?? "";
  const [description, setDescription] = useState(initialExpense?.description ?? "");
  const [amount, setAmount] = useState(initialExpense ? String(initialExpense.amount) : "");
  const [selectedPayer, setPayerId] = useState<string | null>(initialExpense?.payer_member_id ?? null);
  const payerId = selectedPayer ?? ownMemberId;
  const [occurredAt, setOccurredAt] = useState(() => initialExpense ? localDateTime(initialExpense.occurred_at) : localDateTime(new Date().toISOString()).slice(0, 16));
  const [strategy, setStrategy] = useState<"equal" | "exact">(initialExpense?.split_strategy ?? "equal");
  const [selectedParticipants, setParticipants] = useState<string[] | null>(initialExpense?.splits.map((split) => split.member_id) ?? null);
  // Defaults follow current travelers only until the user starts editing.
  const participants = (selectedParticipants ?? travelers.map((member) => member.id)).filter((id) => travelers.some((member) => member.id === id));
  const [allocations, setAllocations] = useState<Record<string, string>>(Object.fromEntries(initialExpense?.splits.map((split) => [split.member_id, String(split.amount)]) ?? []));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<Expense | null>(null);
  const [reason, setReason] = useState("");
  const pending = useRef(false);
  const prefix = useId();

  const [initialDraft] = useState(() => JSON.stringify({ description: initialExpense?.description ?? "", amount: initialExpense ? String(initialExpense.amount) : "", payerId: initialExpense?.payer_member_id ?? ownMemberId, occurredAt, strategy: initialExpense?.split_strategy ?? "equal", participants: [...participants].sort(), allocations: initialExpense?.split_strategy === "exact" ? allocations : {} }));
  const dirty = reason !== "" || JSON.stringify({ description, amount, payerId, occurredAt, strategy, participants: [...participants].sort(), allocations: strategy === "exact" ? allocations : {} }) !== initialDraft;
  useLayoutEffect(() => { onDraftStateChange?.({ dirty, saving }); }, [dirty, saving, onDraftStateChange]);

  const names = Object.fromEntries(travelers.map((traveler) => [traveler.id, traveler.display_name]));
  const numericAmount = Number(amount);
  const allocated = participants.reduce((total, id) => total + Number(allocations[id] || 0), 0);
  const exactMismatch = strategy === "exact" && participants.length > 0 && amount !== "" && allocated !== numericAmount;

  function toggleParticipant(id: string) {
    setParticipants((current) => (current ?? participants).includes(id) ? (current ?? participants).filter((value) => value !== id) : [...(current ?? participants), id]);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    setError("");
    setSaved(null);
    if (initialExpense && !reason.trim()) return setError("Enter a reason.");
    if (!description.trim()) return setError("Enter a description.");
    if (!Number.isSafeInteger(numericAmount) || numericAmount <= 0) return setError("Enter a positive whole NTD amount.");
    if (participants.length === 0) return setError("Choose at least one tripmate to split with.");
    if (!occurredAt || Number.isNaN(new Date(occurredAt).getTime())) return setError("Choose when the expense happened.");

    const common = {
      description: description.trim(),
      amount: numericAmount,
      payer_member_id: travelers.some((member) => member.id === payerId) ? payerId : "",
      occurred_at: initialExpense && occurredAt === localDateTime(initialExpense.occurred_at)
        ? initialExpense.occurred_at : new Date(occurredAt).toISOString(),
    };
    if (!common.payer_member_id) return setError("Choose who paid.");
    let input: ExpenseInput;
    if (strategy === "equal") {
      input = { ...common, split_strategy: "equal", participant_member_ids: participants };
    } else {
      const splits = participants.map((id) => ({ member_id: id, amount: Number(allocations[id]) }));
      if (splits.some((split) => !Number.isSafeInteger(split.amount) || split.amount < 0)) return setError("Use whole NTD amounts for every allocation.");
      if (exactMismatch) return setError("Exact allocations must total the expense amount.");
      input = { ...common, split_strategy: "exact", splits };
    }

    pending.current = true;
    setSaving(true);
    try {
      const expense = initialExpense
        ? await api.correctExpense(tripId, initialExpense.id, reason.trim(), input)
        : await api.addExpense(tripId, input);
      setSaved(expense);
      setDescription("");
      setAmount("");
      setParticipants(null);
      setPayerId(null);
      setStrategy("equal");
      setAllocations({});
      setOccurredAt(localDateTime(new Date().toISOString()).slice(0, 16));
      await onCreated();
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 0
        ? "Could not confirm whether the expense was saved. Refresh history before trying again."
        : (cause as Error).message);
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  if (travelers.length === 0) return <p className="muted">Add a tripmate before recording expenses.</p>;

  return (
    <form onSubmit={submit} onChange={() => setParticipants((current) => current ?? participants)} className="stack-form expense-form">
      <fieldset disabled={saving} className="stack-form form-fields" aria-describedby={error ? `${prefix}-error` : undefined}>
      {initialExpense ? <><p>Your updated expense will appear in the current list. The previous version stays in history.</p><label htmlFor={`${prefix}-reason`}>Reason</label><input id={`${prefix}-reason`} aria-describedby={error ? `${prefix}-error` : undefined} value={reason} onChange={(event) => setReason(event.target.value)} required disabled={saving} /></> : null}
      <div className="two-fields">
        <div><label htmlFor={`${prefix}-expense-description`}>Description</label><input id={`${prefix}-expense-description`} aria-describedby={error ? `${prefix}-error` : undefined} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="e.g. Dinner" required /></div>
        <div><label htmlFor={`${prefix}-expense-amount`}>Amount (NT$)</label><input id={`${prefix}-expense-amount`} type="number" min="1" step="1" aria-describedby={error ? `${prefix}-error` : undefined} value={amount} onChange={(event) => setAmount(event.target.value)} required /></div>
      </div>
      <div className="two-fields">
        <div><label htmlFor={`${prefix}-expense-payer`}>Paid by</label><select id={`${prefix}-expense-payer`} aria-describedby={error ? `${prefix}-error` : undefined} value={payerId} onChange={(event) => setPayerId(event.target.value)}><option value="">Choose who paid</option>{travelers.map((traveler) => <option key={traveler.id} value={traveler.id}>{traveler.display_name}</option>)}</select></div>
        <div><label htmlFor={`${prefix}-expense-date`}>When did it happen?</label><input id={`${prefix}-expense-date`} type="datetime-local" step="any" aria-describedby={error ? `${prefix}-error` : undefined} value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} required /></div>
      </div>
      <fieldset className="choice-fieldset">
        <legend>Split method</legend>
        <div className="segmented">
          <label><input type="radio" name={`${prefix}-split-strategy`} value="equal" checked={strategy === "equal"} onChange={() => { setStrategy("equal"); setParticipants(travelers.map((member) => member.id)); }} /> Equal</label>
          <label><input type="radio" name={`${prefix}-split-strategy`} value="exact" checked={strategy === "exact"} onChange={() => setStrategy("exact")} /> Exact amounts</label>
        </div>
      </fieldset>
      <fieldset className="choice-fieldset">
        <legend>Split between</legend>
        <div className="participant-grid">
          {travelers.map((traveler) => (
            <label className="participant-option" key={traveler.id}>
              <input type="checkbox" checked={participants.includes(traveler.id)} onChange={() => toggleParticipant(traveler.id)} /> {traveler.display_name}
            </label>
          ))}
        </div>
      </fieldset>
      {strategy === "exact" && participants.length > 0 ? (
        <div className="exact-panel">
          <div className="section-heading"><strong>Exact allocations</strong><span className={exactMismatch ? "negative" : "positive"}>Allocated {money(allocated)} of {money(Number.isFinite(numericAmount) ? numericAmount : 0)}</span></div>
          {participants.map((id) => (
            <div className="allocation-input" key={id}><label htmlFor={`${prefix}-allocation-${id}`}>{names[id]} allocation</label><input id={`${prefix}-allocation-${id}`} type="number" min="0" step="1" value={allocations[id] ?? ""} onChange={(event) => setAllocations((current) => ({ ...current, [id]: event.target.value }))} required /></div>
          ))}
          {exactMismatch ? <p className="field-hint" role="status">Allocations must match the expense amount.</p> : null}
        </div>
      ) : null}
      {!initialExpense && !ownMemberId ? <p className="field-hint">Your tripmate membership could not be resolved. Choose who paid explicitly or refresh the trip.</p> : null}
      {error ? <p id={`${prefix}-error`} className="alert" role="alert">{error}</p> : null}
      </fieldset>
      <div className="payment-actions">{onCancel ? <button type="button" disabled={saving} onClick={onCancel}>Cancel</button> : null}<button type="submit" disabled={saving || (strategy === "exact" && exactMismatch)}>{saving ? "Saving…" : initialExpense ? "Save changes" : "Add expense"}</button></div>
      {saved ? <div className="success" role="status"><strong>Expense saved.</strong> Stored split: {saved.splits.map((split) => `${names[split.member_id] ?? "Tripmate"} ${money(split.amount)}`).join(" · ")}</div> : null}
    </form>
  );
}
