import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { AuthForm, AuthProvider } from "../components/auth";
import { InvitationPage, TravelerInvitations } from "../components/invitations";
import { TripDashboard } from "../components/trip-dashboard";
import { api, ApiError, TripInvitation, Traveler } from "../lib/api";

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("../lib/api", async (original) => {
  const client = await original<typeof import("../lib/api")>();
  return { ...client, api: Object.fromEntries(Object.keys(client.api).map((key) => [key, vi.fn()])) };
});
const token = "a".repeat(43);
const user = { id: "bob-user", email: "bob@example.com", display_name: "Robert", created_at: "2026-10-11T12:00:00Z" };
const state = { user, csrf_token: "csrf-test" };
const travelers: Traveler[] = [
  { id: "alice", group_id: "trip", display_name: "Alice", role: "owner", user_id: "alice-user" },
  { id: "bob", group_id: "trip", display_name: "Bob", role: "member", user_id: null },
];
const invitation: TripInvitation = { id: "invitation", group_id: "trip", target_member_id: "bob", target_member_snapshot_id: "bob", created_by_user_id: "alice-user", created_at: "2026-10-11T12:00:00Z", expires_at: "2026-10-18T12:00:00Z", accepted_at: null, accepted_by_user_id: null, revoked_at: null, revoked_by_user_id: null, status: "pending" };
function page() { return render(<AuthProvider><InvitationPage /></AuthProvider>); }

beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState(null, "", "/invite#token=" + token);
  sessionStorage.clear(); localStorage.clear();
  vi.mocked(api.getMe).mockResolvedValue(state);
  vi.mocked(api.previewInvitation).mockResolvedValue({ trip_name: "Japan 2027", member_display_name: "Bob", expires_at: invitation.expires_at });
  vi.mocked(api.acceptInvitation).mockResolvedValue({ ...travelers[1], user_id: user.id });
  vi.mocked(api.listInvitations).mockResolvedValue([]);
});

it("creates a private copyable fragment link, closes it and never recovers old raw tokens", async () => {
  vi.mocked(api.createInvitation).mockResolvedValue({ ...invitation, token });
  vi.mocked(api.listInvitations).mockResolvedValueOnce([]).mockResolvedValue([invitation]);
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  render(<TravelerInvitations canManage={true} tripId="trip" travelers={travelers} />);
  expect(await screen.findByText("No invitation")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Invite to TripTab" }));
  const link = await screen.findByLabelText("Invitation link");
  expect(link).toHaveProperty("value", "http://localhost:3000/invite#token=" + token);
  fireEvent.click(screen.getByRole("button", { name: "Copy invite link" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("http://localhost:3000/invite#token=" + token));
  fireEvent.click(screen.getByRole("button", { name: "Close invite link" }));
  expect(screen.queryByLabelText("Invitation link")).toBeNull();
  expect(api.createInvitation).toHaveBeenCalledWith("trip", "bob");
  expect(sessionStorage.length).toBe(0); expect(localStorage.length).toBe(0);
});

it.each(["pending", "accepted", "revoked", "expired"] as const)("shows owner %s metadata without recovering a bearer link", async (status) => {
  vi.mocked(api.listInvitations).mockResolvedValue([{ ...invitation, status }]);
  render(<TravelerInvitations canManage={true} tripId="trip" travelers={status === "accepted" ? travelers.map((m) => m.id === "bob" ? { ...m, user_id: user.id } : m) : travelers} />);
  if (status === "accepted") { expect(screen.getByText("Member")).toBeTruthy(); expect(screen.queryByText("Accepted invitation")).toBeNull(); }
  else expect(await screen.findByText(`${status.charAt(0).toUpperCase()}${status.slice(1)} invitation`)).toBeTruthy();
  expect(screen.queryByLabelText("Invitation link")).toBeNull();
  if (status !== "pending") expect(screen.queryByRole("button", { name: "Revoke invitation" })).toBeNull();
});

it("revokes a pending invitation and leaves the guest identity intact", async () => {
  vi.mocked(api.listInvitations).mockResolvedValueOnce([invitation]).mockResolvedValue([{ ...invitation, status: "revoked" }]);
  vi.mocked(api.revokeInvitation).mockResolvedValue({ ...invitation, status: "revoked" });
  render(<TravelerInvitations canManage={true} tripId="trip" travelers={travelers} />);
  fireEvent.click(await screen.findByRole("button", { name: "Revoke invitation" }));
  expect(await screen.findByText("Revoked invitation")).toBeTruthy();
  expect(api.revokeInvitation).toHaveBeenCalledWith("trip", invitation.id);
  expect(travelers[1].user_id).toBeNull();
});

it("shows creation, listing and clipboard errors safely", async () => {
  vi.mocked(api.listInvitations).mockRejectedValueOnce(new ApiError("Unavailable", 0)).mockResolvedValue([]);
  vi.mocked(api.createInvitation).mockRejectedValueOnce(new ApiError("traveler is already account-linked",409)).mockResolvedValue({ ...invitation,token });
  Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:vi.fn().mockRejectedValue(new Error("Denied"))}});
  render(<TravelerInvitations canManage={true} tripId="trip" travelers={travelers} />);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent","Could not load invitations. Try refreshing the trip.");
  fireEvent.click(screen.getByRole("button",{name:"Invite to TripTab"}));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent","traveler is already account-linked");
  fireEvent.click(screen.getByRole("button",{name:"Invite to TripTab"}));
  fireEvent.click(await screen.findByRole("button",{name:"Copy invite link"}));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent","Could not copy. Select and copy the invitation link above.");
});

