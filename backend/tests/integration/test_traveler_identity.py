"""Name uniqueness never replaces GroupMember UUID financial identity."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_invitations import committed_invitation as committed_invitation
from test_invitations import invitation_logs as invitation_logs
from test_invitations import invited as invited

from app.application.service import MemberNameConflict, TripTabService
from app.domain import GroupMember
from app.domain.names import canonical_traveler_name
from app.persistence.models import GroupMemberRow
from app.persistence.repository import LedgerRepository

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("name", ["Bob", "BOB", "bob", " Bob ", "Bob ", "\tBob\n"])
def test_canonical_duplicate_rejected_without_new_member(invited, name):
    t = invited
    before = t["owner"].get(t["base"] + "/members").json()
    response = t["owner"].post(t["base"] + "/members", json={"display_name": name})
    assert response.status_code == 409
    assert response.json() == {
        "detail": f'A traveler named "{name.strip()}" already exists in this trip.'
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert t["owner"].get(t["base"] + "/members").json() == before


def test_owner_name_reserved_and_same_name_in_another_trip_valid(invited):
    t = invited
    assert (
        t["owner"].post(t["base"] + "/members", json={"display_name": " alice "})
    ).status_code == 409
    other = t["owner"].post("/api/v1/groups", json={"name": "Other trip"}).json()
    response = t["owner"].post(
        f"/api/v1/groups/{other['id']}/members", json={"display_name": " Bob "}
    )
    assert response.status_code == 201
    assert response.json()["display_name"] == "Bob"
    assert (
        t["eve"].post(t["base"] + "/members", json={"display_name": "bob"})
    ).status_code == 404


def test_existing_same_names_preserve_uuid_removal_and_safe_diagnostics(
    invited, db_session, invitation_logs
):
    t = invited
    a_id = UUID(t["guest"]["id"])
    # Existing duplicates deliberately bypass the new creation validation.
    db_session.get(GroupMemberRow, a_id).display_name = "aaa"
    b = GroupMember(uuid4(), UUID(t["group"]["id"]), "aaa")
    LedgerRepository(db_session).save_member(b)
    owner_id = t["owner_member"]["id"]
    record = t["owner"].post(
        t["base"] + "/expenses",
        json={
            "description": "Private financial detail",
            "amount": 100,
            "payer_member_id": str(a_id),
            "split_strategy": "exact",
            "occurred_at": "2026-10-11T12:00:00Z",
            "splits": [
                {"member_id": str(a_id), "amount": 50},
                {"member_id": owner_id, "amount": 50},
            ],
        },
    )
    assert record.status_code == 201
    assert (
        t["owner"]
        .post(
            t["base"] + "/settlements",
            json={
                "from_member_id": str(a_id),
                "to_member_id": owner_id,
                "amount": 10,
                "occurred_at": "2026-10-11T12:00:00Z",
            },
        )
        .status_code
        == 201
    )
    repo = LedgerRepository(db_session)
    assert repo.has_member_financial_history(b.group_id, a_id)
    assert not repo.has_member_financial_history(b.group_id, b.id)
    before = t["owner"].get(t["base"] + "/expenses").json()
    assert t["owner"].delete(t["base"] + f"/members/{a_id}").status_code == 409
    assert t["owner"].delete(t["base"] + f"/members/{b.id}").status_code == 204
    assert t["owner"].get(t["base"] + "/expenses").json() == before
    remaining = t["owner"].get(t["base"] + "/members").json()
    assert any(m["id"] == str(a_id) for m in remaining)
    assert not any(m["id"] == str(b.id) for m in remaining)
    rejected = [
        r.fields
        for r in invitation_logs.records
        if getattr(r, "fields", {}).get("removal_rejection_reason")
    ]
    assert len(rejected) == 1
    assert rejected[0]["member_id"] == str(a_id)
    assert rejected[0]["group_id"] == t["group"]["id"]
    assert rejected[0]["removal_rejection_reason"] == "financial_reference"
    assert rejected[0]["request_id"]
    assert all(
        secret not in rejected[0].values()
        for secret in ["aaa", "Private financial detail", t["invitation"]["token"]]
    )


def test_concurrent_canonical_duplicate_creations(pg_engine, committed_invitation):
    users, group, *_ = committed_invitation
    started = Barrier(2)

    def create(name):
        with Session(pg_engine) as session:
            started.wait(timeout=5)
            try:
                return (
                    TripTabService(session, users[0])
                    .create_guest_member(group.id, name)
                    .id
                )
            except MemberNameConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create, name) for name in [" Race Guest ", "RACE GUEST"]]
        results = [future.result(timeout=10) for future in futures]
    assert results.count("conflict") == 1
    with Session(pg_engine) as session:
        names = session.scalars(
            select(GroupMemberRow.display_name).where(
                GroupMemberRow.group_id == group.id
            )
        ).all()
        assert sum(canonical_traveler_name(name) == "race guest" for name in names) == 1
