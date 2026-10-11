"use client";

import Link from "next/link";
import { ReactNode, useState } from "react";
import { Expense } from "../lib/api";
import { useAuth } from "./auth";
import { ExpenseDialog } from "./expense-dialog";
import { AuditDetails, FinancialActions } from "./financial-history";
import { useTrip } from "./trip-shell";

const money = (amount: number) => `NT$${new Intl.NumberFormat("en-US").format(amount)}`;
const day = (value: string | Date) => new Date(value).toDateString();
function dateLabel(value: string) {
  const today = new Date(), yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  return day(value) === day(today) ? "Today" : day(value) === day(yesterday) ? "Yesterday" : new Date(value).toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "short", day: "numeric" });
}

export function ExpenseLedger({ history }: { history: ReactNode }) {
  const { user } = useAuth();
  const { trip, travelers, expenses, balances, dataError, load } = useTrip();
  const [entry, setEntry] = useState<Expense | "new" | null>(null);
  const member = travelers.find((traveler) => traveler.user_id === user?.id);
  const owner = member?.role === "owner";
  const balance = !dataError ? balances?.balances.find((balance) => balance.member_id === member?.id) : undefined;
  const names = Object.fromEntries(travelers.map((traveler) => [traveler.id, traveler.display_name]));
  const amounts = Object.fromEntries(expenses.map((expense) => [expense.id, money(expense.amount)]));
  const current = expenses.filter((expense) => expense.status === "active").sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at) || Date.parse(b.created_at) - Date.parse(a.created_at) || a.id.localeCompare(b.id));
  const groups = new Map<string, Expense[]>();
  for (const expense of current) {
    const key = day(expense.occurred_at);
    groups.set(key, [...(groups.get(key) ?? []), expense]);
  }
  return <div className="trip-section expense-workspace">
    {balance ? <div className="personal-balance"><p>{balance.amount > 0 ? `You are owed ${money(balance.amount)}` : balance.amount < 0 ? `You owe ${money(-balance.amount)}` : "You are settled up"}</p><Link href={`/trips/${trip.id}/balances`}>View balances →</Link></div> : null}
    <section aria-label="Current expenses" className="expense-ledger">
      <div className="ledger-heading"><div className="section-heading"><h2>Expenses</h2><span className="count">{current.length}</span></div><button className="expense-trigger" aria-label="Add expense" onClick={() => setEntry("new")}>+ Expense</button></div>
      <div role="group" aria-label="Current expenses">
        {current.length === 0 ? <div className="ledger-empty"><h3>{expenses.length ? "No current expenses" : "No expenses yet."}</h3><p className="muted">{expenses.length ? "Previous records are preserved in history." : "Add the first shared expense for this trip."}</p></div> : [...groups].map(([key, group]) => <section className="expense-date-group" key={key} aria-label={dateLabel(group[0]!.occurred_at)}>
          <h3>{dateLabel(group[0]!.occurred_at)}</h3>
          {group.map((expense) => {
            const share = expense.splits.find((split) => split.member_id === member?.id);
            const payer = expense.payer_member_id === member?.id ? "You" : names[expense.payer_member_id] ?? "Traveler";
            return <article className="ledger-row" id={`expense-${expense.id}`} key={expense.id}>
              <div className="ledger-topline"><h4>{expense.description}</h4><strong className="expense-amount">{money(expense.amount)}</strong></div>
              <p className="ledger-meta muted">{payer} paid · {expense.splits.length} {expense.splits.length === 1 ? "traveler" : "travelers"}</p>
              {share ? <p className="personal-share">Your share {money(share.amount)}</p> : null}
              <div className="ledger-row-controls"><details className="expense-details"><summary>Details<span className="sr-only"> for {expense.description}</span></summary><div>
                <p>Paid by {names[expense.payer_member_id] ?? "Traveler"}</p>
                <p><time dateTime={expense.occurred_at}>{new Date(expense.occurred_at).toLocaleString()}</time> · {expense.split_strategy === "equal" ? "Equal split" : "Exact split"}</p>
                <ul>{expense.splits.map((split) => <li key={split.member_id}><span>{names[split.member_id] ?? "Traveler"}</span><strong>{money(split.amount)}</strong></li>)}</ul>
              </div></details>
              {(owner || expense.created_by_user_id === user?.id) ? <FinancialActions tripId={trip.id} record={expense} kind="expense" onChanged={load} onEdit={() => setEntry(expense)} correction={() => null} /> : null}</div>
              <AuditDetails record={expense} kind="expense" amounts={amounts} />
            </article>;
          })}
        </section>)}
      </div>
      {history}
    </section>
    {entry ? <ExpenseDialog tripId={trip.id} travelers={travelers} {...(entry !== "new" ? { expense: entry } : {})} onClose={() => setEntry(null)} onSaved={load} /> : null}
  </div>;
}
