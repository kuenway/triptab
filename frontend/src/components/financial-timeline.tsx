"use client";

import { useState } from "react";
import { Expense, Settlement, Traveler } from "../lib/api";
import { dateLabel, day } from "../lib/dates";
import { useAuth } from "./auth";
import { FinancialActions } from "./financial-history";
import { PaymentForm } from "./payments";

type HistoryEvent = {
  kind: "expense" | "settlement";
  action: "added" | "edited" | "removed";
  record: Expense | Settlement;
  previous?: Expense | Settlement;
  at: string;
  actor?: string | null;
};
const money = (amount: number) => `NT$${new Intl.NumberFormat("en-US").format(amount)}`;

// Creation timestamps order additions/replacements; void timestamps order removals.
// Replacement links prove edits. A correction is not also rendered as a removal.
export function historyEvents(expenses: Expense[], settlements: Settlement[]): HistoryEvent[] {
  const events: HistoryEvent[] = [];
  for (const [kind, records] of [["expense", expenses], ["settlement", settlements]] as const) {
    const byId = new Map<string, Expense | Settlement>(records.map((record) => [record.id, record]));
    for (const record of records) {
      events.push({ kind, record, action: record.replaces_id ? "edited" : "added", previous: record.replaces_id ? byId.get(record.replaces_id) : undefined, at: record.created_at, actor: record.created_by_user_id });
      if (record.status === "voided" && !record.replaced_by_id && record.void_created_at) events.push({ kind, record, action: "removed", at: record.void_created_at, actor: record.void_created_by_user_id });
    }
  }
  return events.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

export function FinancialTimeline({ expenses, payments, travelers, tripId, error, onChanged }: {
  expenses: Expense[];
  payments: Settlement[] | null;
  travelers: Traveler[];
  tripId: string;
  error: string;
  onChanged: () => Promise<void>;
}) {
  const { user } = useAuth();
  const [editing, setEditing] = useState<string | null>(null);
  const member = travelers.find((person) => person.user_id === user?.id);
  const owner = member?.role === "owner";
  const name = (id: string, fallback = "Tripmate") => id === member?.id ? "You" : travelers.find((person) => person.id === id)?.display_name ?? fallback;
  // Account IDs alone establish actors. Financial participants never establish authorship.
  const actorName = (id?: string | null) => id && id === user?.id ? "You" : travelers.find((person) => person.user_id && person.user_id === id)?.display_name;
  const events = historyEvents(expenses, payments ?? []);
  const groups = new Map<string, HistoryEvent[]>();
  for (const event of events) groups.set(day(event.at), [...(groups.get(day(event.at)) ?? []), event]);

  return <section className="trip-section history-section" aria-labelledby="history-heading">
    <div className="section-heading"><h2 id="history-heading">History</h2></div>
    <p className="muted history-caption">Expenses and settlements, including edits and removals.</p>
    {error ? <div><p role="alert" className="alert">{error}</p><button className="payment-button" onClick={() => void onChanged()}>Retry history</button></div> : payments === null ? <p className="muted" role="status">Loading history…</p> : events.length === 0 ? <div className="history-empty"><h3>No history yet.</h3><p className="muted">Shared expenses and confirmed settlements will appear here.</p></div> : <div className="financial-timeline" aria-label="Financial activity">
      {[...groups].map(([key, group]) => <section className="history-date-group" key={key} aria-label={dateLabel(group[0]!.at)}>
        <h3>{dateLabel(group[0]!.at)}</h3>
        <ol>{group.map((event) => {
          const { record, previous, action, kind } = event;
          const expense = kind === "expense" ? record as Expense : null;
          const payment = kind === "settlement" ? record as Settlement : null;
          const actor = actorName(event.actor);
          const title = expense ? `${expense.description} ${action === "added" ? "added" : action === "edited" ? "edited" : "removed"}` : action === "added" ? `${name(payment!.from_member_id, payment!.from_display_name)} settled with ${name(payment!.to_member_id, payment!.to_display_name)}` : action === "edited" ? "Settlement corrected" : "Settlement removed";
          const activePayment = payment && action !== "removed" && record.status === "active";
          return <li key={`${kind}-${record.id}-${action}`}>
            <article className="history-event" id={activePayment ? `payment-${record.id}` : `history-${kind}-${record.id}-${action}`}>
              <div className="history-event-topline"><h4>{title}</h4><strong className="history-amount">{previous && previous.amount !== record.amount ? <>{money(previous.amount)} <span aria-label="changed to">→</span> {money(record.amount)}</> : money(record.amount)}</strong></div>
              <p className="history-context muted">{expense ? <>{name(expense.payer_member_id)} paid · {expense.splits.length} {expense.splits.length === 1 ? "tripmate" : "tripmates"}</> : <>{name(payment!.from_member_id, payment!.from_display_name)} <span aria-label="to">→</span> {name(payment!.to_member_id, payment!.to_display_name)}</>}</p>
              {previous && expense && (previous as Expense).description !== expense.description ? <p className="history-change">Description: {(previous as Expense).description} → {expense.description}</p> : null}
              {previous && expense && (previous as Expense).payer_member_id !== expense.payer_member_id ? <p className="history-change">Paid by: {name((previous as Expense).payer_member_id)} → {name(expense.payer_member_id)}</p> : null}
              {previous && expense && ((previous as Expense).split_strategy !== expense.split_strategy || JSON.stringify((previous as Expense).splits.slice().sort((a, b) => a.member_id.localeCompare(b.member_id))) !== JSON.stringify(expense.splits.slice().sort((a, b) => a.member_id.localeCompare(b.member_id)))) ? <p className="history-change">Split allocations changed</p> : null}
              {previous && payment && ((previous as Settlement).from_member_id !== payment.from_member_id || (previous as Settlement).to_member_id !== payment.to_member_id) ? <p className="history-change">Transfer participants changed</p> : null}
              <p className="history-event-meta muted">{actor ? <span>{action === "edited" ? "Edited" : action === "removed" ? "Removed" : "Recorded"} by {actor}</span> : null}<time dateTime={event.at}>{new Date(event.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</time></p>
              <details className="history-details"><summary>Details<span className="sr-only"> for {title}</span></summary>
                <div className="history-detail-body">
                  <p>{expense ? "Expense occurred" : "External transfer occurred"} <time dateTime={record.occurred_at}>{new Date(record.occurred_at).toLocaleString()}</time></p>
                  {expense ? <><p>{expense.split_strategy === "equal" ? "Equal split" : "Exact split"}</p><ul className="history-allocations">{expense.splits.map((split) => <li key={split.member_id}><span>{name(split.member_id)}</span><strong>{money(split.amount)}</strong></li>)}</ul></> : <p>TripTab records the settlement; it does not transfer money.</p>}
                  {action === "edited" ? <><p>Correction of an earlier {kind}.</p>{previous?.void_reason ? <p>Reason: {previous.void_reason}</p> : null}</> : null}
                  {action === "removed" && record.void_reason?.trim() ? <p>Note: {record.void_reason}</p> : null}
                  {action !== "removed" && record.status === "voided" ? <p>This version is preserved in history and excluded from current balances.</p> : null}
                  {activePayment && (owner || record.created_by_user_id === user?.id) ? editing === record.id ? <div role="group" aria-label="Edit payment"><PaymentForm tripId={tripId} travelers={travelers} initialPayment={payment} onCancel={() => setEditing(null)} onRecorded={async () => { await onChanged(); setEditing(null); }} /></div> : <FinancialActions tripId={tripId} record={record} kind="payment" onChanged={onChanged} onEdit={() => setEditing(record.id)} correction={() => null} /> : null}
                </div>
              </details>
            </article>
          </li>;
        })}</ol>
      </section>)}
    </div>}
  </section>;
}