it("previews minimal information and requires explicit acceptance", async () => {
  page();
  expect(await screen.findByRole("heading", { name: "Join Japan 2027" })).toBeTruthy();
  expect(screen.getByText("You've been invited to join as Bob.")).toBeTruthy();
  expect(api.acceptInvitation).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "Join as Bob" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/trips/trip"));
  expect(api.acceptInvitation).toHaveBeenCalledWith(token);
  expect(window.location.hash).toBe("");
  expect(sessionStorage.length).toBe(0); expect(localStorage.length).toBe(0);
});

it("offers login and registration with fragment-only continuation", async () => {
  vi.mocked(api.getMe).mockRejectedValue(new ApiError("sign in required",401));
  page();
  expect(await screen.findByRole("link",{name:"Log in to join"})).toHaveProperty("href","http://localhost:3000/login#token="+token);
  expect(screen.getByRole("link",{name:"Create account to join"})).toHaveProperty("href","http://localhost:3000/register#token="+token);
  expect(api.acceptInvitation).not.toHaveBeenCalled();
});

it.each(["login","register"] as const)("returns from %s to the invitation without automatically accepting", async (mode) => {
  window.history.replaceState(null,"","/"+mode+"#token="+token);
  vi.mocked(api.login).mockResolvedValue(state); vi.mocked(api.register).mockResolvedValue(state);
  render(<AuthProvider><AuthForm mode={mode} /></AuthProvider>);
  const submit=await screen.findByRole("button",{name:mode==="login"?"Log in":"Register"});
  await waitFor(()=>expect(submit.hasAttribute("disabled")).toBe(false));
  fireEvent.change(screen.getByLabelText("Email",{exact:true}),{target:{value:user.email}});
  fireEvent.change(screen.getByLabelText("Password",{exact:true}),{target:{value:"TripTab test password 123"}});
  if(mode==="register")fireEvent.change(screen.getByLabelText("Display name"),{target:{value:user.display_name}});
  expect(screen.getByRole("link",{name:mode==="login"?"Create an account":"Log in"})).toHaveProperty("href",`http://localhost:3000/${mode==="login"?"register":"login"}#token=${token}`);
  fireEvent.click(submit);
  await waitFor(()=>expect(replace).toHaveBeenCalledWith("/invite#token="+token));
  expect(api.acceptInvitation).not.toHaveBeenCalled();expect(window.location.hash).toBe("");
});

