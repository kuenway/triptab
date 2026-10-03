"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";

import { api, ApiError, Balances, Expense, ExpenseInput, Settlement, SettlementSuggestions, Traveler, Trip } from "../lib/api";
import { PaymentForm, PaymentHistory, SuggestedPayments } from "./payments";

import { AuditDetails, FinancialActions, localDateTime } from "./financial-history";

import { AccountMenu, useAuth } from "./auth";

const money = (amount: number) => `NT$${new Intl.NumberFormat("en-US").format(amount)}`;

export function TravelerForm({ tripId, onAdded }: { tripId: string; onAdded: () => void }) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return setError("Enter a traveler name.");
    setSaving(true);
    setError("");
    try {
      await api.addTraveler(tripId, name.trim());
      setName("");
      onAdded();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="inline-form">
      <label className="sr-only" htmlFor="traveler-name">Traveler name</label>
      <input id="traveler-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Traveler name" required />
      <button type="submit" disabled={saving}>{saving ? "Adding…" : "Add traveler"}</button>
      {error ? <p className="alert form-wide" role="alert">{error}</p> : null}
    </form>
  );
}

export function BalanceList({ balances }: { balances: Balances }) {
  return (
    <div className="balance-list">
      {balances.balances.length === 0 ? <p className="muted">Add travelers to see balances.</p> : null}
      {balances.balances.map((balance) => (
        <div className="balance-row" key={balance.member_id}>
          <span className="person-name">{balance.display_name}</span>
          <span className={`balance-value ${balance.amount > 0 ? "positive" : balance.amount < 0 ? "negative" : "even"}`}>
            {balance.amount > 0 ? `gets back ${money(balance.amount)}` : balance.amount < 0 ? `owes ${money(-balance.amount)}` : "settled"}
          </span>
        </div>
      ))}
    </div>
  );
}

