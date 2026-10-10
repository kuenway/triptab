"""Guest removal preserves financial identities and retained invitation audit."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_invitations import committed_invitation as committed_invitation
from test_invitations import invitation_logs as invitation_logs
from test_invitations import invited as invited

from app.application.invitations import InvitationService
from app.application.service import (
    MemberRemovalConflict,
    ResourceNotFound,
    TripTabService,
)
from app.persistence.models import GroupMemberRow, TripInvitationRow
from app.persistence.repository import LedgerRepository

pytestmark = pytest.mark.integration
WHEN = "2026-10-11T12:00:00Z"


def path(t, member=None):
    return t["base"] + "/members/" + (member or t["guest"])["id"]


def snapshot(session):
    tables = [
        "expenses",
        "expense_splits",
        "settlements",
        "expense_voids",
        "settlement_voids",
    ]
    return {
        table: sorted(session.execute(text(f"SELECT * FROM {table}")).all(), key=repr)
        for table in tables
    }


def test_remove_unused_guest_revokes_and_detaches_all_audit(
    invited, db_session, raw_client, invitation_logs
):
    caplog = invitation_logs
    t = invited
    first = t["invitation"]
    second = t["owner"].post(path(t) + "/invitations").json()
    response = t["owner"].delete(path(t))
    assert response.status_code == 204 and response.content == b""
    assert response.headers["Cache-Control"] == "no-store"
    assert all(
        m["id"] != t["guest"]["id"]
        for m in t["owner"].get(t["base"] + "/members").json()
    )
    listing = t["owner"].get(t["base"] + "/invitations").json()
    assert len(listing) == 2
    for row in listing:
        assert row["target_member_id"] is None
        assert row["target_member_snapshot_id"] == t["guest"]["id"]
        assert (
            row["status"] == "revoked" and row["revoked_by_user_id"] == t["alice"]["id"]
        )
        assert "token" not in row and "token_hash" not in row
    for row in [first, second]:
        for client, suffix in [(raw_client, "preview"), (t["bob"], "accept")]:
            result = client.post(
                "/api/v1/invitations/" + suffix, json={"token": row["token"]}
            )
            assert result.status_code == 404
            assert result.headers["Cache-Control"] == "no-store"
            assert row["token"] not in result.text and row["token"] not in caplog.text
            assert all(
                row["token"] not in repr(record.__dict__) for record in caplog.records
            )
        assert (
            t["owner"].post(t["base"] + f"/invitations/{row['id']}/revoke").status_code
            == 409
        )
    assert caplog.records
    assert t["owner"].delete(path(t)).status_code == 404
    db_session.expire_all()
    assert db_session.get(GroupMemberRow, UUID(t["guest"]["id"])) is None


def test_expired_invitation_is_revoked_before_detachment(invited, db_session):
    t = invited
    row = db_session.get(TripInvitationRow, UUID(t["invitation"]["id"]))
    row.created_at -= timedelta(days=8)
    row.expires_at -= timedelta(days=8)
    db_session.flush()
    assert t["owner"].delete(path(t)).status_code == 204
    assert t["owner"].get(t["base"] + "/invitations").json()[0]["status"] == "revoked"


@pytest.mark.parametrize(
    "history",
    [
        "payer",
        "split",
        "zero_split",
        "settlement_from",
        "settlement_to",
        "voided_expense",
        "corrected_expense",
        "voided_settlement",
    ],
)
def test_all_financial_history_blocks_removal_even_when_voided_or_zero(
    invited, db_session, history
):
    t = invited
    owner = t["owner_member"]["id"]
    guest = t["guest"]["id"]
    expense = dict(
        description="Immutable history",
        amount=100,
        payer_member_id=guest
        if history in {"payer", "voided_expense", "corrected_expense"}
        else owner,
        split_strategy="exact",
        occurred_at=WHEN,
        splits=[{"member_id": owner, "amount": 100}],
    )
    if history in {"split", "zero_split"}:
        expense["splits"] = [
            {"member_id": guest, "amount": 0 if history == "zero_split" else 100},
            {"member_id": owner, "amount": 100 if history == "zero_split" else 0},
        ]
    if "settlement" in history:
        record = t["owner"].post(
            t["base"] + "/settlements",
            json={
                "from_member_id": owner if history == "settlement_to" else guest,
                "to_member_id": guest if history == "settlement_to" else owner,
                "amount": 100,
                "occurred_at": WHEN,
            },
        )
        assert record.status_code == 201
        if history == "voided_settlement":
            assert (
                t["owner"]
                .post(
                    t["base"] + f"/settlements/{record.json()['id']}/void",
                    json={"reason": "Cancelled"},
                )
                .status_code
                == 200
            )
    else:
        record = t["owner"].post(t["base"] + "/expenses", json=expense)
        assert record.status_code == 201
        if history == "voided_expense":
            assert (
                t["owner"]
                .post(
                    t["base"] + f"/expenses/{record.json()['id']}/void",
                    json={"reason": "Cancelled"},
                )
                .status_code
                == 200
            )
        elif history == "corrected_expense":
            replacement = {**expense, "payer_member_id": owner}
            assert (
                t["owner"]
                .post(
                    t["base"] + f"/expenses/{record.json()['id']}/corrections",
                    json={"reason": "Wrong payer", "replacement": replacement},
                )
                .status_code
                == 201
            )
    before = snapshot(db_session)
    response = t["owner"].delete(path(t))
    assert (
        response.status_code == 409 and "financial history" in response.json()["detail"]
    )
    assert snapshot(db_session) == before
    assert t["owner"].get(t["base"] + "/invitations").json()[0]["status"] == "pending"


def test_owner_linked_member_and_idor_protection(invited, raw_client):
    t = invited
    assert raw_client.delete(path(t)).status_code == 401
    assert t["eve"].delete(path(t)).status_code == 404
    assert t["owner"].delete(path(t, t["owner_member"])).status_code == 409
    assert (
        t["bob"]
        .post("/api/v1/invitations/accept", json={"token": t["invitation"]["token"]})
        .status_code
        == 200
    )
    assert t["owner"].delete(path(t)).status_code == 409
    unused = (
        t["owner"].post(t["base"] + "/members", json={"display_name": "Unused"}).json()
    )
    assert t["bob"].delete(path(t, unused)).status_code == 403
    other = t["owner"].post("/api/v1/groups", json={"name": "Other"}).json()
    assert (
        t["owner"]
        .delete(f"/api/v1/groups/{other['id']}/members/{unused['id']}")
        .status_code
        == 404
    )
    assert (
        t["bob"]
        .delete(f"/api/v1/groups/{other['id']}/members/{unused['id']}")
        .status_code
        == 404
    )
    assert t["owner"].delete(t["base"] + "/members/" + str(uuid4())).status_code == 404


@pytest.mark.parametrize(
    "header,value",
    [
        ("X-CSRF-Token", ""),
        ("X-CSRF-Token", "wrong"),
        ("Origin", ""),
        ("Origin", "https://evil.example"),
    ],
)
def test_removal_requires_csrf_and_origin(invited, header, value):
    t = invited
    response = t["owner"].delete(path(t), headers={header: value})
    assert (
        response.status_code == 403 and response.headers["Cache-Control"] == "no-store"
    )
    assert any(
        m["id"] == t["guest"]["id"]
        for m in t["owner"].get(t["base"] + "/members").json()
    )


@pytest.mark.parametrize("reference", ["payer", "split", "sender", "recipient"])
def test_fk_failure_rolls_back_revocation_detachment_and_deletion(
    invited, db_session, monkeypatch, reference
):
    t = invited
    if reference in {"payer", "split"}:
        response = t["owner"].post(
            t["base"] + "/expenses",
            json={
                "description": "Restrict defense",
                "amount": 10,
                "payer_member_id": t["guest"]["id"]
                if reference == "payer"
                else t["owner_member"]["id"],
                "split_strategy": "equal",
                "occurred_at": WHEN,
                "participant_member_ids": [t["guest"]["id"]]
                if reference == "split"
                else [t["owner_member"]["id"]],
            },
        )
    else:
        response = t["owner"].post(
            t["base"] + "/settlements",
            json={
                "from_member_id": t["guest"]["id"]
                if reference == "sender"
                else t["owner_member"]["id"],
                "to_member_id": t["owner_member"]["id"]
                if reference == "sender"
                else t["guest"]["id"],
                "amount": 10,
                "occurred_at": WHEN,
            },
        )
    assert response.status_code == 201
    # Simulate the eligibility read missing a concurrent financial insert. Native
    # RESTRICT constraints must protect the member and roll back invitation writes.
    monkeypatch.setattr(
        LedgerRepository, "has_member_financial_history", lambda *args: False
    )
    before = snapshot(db_session)
    assert t["owner"].delete(path(t)).status_code == 409
    assert snapshot(db_session) == before
    listing = t["owner"].get(t["base"] + "/invitations").json()[0]
    assert (
        listing["status"] == "pending"
        and listing["target_member_id"] == t["guest"]["id"]
    )


@pytest.mark.parametrize(
    "violation",
    ["pending_detach", "accepted_detach", "snapshot_change", "wrong_live_target"],
)
def test_invitation_live_target_and_immutable_snapshot_constraints(
    invited, db_session, violation
):
    t = invited
    row = db_session.get(TripInvitationRow, UUID(t["invitation"]["id"]))
    with pytest.raises(IntegrityError), db_session.begin_nested():
        if violation == "snapshot_change":
            # Changing both UUIDs would satisfy all checks/FKs without the trigger.
            row.target_member_snapshot_id = UUID(t["owner_member"]["id"])
            row.target_member_id = UUID(t["owner_member"]["id"])
        elif violation == "wrong_live_target":
            row.target_member_id = UUID(t["owner_member"]["id"])
        else:
            row.target_member_id = None
            if violation == "accepted_detach":
                row.accepted_at = datetime.now(UTC)
                row.accepted_by_user_id = UUID(t["robert"]["id"])
        db_session.flush()


@pytest.mark.parametrize("winner", ["removal", "acceptance"])
def test_guest_removal_and_acceptance_race(
    pg_engine, committed_invitation, monkeypatch, winner
):
    users, group, guest, _, invitation, token, _, _ = committed_invitation
    locked, release, attempted = Event(), Event(), Event()
    history = LedgerRepository.has_member_financial_history
    lock_invitation = InvitationService._lock_invitation
    lock_member = InvitationService._member
    if winner == "removal":

        def pause_removal(repo, *args):
            result = history(repo, *args)
            locked.set()
            assert release.wait(10)
            return result

        monkeypatch.setattr(
            LedgerRepository, "has_member_financial_history", pause_removal
        )

        def acceptance_waiting(service, *args):
            attempted.set()
            return lock_member(service, *args)

        monkeypatch.setattr(InvitationService, "_member", acceptance_waiting)
    else:

        def pause_acceptance(service, row):
            result = lock_invitation(service, row)
            locked.set()
            assert release.wait(10)
            return result

        monkeypatch.setattr(InvitationService, "_lock_invitation", pause_acceptance)

    def remove():
        with Session(pg_engine) as s:
            if winner == "acceptance":
                attempted.set()
            try:
                TripTabService(s, users[0]).remove_guest_member(group.id, guest.id)
                return "removed"
            except MemberRemovalConflict:
                return "conflict"

    def claim():
        with Session(pg_engine) as s:
            try:
                return InvitationService(s, users[1]).accept(token).id
            except ResourceNotFound:
                return "unavailable"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(remove if winner == "removal" else claim)
        assert locked.wait(5)
        second = pool.submit(claim if winner == "removal" else remove)
        assert attempted.wait(5)
        release.set()
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert results == (
        ["removed", "unavailable"] if winner == "removal" else [guest.id, "conflict"]
    )
    with Session(pg_engine) as s:
        row = s.get(TripInvitationRow, invitation.id)
        assert row.target_member_snapshot_id == guest.id
        assert row.status == ("revoked" if winner == "removal" else "accepted")
        assert (s.get(GroupMemberRow, guest.id) is None) == (winner == "removal")


def test_unused_guest_without_invitations_is_removable(invited):
    t = invited
    unused = (
        t["owner"].post(t["base"] + "/members", json={"display_name": "Unused"}).json()
    )
    assert t["owner"].delete(path(t, unused)).status_code == 204
    assert len(t["owner"].get(t["base"] + "/invitations").json()) == 1