it.each(["expired","revoked","invalid"])("shows safe unavailable text for %s links", async () => {
  vi.mocked(api.previewInvitation).mockRejectedValue(new ApiError("invitation unavailable",404));
  page();expect(await screen.findByText("This invitation is no longer available.")).toBeTruthy();
  expect(screen.queryByRole("button",{name:"Join as Bob"})).toBeNull();
});

it("rejects missing or malformed fragments locally", async () => {
  window.history.replaceState(null,"","/invite?token=short");page();
  expect(await screen.findByText("This invitation is no longer available.")).toBeTruthy();
  expect(api.previewInvitation).not.toHaveBeenCalled();
});

it("preserves context on acceptance conflicts and uncertain responses for safe explicit retry", async () => {
  vi.mocked(api.acceptInvitation).mockRejectedValueOnce(new ApiError("Could not reach TripTab.",0)).mockResolvedValue({ ...travelers[1],user_id:user.id });
  page();fireEvent.click(await screen.findByRole("button",{name:"Join as Bob"}));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent","Could not reach TripTab.");
  expect(window.location.hash).toBe("#token="+token);expect(replace).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Join as Bob"}));
  await waitFor(()=>expect(replace).toHaveBeenCalledWith("/trips/trip"));
});

it("clears the token on explicit cancellation", async () => {
  page();await screen.findByRole("heading",{name:"Join Japan 2027"});
  fireEvent.click(screen.getByRole("button",{name:"Cancel invitation"}));
  expect(window.location.hash).toBe("");expect(replace).toHaveBeenCalledWith("/");
});

it("ignores stale preview responses after switching invitation fragments", async () => {
  let resolve!: (preview: {trip_name:string;member_display_name:string;expires_at:string})=>void;
  vi.mocked(api.previewInvitation).mockReturnValueOnce(new Promise((done)=>{resolve=done;})).mockResolvedValue({trip_name:"Other trip",member_display_name:"Charlie",expires_at:invitation.expires_at});
  page();await waitFor(()=>expect(api.previewInvitation).toHaveBeenCalledWith(token));
  window.history.replaceState(null,"","/invite#token="+"b".repeat(43));fireEvent(window,new Event("hashchange"));
  expect(await screen.findByRole("heading",{name:"Join Other trip"})).toBeTruthy();
  resolve({trip_name:"Japan 2027",member_display_name:"Bob",expires_at:invitation.expires_at});
  await waitFor(()=>expect(screen.queryByRole("button",{name:"Join as Bob"})).toBeNull());
  fireEvent.click(screen.getByRole("button",{name:"Join as Charlie"}));
  await waitFor(()=>expect(api.acceptInvitation).toHaveBeenCalledWith("b".repeat(43)));
});

it.each(["owner","member"] as const)("shows invitation management only to %s where authorized and updates Guest to Member", async (role) => {
  vi.mocked(api.getMe).mockResolvedValue({ ...state,user:{...user,id:role==="owner"?"alice-user":"bob-user"} });
  vi.mocked(api.getTrip).mockResolvedValue({id:"trip",name:"Japan 2027",currency:"TWD",currency_scale:0});
  vi.mocked(api.listTravelers).mockResolvedValue(role==="owner"?travelers:travelers.map((m)=>m.id==="bob"?{...m,user_id:user.id}:m));
  vi.mocked(api.listExpenses).mockResolvedValue([]);vi.mocked(api.getBalances).mockResolvedValue({group_id:"trip",currency:"TWD",balances:[]});
  vi.mocked(api.listSettlements).mockResolvedValue([]);vi.mocked(api.getSettlementSuggestions).mockResolvedValue({group_id:"trip",currency:"TWD",suggestions:[]});
  render(<AuthProvider><TripDashboard tripId="trip" /></AuthProvider>);
  const region=within(await screen.findByRole("region",{name:"Travelers"}));
  await waitFor(()=>expect(region.queryByRole("button",{name:"Invite to TripTab"})!==null).toBe(role==="owner"));
  expect(region.getByText(role==="owner"?"Guest":"Member")).toBeTruthy();
  if(role==="member")expect(api.listInvitations).not.toHaveBeenCalled();
});