export function ExpenseHistory({ expenses, travelers, tripId, onChanged }: { expenses: Expense[]; travelers: Traveler[]; tripId?: string; onChanged?: () => Promise<void> }) {
  const { user } = useAuth();
  const owner = travelers.some((traveler) => traveler.user_id === user?.id && traveler.role === "owner");
  const names = Object.fromEntries(travelers.map((traveler) => [traveler.id, traveler.display_name]));
  if (expenses.length === 0) return <p className="muted">No expenses yet. Add one to start the tab.</p>;
  return (
    <div className="expense-list">
      {expenses.map((expense) => (
        <article className="expense-item" id={`expense-${expense.id}`} key={expense.id}>
          <div className="expense-topline">
            <div><h3>{expense.description}</h3><p className="muted">Paid by {names[expense.payer_member_id] ?? "Traveler"} · {new Date(expense.occurred_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</p></div>
            <strong className="expense-amount">{money(expense.amount)}</strong>
          </div>
          <div className="allocation-list">
            <span className="strategy-pill">{expense.split_strategy === "equal" ? "Equal split" : "Exact split"}</span>
            {expense.splits.map((split) => (
              <span key={split.member_id}>{names[split.member_id] ?? "Traveler"} {money(split.amount)}</span>
            ))}
          </div>
          <AuditDetails record={expense} kind="expense" />
          {tripId && onChanged && (owner || expense.created_by_user_id === user?.id) ? <FinancialActions tripId={tripId} record={expense} kind="expense" onChanged={onChanged} correction={(close) => <ExpenseForm tripId={tripId} travelers={travelers} initialExpense={expense} onCancel={close} onCreated={async () => { await onChanged(); close(); }} />} /> : null}
        </article>
      ))}
    </div>
  );
}

export function ExpenseForm({ tripId, travelers, onCreated, initialExpense, onCancel }: { tripId: string; travelers: Traveler[]; onCreated: () => void | Promise<void>; initialExpense?: Expense; onCancel?: () => void }) {
  const [description, setDescription] = useState(initialExpense?.description ?? "");
  const [amount, setAmount] = useState(initialExpense ? String(initialExpense.amount) : "");
  const [payerId, setPayerId] = useState(initialExpense?.payer_member_id ?? "");
  const [occurredAt, setOccurredAt] = useState(initialExpense ? localDateTime(initialExpense.occurred_at) : "");
  const [strategy, setStrategy] = useState<"equal" | "exact">(initialExpense?.split_strategy ?? "equal");
  const [participants, setParticipants] = useState<string[]>(initialExpense?.splits.map((split) => split.member_id) ?? []);
  const [allocations, setAllocations] = useState<Record<string, string>>(Object.fromEntries(initialExpense?.splits.map((split) => [split.member_id, String(split.amount)]) ?? []));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<Expense | null>(null);
  const [reason, setReason] = useState("");
  const pending = useRef(false);
  const prefix = useId();

  const names = Object.fromEntries(travelers.map((traveler) => [traveler.id, traveler.display_name]));
  const numericAmount = Number(amount);
  const allocated = participants.reduce((total, id) => total + Number(allocations[id] || 0), 0);
  const exactMismatch = strategy === "exact" && participants.length > 0 && amount !== "" && allocated !== numericAmount;

  function toggleParticipant(id: string) {
    setParticipants((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    setError("");
    setSaved(null);
    if (initialExpense && !reason.trim()) return setError("Enter a reason.");
    if (!description.trim()) return setError("Enter a description.");
    if (!Number.isSafeInteger(numericAmount) || numericAmount <= 0) return setError("Enter a positive whole NTD amount.");
    if (participants.length === 0) return setError("Choose at least one traveler to split with.");
    if (!occurredAt || Number.isNaN(new Date(occurredAt).getTime())) return setError("Choose when the expense happened.");

    const common = {
      description: description.trim(),
      amount: numericAmount,
      payer_member_id: payerId || travelers[0]?.id,
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
      setParticipants([]);
      setAllocations({});
      setOccurredAt("");
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

  if (travelers.length === 0) return <p className="muted">Add a traveler before recording expenses.</p>;

  return (
    <form onSubmit={submit} className="stack-form expense-form">
      {initialExpense ? <><p>The original expense will remain in history and will be marked void. This saves a new replacement record.</p><label htmlFor={`${prefix}-reason`}>Reason</label><input id={`${prefix}-reason`} value={reason} onChange={(event) => setReason(event.target.value)} required disabled={saving} /></> : null}
      <fieldset disabled={saving} className="stack-form form-fields">
      <div className="two-fields">
        <div><label htmlFor={`${prefix}-expense-description`}>Description</label><input id={`${prefix}-expense-description`} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="e.g. Dinner" required /></div>
        <div><label htmlFor={`${prefix}-expense-amount`}>Amount (NT$)</label><input id={`${prefix}-expense-amount`} type="number" min="1" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} required /></div>
      </div>
      <div className="two-fields">
        <div><label htmlFor={`${prefix}-expense-payer`}>Paid by</label><select id={`${prefix}-expense-payer`} value={payerId || travelers[0].id} onChange={(event) => setPayerId(event.target.value)}>{travelers.map((traveler) => <option key={traveler.id} value={traveler.id}>{traveler.display_name}</option>)}</select></div>
        <div><label htmlFor={`${prefix}-expense-date`}>When did it happen?</label><input id={`${prefix}-expense-date`} type="datetime-local" step="any" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} required /></div>
      </div>
      <fieldset className="choice-fieldset">
        <legend>Split method</legend>
        <div className="segmented">
          <label><input type="radio" name={`${prefix}-split-strategy`} value="equal" checked={strategy === "equal"} onChange={() => setStrategy("equal")} /> Equal</label>
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
      {error ? <p className="alert" role="alert">{error}</p> : null}
      </fieldset>
      <div className="payment-actions">{onCancel ? <button type="button" disabled={saving} onClick={onCancel}>Cancel</button> : null}<button type="submit" disabled={saving || (strategy === "exact" && exactMismatch)}>{saving ? "Saving…" : initialExpense ? "Save correction" : "Add expense"}</button></div>
      {saved ? <div className="success" role="status"><strong>Expense saved.</strong> Stored split: {saved.splits.map((split) => `${names[split.member_id] ?? "Traveler"} ${money(split.amount)}`).join(" · ")}</div> : null}
    </form>
  );
}

export function TripDashboard({ tripId }: { tripId: string }) {
  const { user } = useAuth();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [travelers, setTravelers] = useState<Traveler[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [balances, setBalances] = useState<Balances | null>(null);
  const [suggestions, setSuggestions] = useState<SettlementSuggestions | null>(null);
  const [suggestionsError, setSuggestionsError] = useState("");
  const [payments, setPayments] = useState<Settlement[] | null>(null);
  const [paymentsError, setPaymentsError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(async () => {
    setSuggestions(null);
    setSuggestionsError("");
    setPayments(null);
    setPaymentsError("");
    try {
      const [nextTrip, nextTravelers, nextExpenses, nextBalances, nextSuggestions, nextPayments] = await Promise.all([
        api.getTrip(tripId), api.listTravelers(tripId), api.listExpenses(tripId), api.getBalances(tripId),
        api.getSettlementSuggestions(tripId).catch((cause: Error) => {
          setSuggestionsError(cause.message);
          return null;
        }),
        api.listSettlements(tripId).catch((cause: Error) => {
          setPaymentsError(cause.message);
          return null;
        }),
      ]);
      setTrip(nextTrip);
      setTravelers(nextTravelers);
      setExpenses(nextExpenses);
      setBalances(nextBalances);
      setSuggestions(nextSuggestions);
      setPayments(nextPayments);
      setError("");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
      else setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }, [tripId]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const owner = travelers.some((traveler) => traveler.user_id === user?.id && traveler.role === "owner");

  if (loading) return <main className="shell"><p role="status">Loading trip…</p></main>;
  if (notFound) return <main className="shell"><p className="eyebrow">TRIP NOT FOUND</p><h1>We couldn’t find that trip.</h1><Link href="/">← Back to trips</Link></main>;
  if (!trip) return <main className="shell"><p className="alert" role="alert">{error || "Could not load this trip."}</p><button onClick={() => void load()}>Try again</button><p><Link href="/">← Back to trips</Link></p></main>;

  return (
    <main className="shell">
      <header className="site-header"><Link href="/" className="wordmark">TripTab<span className="brand-dot">.</span></Link><div className="account-menu"><Link className="back-link" href="/">← All trips</Link><AccountMenu /></div></header>
      <div className="page-intro trip-intro"><p className="eyebrow">YOUR TRIP</p><h1>{trip.name}</h1><p>Shared expenses in TWD · {travelers.length} {travelers.length === 1 ? "traveler" : "travelers"}</p></div>
      {error ? <p className="alert" role="alert">{error}</p> : null}
      <div className="dashboard-grid">
        <div className="dashboard-main">
          <section className="panel" aria-labelledby="add-expense-heading"><div className="section-heading"><h2 id="add-expense-heading">Add an expense</h2></div><ExpenseForm tripId={tripId} travelers={travelers} onCreated={() => void load()} /></section>
          <section className="panel" aria-labelledby="expenses-heading"><div className="section-heading"><h2 id="expenses-heading">Expense history</h2><span className="count">{expenses.length}</span></div><ExpenseHistory expenses={expenses} travelers={travelers} tripId={tripId} onChanged={load} /></section>
          <section className="panel" aria-labelledby="record-payment-heading"><div className="section-heading"><h2 id="record-payment-heading">Record payment</h2></div><PaymentForm tripId={tripId} travelers={travelers} onRecorded={load} /></section>
          <section className="panel" aria-labelledby="payment-history-heading"><div className="section-heading"><h2 id="payment-history-heading">Payment history</h2></div>{paymentsError ? <p className="alert" role="alert">{paymentsError}</p> : payments ? <PaymentHistory payments={payments} travelers={travelers} tripId={tripId} onChanged={load} /> : <p className="muted" role="status">Loading payment history…</p>}</section>
        </div>
        <div className="dashboard-side">
          <section className="panel" aria-labelledby="balances-heading"><div className="section-heading"><h2 id="balances-heading">Balances</h2></div><p className="muted section-caption">Who should receive and who owes.</p>{balances ? <BalanceList balances={balances} /> : <p className="muted">Loading balances…</p>}</section>
          <section className="panel" aria-labelledby="suggested-payments-heading"><div className="section-heading"><h2 id="suggested-payments-heading">Suggested payments</h2></div><p className="muted section-caption">Mark as paid only after a payment happened outside TripTab.</p>{suggestionsError ? <p className="alert" role="alert">{suggestionsError}</p> : suggestions ? <SuggestedPayments tripId={tripId} travelers={travelers} suggestions={suggestions} onRecorded={load} /> : <p className="muted" role="status">Loading suggested payments…</p>}</section>
          <section className="panel" aria-labelledby="travelers-heading"><div className="section-heading"><h2 id="travelers-heading">Travelers</h2><span className="count">{travelers.length}</span></div>{travelers.length === 0 ? <p className="muted">No travelers yet. Add the people sharing this trip.</p> : <div className="traveler-list">{travelers.map((traveler) => <div className="traveler-row" key={traveler.id}><span className="person-dot" aria-hidden="true">{traveler.display_name.charAt(0).toUpperCase()}</span>{traveler.display_name} <span className="strategy-pill">{traveler.role === "owner" ? "Owner" : traveler.user_id ? "Member" : "Guest"}</span></div>)}</div>}{owner ? <TravelerForm tripId={tripId} onAdded={() => void load()} /> : null}</section>
        </div>
      </div>
      <p className="dev-note">Private trip · Financial history is preserved</p>
    </main>
  );
}
