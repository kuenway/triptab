"use client";

import { FormEvent, useState } from "react";

import { api, Balances, Expense, Traveler } from "../lib/api";
import { PaymentForm, PaymentHistory, SuggestedPayments } from "./payments";

import { AuditDetails, FinancialActions, FinancialHistory } from "./financial-history";

import { useAuth } from "./auth";
import { TravelerInvitations } from "./invitations";
import { useTrip } from "./trip-shell";

import { ExpenseForm } from "./expense-form";
import { ExpenseLedger } from "./expense-ledger";
export { ExpenseForm } from "./expense-form";

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

export function ExpenseHistory({ expenses, travelers, tripId, onChanged, historyOnly = false }: { expenses: Expense[]; travelers: Traveler[]; tripId?: string; onChanged?: () => Promise<void>; historyOnly?: boolean }) {
  const { user } = useAuth();
  const owner = travelers.some((traveler) => traveler.user_id === user?.id && traveler.role === "owner");
  const names = Object.fromEntries(travelers.map((traveler) => [traveler.id, traveler.display_name]));
  const amounts = Object.fromEntries(expenses.map((expense) => [expense.id, money(expense.amount)]));
  return (
    <FinancialHistory records={expenses} kind="expense" historyOnly={historyOnly}>
      {(expense) => (
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
          <AuditDetails record={expense} kind="expense" amounts={amounts} />
          {tripId && onChanged && (owner || expense.created_by_user_id === user?.id) ? <FinancialActions tripId={tripId} record={expense} kind="expense" onChanged={onChanged} correction={(close) => <ExpenseForm tripId={tripId} travelers={travelers} initialExpense={expense} onCancel={close} onCreated={async () => { await onChanged(); close(); }} />} /> : null}
        </article>
      )}
    </FinancialHistory>
  );
}


export function TripSection({ section }: { section: "expenses" | "balances" | "travelers" | "history" }) {
  const { user } = useAuth();
  const { trip, travelers, expenses, balances, suggestions, suggestionsError, payments, paymentsError, load } = useTrip();
  const tripId = trip.id;
  const owner = travelers.some((traveler) => traveler.user_id === user?.id && traveler.role === "owner");

  if (section === "expenses") return <ExpenseLedger history={<ExpenseHistory expenses={expenses} travelers={travelers} historyOnly />} />;

  if (section === "balances") return <div className="trip-section trip-columns">
    <div className="dashboard-main">
      <section className="panel" aria-labelledby="balances-heading"><div className="section-heading"><h2 id="balances-heading">Balances</h2></div><p className="muted section-caption">Who should receive and who owes.</p>{balances ? <BalanceList balances={balances} /> : <p className="muted">Loading balances…</p>}</section>
      <section className="panel" aria-labelledby="suggested-payments-heading"><div className="section-heading"><h2 id="suggested-payments-heading">Suggested payments</h2></div><p className="muted section-caption">Mark as paid only after a payment happened outside TripTab.</p>{suggestionsError ? <p className="alert" role="alert">{suggestionsError}</p> : suggestions ? <SuggestedPayments tripId={tripId} travelers={travelers} suggestions={suggestions} onRecorded={load} /> : <p className="muted" role="status">Loading suggested payments…</p>}</section>
    </div>
    <div className="dashboard-side">
      <section className="panel" aria-labelledby="record-payment-heading"><div className="section-heading"><h2 id="record-payment-heading">Record payment</h2></div><PaymentForm tripId={tripId} travelers={travelers} onRecorded={load} /></section>
      <section className="panel" aria-labelledby="payment-history-heading"><div className="section-heading"><h2 id="payment-history-heading">Current payments</h2></div>{paymentsError ? <p className="alert" role="alert">{paymentsError}</p> : payments ? <PaymentHistory payments={payments} travelers={travelers} tripId={tripId} onChanged={load} /> : <p className="muted" role="status">Loading payment history…</p>}</section>
    </div>
  </div>;

  if (section === "travelers") return <div className="trip-section">
    <section className="panel" aria-labelledby="travelers-heading"><div className="section-heading"><h2 id="travelers-heading">Travelers</h2><span className="count">{travelers.length}</span></div><TravelerInvitations tripId={tripId} travelers={travelers} canManage={owner} onChanged={load} />{owner ? <TravelerForm tripId={tripId} onAdded={() => void load()} /> : null}</section>
  </div>;

  return <div className="trip-section">
    <h2>History</h2>
    <section className="panel" aria-labelledby="expense-history-heading"><div className="section-heading"><h2 id="expense-history-heading">Expense history</h2></div><ExpenseHistory expenses={expenses} travelers={travelers} /></section>
    <section className="panel" aria-labelledby="all-payment-history-heading"><div className="section-heading"><h2 id="all-payment-history-heading">Payment history</h2></div>{paymentsError ? <p className="alert" role="alert">{paymentsError}</p> : payments ? <PaymentHistory payments={payments} travelers={travelers} /> : <p className="muted" role="status">Loading payment history…</p>}</section>
  </div>;
}
