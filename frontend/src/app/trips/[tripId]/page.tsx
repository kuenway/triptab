"use client";

import { useParams } from "next/navigation";

import { RequireAuth } from "../../../components/auth";

import { TripDashboard } from "../../../components/trip-dashboard";

export default function TripPage() {
  const { tripId } = useParams<{ tripId: string }>();
  return <RequireAuth><TripDashboard tripId={tripId} /></RequireAuth>;
}
