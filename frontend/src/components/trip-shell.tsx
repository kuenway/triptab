"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

import { api, ApiError, Balances, Expense, Settlement, SettlementSuggestions, Traveler, Trip } from "../lib/api";
import { AccountMenu } from "./auth";

type TripData = {
  trip: Trip;
  travelers: Traveler[];
  expenses: Expense[];
  balances: Balances | null;
  suggestions: SettlementSuggestions | null;
  suggestionsError: string;
  payments: Settlement[] | null;
  paymentsError: string;
  load: () => Promise<void>;
};

const TripContext = createContext<TripData | null>(null);

export function useTrip() {
  const data = useContext(TripContext);
  if (!data) throw new Error("TripShell is required");
  return data;
}

const destinations = [
  { name: "Expenses", path: "", icon: "M6 3h12v18l-3-2-3 2-3-2-3 2V3Zm3 5h6M9 12h6" },
  { name: "Balances", path: "/balances", icon: "M12 3v18M5 21h14M4 7h16M6 7l-3 7h6L6 7Zm12 0-3 7h6l-3-7Z" },
  { name: "Travelers", path: "/travelers", icon: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M22 21v-2a4 4 0 0 0-3-3.87M15 3.13a4 4 0 0 1 0 7.75M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z" },
  { name: "History", path: "/history", icon: "M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7M12 7v5l3 2" },
];

export function TripShell({ tripId, children }: { tripId: string; children: ReactNode }) {
  const pathname = usePathname();
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

  if (loading) return <main className="shell trip-shell"><p role="status">Loading trip…</p></main>;
  if (notFound) return <main className="shell trip-shell"><h1>We couldn’t find that trip.</h1><Link href="/">← Back to trips</Link></main>;
  if (!trip) return <main className="shell trip-shell"><p className="alert" role="alert">{error || "Could not load this trip."}</p><button onClick={() => void load()}>Try again</button><p><Link href="/">← Back to trips</Link></p></main>;

  const base = `/trips/${tripId}`;
  return <TripContext.Provider value={{ trip, travelers, expenses, balances, suggestions, suggestionsError, payments, paymentsError, load }}>
    <main className="shell trip-shell">
      <header className="site-header"><Link href="/" className="wordmark">TripTab<span className="brand-dot">.</span></Link><AccountMenu /></header>
      <div className="trip-heading"><Link className="back-link" href="/">← All trips</Link><h1>{trip.name}</h1><p className="muted">{travelers.length} {travelers.length === 1 ? "traveler" : "travelers"} · TWD</p></div>
      <nav className="trip-navigation" aria-label="Trip sections">
        {destinations.map(({ name, path, icon }) => <Link key={name} href={base + path} aria-current={pathname === base + path ? "page" : undefined}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={icon} /></svg>
          <span>{name}</span>
        </Link>)}
      </nav>
      {error ? <p className="alert" role="alert">{error}</p> : null}
      {children}
      <p className="dev-note">Private trip · Financial history is preserved</p>
    </main>
  </TripContext.Provider>;
}