it("shows an identity conflict without clearing the pending invitation or navigating", async () => {
  vi.mocked(api.acceptInvitation).mockRejectedValue(new ApiError("account already has a traveler in this trip",409));
  page();fireEvent.click(await screen.findByRole("button",{name:"Join as Bob"}));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent","account already has a traveler in this trip");
  expect(window.location.hash).toBe("#token="+token);expect(replace).not.toHaveBeenCalled();
});

it("keeps one traveler row, with owner-only Guest actions and no accepted invitation noise", async () => {
  vi.mocked(api.listInvitations).mockResolvedValue([invitation]);
  const view = render(<TravelerInvitations canManage={true} tripId="trip" travelers={travelers} />);
  const row = within(screen.getByRole("group", { name: "Invitation for Bob" }));
  expect(await row.findByText("Pending invitation")).toBeTruthy();
  expect(screen.getAllByText("Bob")).toHaveLength(1);
  expect(row.getByText("Guest")).toBeTruthy();
  expect(row.getByRole("button", { name: "Remove traveler" })).toBeTruthy();
  const owner = within(screen.getByRole("group", { name: "Invitation for Alice" }));
  expect(owner.queryByRole("button")).toBeNull();
  view.rerender(<TravelerInvitations canManage={true} tripId="trip" travelers={travelers.map((m) => m.id === "bob" ? { ...m, user_id: user.id } : m)} />);
  expect(row.getByText("Member")).toBeTruthy();
  expect(row.queryByRole("button")).toBeNull();
  expect(row.queryByText(/invitation/i)).toBeNull();
});

it("hides invitation/removal management from normal Members", () => {
  render(<TravelerInvitations canManage={false} tripId="trip" travelers={travelers} />);
  expect(screen.queryByRole("button")).toBeNull();
  expect(api.listInvitations).not.toHaveBeenCalled();
});

it("requires confirmation, can cancel and refreshes after removing an unused Guest", async () => {
  vi.mocked(api.removeTraveler).mockResolvedValue(undefined);
  const changed = vi.fn().mockResolvedValue(undefined);
  render(<TravelerInvitations canManage={true} tripId="trip" travelers={travelers} onChanged={changed} />);
  fireEvent.click(screen.getByRole("button", { name: "Remove traveler" }));
  expect(api.removeTraveler).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel removal" }));
  expect(screen.queryByRole("button", { name: "Confirm removal" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Remove traveler" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(api.removeTraveler).toHaveBeenCalledWith("trip", "bob");
  expect(screen.queryByRole("button", { name: "Confirm removal" })).toBeNull();
});

it("shows financial-history rejection without removing the traveler or invitation", async () => {
  vi.mocked(api.listInvitations).mockResolvedValue([invitation]);
  vi.mocked(api.removeTraveler).mockRejectedValue(new ApiError("This traveler has financial history and cannot be removed.", 409));
  const changed = vi.fn();
  render(<TravelerInvitations canManage={true} tripId="trip" travelers={travelers} onChanged={changed} />);
  await screen.findByText("Pending invitation");
  fireEvent.click(screen.getByRole("button", { name: "Remove traveler" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "This traveler has financial history and cannot be removed.");
  expect(screen.getByText("Bob")).toBeTruthy();
  expect(screen.getByText("Pending invitation")).toBeTruthy();
  expect(changed).not.toHaveBeenCalled();
});
