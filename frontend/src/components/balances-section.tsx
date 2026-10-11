"use client";

import Link from "next/link";
import { Balances } from "../lib/api";
import { useAuth } from "./auth";
import { SuggestedPayments } from "./payments";
import { useTrip } from "./trip-shell";

const money = (amount: number) => `NT$${new Intl.NumberFormat("en-US").format(amount)}`;

export function BalanceList({ balances, currentMemberId }: { balances: Balances; currentMemberId?: string }) {
  return <div className="balance-list net-balance-list">
    {balances.balances.length === 0 ? <p className="muted">Traveler balances are unavailable.</p> : null}
    {balances.balances.map((balance) => <div className="balance-row" key={balance.member_id}>
      <span className="person-name">{balance.member_id === currentMemberId ? "You" : balance.display_name}</span>
      <span className={`balance-value ${balance.amount > 0 ? "positive" : balance.amount < 0 ? "negative" : "even"}`}>
        {balance.amount > 0 ? `Is owed ${money(balance.amount)}` : balance.amount < 0 ? `Owes ${money(-balance.amount)}` : "Settled"}
      </span>
    </div>)}
  </div>;
}

export function BalancesSection() {
  const { user } = useAuth();
  const { trip, travelers, balances, suggestions, suggestionsError, dataError, load } = useTrip();
  const member = travelers.find((traveler) => traveler.user_id === user?.id);
  const personal = !dataError ? balances?.balances.find((balance) => balance.member_id === member?.id) : undefined;
  const settled = !dataError && !suggestionsError && balances && balances.balances.length > 0 && balances.balances.every((balance) => balance.amount === 0) && suggestions?.suggestions.length === 0;
  return <div className="trip-section balance-workspace">
    <section className="balance-overview" aria-labelledby="balances-heading">
      <h2 id="balances-heading">Balances</h2>
      <div className="balance-personal"><h3>Your balance</h3>
        {personal ? <><p>{personal.amount > 0 ? "You are owed" : personal.amount < 0 ? "You owe" : "You're settled up"}</p>{personal.amount !== 0 ? <strong>{money(Math.abs(personal.amount))}</strong> : null}</> : <p className="muted">{dataError ? "Balances could not be refreshed. Retry before confirming a transfer." : balances ? "Your balance could not be resolved." : "Loading balances…"}</p>}
      </div>
      {settled ? <p className="settlement-status" role="status">Everyone is settled up.</p> : null}
      <h3>Traveler balances</h3>
      <p className="muted balance-caption">Each traveler&apos;s net position in this Trip.</p>
      {!dataError && balances ? <BalanceList balances={balances} {...(member ? { currentMemberId: member.id } : {})} /> : null}
    </section>
    <section className="suggested-transfers" aria-labelledby="transfers-heading">
      <h2 id="transfers-heading">Suggested transfers</h2>
      <p className="muted balance-caption">Transfer using your preferred payment method. Mark settled only after the money has been transferred outside TripTab.</p>
      {dataError ? <p className="muted">Refresh Trip data before confirming a transfer.</p> : suggestionsError ? <div><p className="alert" role="alert">{suggestionsError}</p><button className="payment-button" onClick={() => void load()}>Retry suggestions</button></div> : !suggestions ? <p className="muted" role="status">Loading suggested transfers…</p> : null}
      <SuggestedPayments tripId={trip.id} travelers={travelers} suggestions={suggestions} unavailable={Boolean(dataError || suggestionsError)} onRecorded={load} />
      <Link className="settlement-history-link" href={`/trips/${trip.id}/history`}>View settlement history</Link>
    </section>
  </div>;
}
