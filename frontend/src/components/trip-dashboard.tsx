"use client";

import { FormEvent, useState } from "react";

import { api, Expense, Traveler } from "../lib/api";
import { FinancialTimeline } from "./financial-timeline";
import { BalancesSection } from "./balances-section";
export { BalanceList } from "./balances-section";

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
    if (!name.trim()) return setError("Enter a tripmate name.");
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
      <label className="sr-only" htmlFor="traveler-name">Tripmate name</label>
      <input id="traveler-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Tripmate name" required />
      <button type="submit" disabled={saving}>{saving ? "Adding…" : "Add tripmate"}</button>
      {error ? <p className="alert form-wide" role="alert">{error}</p> : null}
    </form>
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
            <div><h3>{expense.description}</h3><p className="muted">Paid by {names[expense.payer_member_id] ?? "Tripmate"} · {new Date(expense.occurred_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</p></div>
            <strong className="expense-amount">{money(expense.amount)}</strong>
          </div>
          <div className="allocation-list">
            <span className="strategy-pill">{expense.split_strategy === "equal" ? "Equal split" : "Exact split"}</span>
            {expense.splits.map((split) => (
              <span key={split.member_id}>{names[split.member_id] ?? "Tripmate"} {money(split.amount)}</span>
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
  const { trip, travelers, expenses, payments, paymentsError, dataError, load } = useTrip();
  const tripId = trip.id;
  const owner = travelers.some((traveler) => traveler.user_id === user?.id && traveler.role === "owner");

  if (section === "expenses") return <ExpenseLedger history={<ExpenseHistory expenses={expenses} travelers={travelers} historyOnly />} />;

  if (section === "balances") return <BalancesSection />;

  if (section === "travelers") return <div className="trip-section">
    <section className="tripmates-section" aria-labelledby="travelers-heading"><div className="section-heading"><h2 id="travelers-heading">Tripmates</h2><span className="count">{travelers.length}</span></div>{dataError ? <div><p role="alert" className="alert">{dataError}</p><button className="payment-button" onClick={() => void load()}>Retry tripmates</button></div> : <><TravelerInvitations tripId={tripId} travelers={travelers} canManage={owner} currentUserId={user?.id} onChanged={load} />{owner ? <TravelerForm tripId={tripId} onAdded={() => void load()} /> : null}</>}</section>
  </div>;

  return <FinancialTimeline expenses={expenses} payments={payments} travelers={travelers} tripId={tripId} error={dataError || paymentsError} onChanged={load} />;
}
