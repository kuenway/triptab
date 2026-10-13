"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AccountMenu, RequireAuth } from "../components/auth";
import { LoadingState } from "../components/loading-state";
import { NewTripDialog } from "../components/new-trip-dialog";
import { api, Trip } from "../lib/api";

export default function Home() {
  return <RequireAuth><TripList /></RequireAuth>;
}

function TripList() {
  const router = useRouter();
  const [trips, setTrips] = useState<Trip[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setTrips(await api.listTrips()); }
    catch { setError("Could not load your trips. Please retry."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  return <main className="shell trips-home">
    <header className="site-header"><Link href="/" className="wordmark">TripTab<span className="brand-dot">.</span></Link><AccountMenu /></header>
    <section className="trips-workspace" aria-labelledby="trips-heading">
      <h1 id="trips-heading">Your trips</h1>
      {loading ? <LoadingState variant="trips" /> : error ? <div className="trips-state"><p role="alert" className="alert">{error}</p><button className="payment-button" onClick={() => void load()}>Retry trips</button></div> : trips.length === 0 ? <div className="trips-state"><h2>No trips yet.</h2><p className="muted">Create your first trip to start sharing expenses.</p></div> : <ul className="trip-list" aria-label="Your trips">
        {trips.map((trip) => <li key={trip.id}><Link className="trip-row" href={`/trips/${trip.id}`}>
          <span className="trip-row-main"><strong>{trip.name}</strong></span>
          <svg className="trip-arrow" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg>
        </Link></li>)}
      </ul>}
      <button className="new-trip-trigger" onClick={() => setCreating(true)}>+ New trip</button>
    </section>
    {creating ? <NewTripDialog onClose={() => setCreating(false)} onCreated={(trip) => router.push(`/trips/${trip.id}`)} onCheckTrips={() => { setCreating(false); void load(); }} /> : null}
  </main>;
}
