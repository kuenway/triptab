"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { AccountMenu, RequireAuth } from "../components/auth";

import { api, Trip } from "../lib/api";

export default function Home() {
  return <RequireAuth><TripList /></RequireAuth>;
}

function TripList() {
  const router = useRouter();
  const [trips, setTrips] = useState<Trip[]>([]);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [formError, setFormError] = useState("");

  useEffect(() => {
    api.listTrips()
      .then(setTrips)
      .catch((cause: Error) => setLoadError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  async function createTrip(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return setFormError("Enter a trip name.");
    setSaving(true);
    setFormError("");
    try {
      const trip = await api.createTrip(name.trim());
      router.push(`/trips/${trip.id}`);
    } catch (cause) {
      setFormError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="shell">
      <header className="site-header">
        <Link href="/" className="wordmark">TripTab<span className="brand-dot">.</span></Link>
        <AccountMenu />
      </header>

      <div className="page-intro">
        <p className="eyebrow">YOUR TRIPS</p>
        <h1>Every trip has a tab.</h1>
        <p>Keep shared expenses and balances in one simple place.</p>
      </div>

      <div className="home-grid">
        <section className="panel" aria-labelledby="trips-heading">
          <div className="section-heading">
            <h2 id="trips-heading">Trips</h2>
            <span className="count">{trips.length}</span>
          </div>
          {loading ? <p className="muted" role="status">Loading trips…</p> : null}
          {!loading && loadError ? <p className="alert" role="alert">{loadError}</p> : null}
          {!loading && !loadError && trips.length === 0 ? (
            <div className="empty-state">
              <span className="empty-icon" aria-hidden="true">✦</span>
              <h3>No trips yet</h3>
              <p>Create your first trip to start tracking shared expenses.</p>
            </div>
          ) : null}
          <div className="trip-list">
            {trips.map((trip) => (
              <Link className="trip-row" href={`/trips/${trip.id}`} key={trip.id}>
                <span className="trip-avatar" aria-hidden="true">{trip.name.charAt(0).toUpperCase()}</span>
                <span className="trip-row-main"><strong>{trip.name}</strong><small>TWD · Shared trip</small></span>
                <span className="trip-arrow" aria-hidden="true">→</span>
              </Link>
            ))}
          </div>
        </section>

        <section className="panel create-panel" aria-labelledby="create-heading">
          <p className="eyebrow">START SOMETHING NEW</p>
          <h2 id="create-heading">Create a trip</h2>
          <p className="muted">Going somewhere together? Give your trip a name.</p>
          <form onSubmit={createTrip} className="stack-form">
            <label htmlFor="trip-name">Trip name</label>
            <input id="trip-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Tokyo Weekend" required />
            {formError ? <p className="alert" role="alert">{formError}</p> : null}
            <button type="submit" disabled={saving}>{saving ? "Creating…" : "Create trip"}</button>
          </form>
          <p className="form-note">All amounts are in New Taiwan dollars (NT$).</p>
        </section>
      </div>
      <p className="dev-note">Private trips · Shared with your trip members</p>
    </main>
  );
}
