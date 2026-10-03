"use client";

import { useParams } from "next/navigation";

import { TripDashboard } from "../../../components/trip-dashboard";

export default function TripPage() {
  const { tripId } = useParams<{ tripId: string }>();
  return <TripDashboard tripId={tripId} />;
}
