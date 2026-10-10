"""Invitation lifecycle, account claiming, immutable identity and PostgreSQL races."""

import base64
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.invitations import InvitationConflict, InvitationService
from app.application.service import ResourceNotFound
from app.domain import User
from app.persistence.models import GroupMemberRow, TripInvitationRow

pytestmark = pytest.mark.integration
PREFIX = "/api/v1"
WHEN = "2026-10-03T12:00:00Z"


@pytest.fixture
def invited(account_clients):
    owner, alice = account_clients("Alice")
    bob, robert = account_clients("Robert")
    eve, outsider = account_clients("Eve")
    group = owner.post(PREFIX + "/groups", json={"name": "Japan 2027"}).json()
    base = PREFIX + "/groups/" + group["id"]
    guest = owner.post(base + "/members", json={"display_name": "Bob"}).json()
    owner_member = next(
        m for m in owner.get(base + "/members").json() if m["role"] == "owner"
    )
    response = owner.post(base + f"/members/{guest['id']}/invitations")
    assert response.status_code == 201
    return dict(
        owner=owner,
        bob=bob,
        eve=eve,
        alice=alice,
        robert=robert,
        outsider=outsider,
        group=group,
        base=base,
        guest=guest,
        owner_member=owner_member,
        invitation=response.json(),
    )


def accept(t, client=None, token=None):
    return (client or t["bob"]).post(
        PREFIX + "/invitations/accept",
        json={"token": token or t["invitation"]["token"]},
    )


def preview(t, client, token=None):
    return client.post(
        PREFIX + "/invitations/preview",
        json={"token": token or t["invitation"]["token"]},
    )


def test_secure_creation_minimal_public_preview_and_listing(
    invited, raw_client, db_session, caplog
):
    t = invited
    invitation = t["invitation"]
    token = invitation["token"]
    assert len(base64.urlsafe_b64decode(token + "=")) == 32
    row = db_session.get(TripInvitationRow, UUID(invitation["id"]))
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in repr(row.__dict__) and row.status == "pending"
    assert row.expires_at - row.created_at == timedelta(days=7)
    assert row.created_by_user_id == UUID(t["alice"]["id"])
    result = preview(t, raw_client)
    assert result.status_code == 200
    assert set(result.json()) == {"trip_name", "member_display_name", "expires_at"}
    assert result.json()["trip_name"] == "Japan 2027"
    assert result.json()["member_display_name"] == "Bob"
    listing = t["owner"].get(t["base"] + "/invitations")
    assert listing.status_code == 200 and listing.json()[0]["status"] == "pending"
    assert "token" not in listing.json()[0] and "token_hash" not in listing.json()[0]
    assert token not in listing.text and token not in result.text
    for suffix in ["", "/members", "/expenses", "/balances", "/settlements"]:
        assert (
            raw_client.get(
                t["base"] + suffix, headers={"Authorization": "Bearer " + token}
            ).status_code
            == 401
        )
    assert accept(t, raw_client).status_code == 401
    assert (
        raw_client.post(
            PREFIX + "/invitations/preview", json={"token": "secret-short"}
        ).status_code
        == 422
    )
    assert (
        "secret-short"
        not in raw_client.post(
            PREFIX + "/invitations/preview", json={"token": "secret-short"}
        ).text
    )
    assert token not in caplog.text


def test_claim_preserves_all_financial_identity_history_and_enables_collaboration(
    invited,
):
    t = invited
    owner = t["owner"]
    base = t["base"]
    guest = t["guest"]
    om = t["owner_member"]
    charlie = owner.post(base + "/members", json={"display_name": "Charlie"}).json()
    dan = owner.post(base + "/members", json={"display_name": "Dan"}).json()
    expense = dict(
        description="Bob hotel",
        amount=900,
        payer_member_id=guest["id"],
        split_strategy="equal",
        participant_member_ids=[om["id"], guest["id"], charlie["id"]],
        occurred_at=WHEN,
    )
    original = owner.post(base + "/expenses", json=expense).json()
    assert (
        owner.post(
            base + f"/expenses/{original['id']}/corrections",
            json={"reason": "Receipt", "replacement": dict(expense, amount=990)},
        ).status_code
        == 201
    )
    payment = dict(
        from_member_id=guest["id"], to_member_id=om["id"], amount=100, occurred_at=WHEN
    )
    paid = owner.post(base + "/settlements", json=payment).json()
    assert (
        owner.post(
            base + f"/settlements/{paid['id']}/corrections",
            json={"reason": "Amount", "replacement": dict(payment, amount=90)},
        ).status_code
        == 201
    )
    paths = ["/expenses", "/settlements", "/balances", "/settlement-suggestions"]
    before = {p: owner.get(base + p).json() for p in paths}
    assert (
        next(
            b for b in before["/balances"]["balances"] if b["member_id"] == guest["id"]
        )["amount"]
        != 0
    )
    assert t["bob"].get(base).status_code == 404
    result = accept(t)
    assert result.status_code == 200
    linked = result.json()
    assert linked == dict(guest, user_id=t["robert"]["id"])
    assert linked["role"] == "member" and linked["display_name"] == "Bob"
    members = owner.get(base + "/members").json()
    assert len(members) == 4 and sum(m["id"] == guest["id"] for m in members) == 1
    assert {p: owner.get(base + p).json() for p in paths} == before
    assert {p: t["bob"].get(base + p).json() for p in paths} == before
    assert t["group"] in t["bob"].get(PREFIX + "/groups").json()
    new = t["bob"].post(
        base + "/expenses",
        json=dict(
            expense,
            payer_member_id=charlie["id"],
            description="Bob records Charlie's expense",
        ),
    )
    assert (
        new.status_code == 201 and new.json()["created_by_user_id"] == t["robert"]["id"]
    )
    assert new.json()["payer_member_id"] == charlie["id"]
    assert (
        t["bob"]
        .post(
            base + f"/expenses/{new.json()['id']}/void",
            json={"reason": "Own authored expense"},
        )
        .status_code
        == 200
    )
    assert (
        t["bob"]
        .post(base + f"/expenses/{original['id']}/void", json={"reason": "Not own"})
        .status_code
        == 403
    )
    assert t["bob"].post(base + "/settlements", json=payment).status_code == 201
    assert (
        t["bob"]
        .post(
            base + "/settlements",
            json=dict(payment, from_member_id=charlie["id"], to_member_id=dan["id"]),
        )
        .status_code
        == 403
    )
    assert next(m for m in members if m["id"] == charlie["id"])["user_id"] is None
    unrelated = owner.post(PREFIX + "/groups", json={"name": "Unrelated"}).json()
    assert t["bob"].get(PREFIX + "/groups/" + unrelated["id"]).status_code == 404


def test_creation_replaces_prior_unconsumed_invitations(invited, db_session):
    t = invited
    new = t["owner"].post(t["base"] + f"/members/{t['guest']['id']}/invitations")
    assert new.status_code == 201 and new.json()["token"] != t["invitation"]["token"]
    assert accept(t).status_code == 404
    assert preview(t, t["bob"]).status_code == 404
    old = t["owner"].get(t["base"] + "/invitations").json()[1]
    assert old["status"] == "revoked" and old["revoked_by_user_id"] == t["alice"]["id"]
    assert accept(t, token=new.json()["token"]).status_code == 200
    db_session.expire_all()
    assert db_session.get(TripInvitationRow, UUID(old["id"])).accepted_at is None


@pytest.mark.parametrize("state", ["expired", "revoked", "invalid", "claimed"])
def test_unavailable_preview_and_acceptance(invited, db_session, state):
    t = invited
    row = db_session.get(TripInvitationRow, UUID(t["invitation"]["id"]))
    token = t["invitation"]["token"]
    if state == "expired":
        row.created_at -= timedelta(days=8)
        row.expires_at -= timedelta(days=8)
        db_session.flush()
        assert (
            t["owner"].get(t["base"] + "/invitations").json()[0]["status"] == "expired"
        )
    elif state == "revoked":
        revoke = t["owner"].post(t["base"] + f"/invitations/{row.id}/revoke")
        assert revoke.status_code == 200 and revoke.json()["status"] == "revoked"
    elif state == "claimed":
        db_session.get(GroupMemberRow, UUID(t["guest"]["id"])).user_id = UUID(
            t["outsider"]["id"]
        )
        db_session.flush()
    else:
        token = "x" * 43
    assert preview(t, t["bob"], token).status_code == 404
    assert accept(t, token=token).status_code == (409 if state == "claimed" else 404)
    if state != "claimed":
        assert (
            next(
                m
                for m in t["owner"].get(t["base"] + "/members").json()
                if m["id"] == t["guest"]["id"]
            )["user_id"]
            is None
        )


def test_retry_original_user_and_conflict_other_user_or_revocation(invited, db_session):
    t = invited
    first = accept(t)
    assert first.status_code == 200
    again = accept(t)
    assert again.status_code == 200 and again.json() == first.json()
    assert accept(t, t["eve"]).status_code == 409
    assert preview(t, t["eve"]).status_code == 404
    assert (
        t["owner"]
        .post(t["base"] + f"/invitations/{t['invitation']['id']}/revoke")
        .status_code
        == 409
    )
    assert (
        t["owner"].get(t["base"] + "/invitations").json()[0]["accepted_by_user_id"]
        == t["robert"]["id"]
    )
    # Consumed-token retry stays safe after the former pending expiry.
    db_session.expire_all()
    row = db_session.get(TripInvitationRow, UUID(t["invitation"]["id"]))
    row.created_at -= timedelta(days=8)
    row.accepted_at -= timedelta(days=8)
    row.expires_at -= timedelta(days=8)
    db_session.flush()
    assert accept(t).status_code == 200


def test_owner_already_has_membership_and_linked_targets_cannot_be_invited(
    invited, db_session
):
    t = invited
    assert accept(t, t["owner"]).status_code == 409
    for member in [t["owner_member"], t["guest"]]:
        if member == t["guest"]:
            assert accept(t).status_code == 200
        assert (
            t["owner"]
            .post(t["base"] + f"/members/{member['id']}/invitations")
            .status_code
            == 409
        )
    assert db_session.get(
        TripInvitationRow, UUID(t["invitation"]["id"])
    ).accepted_by_user_id == UUID(t["robert"]["id"])


def test_existing_member_cannot_claim_second_guest(invited):
    t = invited
    assert accept(t).status_code == 200
    other = (
        t["owner"]
        .post(t["base"] + "/members", json={"display_name": "Other guest"})
        .json()
    )
    invitation = (
        t["owner"].post(t["base"] + f"/members/{other['id']}/invitations").json()
    )
    assert accept(t, token=invitation["token"]).status_code == 409
    members = t["owner"].get(t["base"] + "/members").json()
    assert sum(m["user_id"] == t["robert"]["id"] for m in members) == 1
    assert next(m for m in members if m["id"] == other["id"])["user_id"] is None
    assert accept(t, t["eve"], invitation["token"]).status_code == 200


def test_owner_member_outsider_and_nested_idor(invited):
    t = invited
    assert accept(t).status_code == 200
    other = (
        t["owner"].post(t["base"] + "/members", json={"display_name": "Charlie"}).json()
    )
    for client, status in [(t["bob"], 403), (t["eve"], 404)]:
        assert (
            client.post(t["base"] + f"/members/{other['id']}/invitations").status_code
            == status
        )
        assert client.get(t["base"] + "/invitations").status_code == status
        assert (
            client.post(
                t["base"] + f"/invitations/{t['invitation']['id']}/revoke"
            ).status_code
            == status
        )
    unrelated = t["owner"].post(PREFIX + "/groups", json={"name": "Other trip"}).json()
    otherbase = PREFIX + "/groups/" + unrelated["id"]
    assert (
        t["owner"]
        .post(otherbase + f"/invitations/{t['invitation']['id']}/revoke")
        .status_code
        == 404
    )
    assert (
        t["owner"].post(otherbase + f"/members/{other['id']}/invitations").status_code
        == 404
    )
    assert (
        t["bob"].post(otherbase + f"/members/{other['id']}/invitations").status_code
        == 404
    )
    assert (
        t["bob"]
        .post(otherbase + f"/invitations/{t['invitation']['id']}/revoke")
        .status_code
        == 404
    )


@pytest.mark.parametrize("operation", ["create", "accept", "revoke"])
@pytest.mark.parametrize(
    "header,value",
    [
        ("X-CSRF-Token", ""),
        ("X-CSRF-Token", "wrong"),
        ("Origin", "https://evil.example"),
        ("Origin", ""),
    ],
)
def test_invitation_mutations_require_csrf_and_origin(
    invited, operation, header, value
):
    t = invited
    path = {
        "create": t["base"] + f"/members/{t['guest']['id']}/invitations",
        "accept": PREFIX + "/invitations/accept",
        "revoke": t["base"] + f"/invitations/{t['invitation']['id']}/revoke",
    }[operation]
    client = t["bob"] if operation == "accept" else t["owner"]
    response = client.post(
        path,
        json={"token": t["invitation"]["token"]} if operation == "accept" else None,
        headers={header: value},
    )
    assert (
        response.status_code == 403 and response.headers["Cache-Control"] == "no-store"
    )
    assert t["invitation"]["token"] not in response.text


def test_management_requires_auth_and_rejects_supplied_actors(invited, raw_client):
    t = invited
    create = t["base"] + f"/members/{t['guest']['id']}/invitations"
    revoke = t["base"] + f"/invitations/{t['invitation']['id']}/revoke"
    assert raw_client.get(t["base"] + "/invitations").status_code == 401
    for path in [create, revoke]:
        assert raw_client.post(path).status_code == 401
        assert (
            t["owner"]
            .post(path, json={"created_by_user_id": t["outsider"]["id"]})
            .status_code
            == 422
        )


def test_other_trip_membership_does_not_prevent_claim(invited):
    t = invited
    own_trip = (
        t["bob"].post(PREFIX + "/groups", json={"name": "Bob's other trip"}).json()
    )
    assert accept(t).status_code == 200
    assert {g["id"] for g in t["bob"].get(PREFIX + "/groups").json()} == {
        own_trip["id"],
        t["group"]["id"],
    }


@pytest.fixture
def invitation_logs(caplog):
    logger = logging.getLogger("triptab")
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def test_no_store_secret_safe_errors_and_structured_logs(
    invited, raw_client, invitation_logs
):
    caplog = invitation_logs
    t = invited
    token = t["invitation"]["token"]
    responses = [
        preview(t, raw_client),
        t["owner"].get(t["base"] + "/invitations"),
        accept(t),
        accept(t, t["eve"]),
        raw_client.post(
            PREFIX + "/invitations/preview", json={"token": token, "extra": token}
        ),
        raw_client.post(
            PREFIX + "/invitations/preview", json={"token": "short-secret"}
        ),
    ]
    for response in responses:
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["CDN-Cache-Control"] == "no-store"
        assert response.headers["Vercel-CDN-Cache-Control"] == "no-store"
        assert token not in response.text and "short-secret" not in response.text
    assert preview(t, raw_client).status_code == 404
    assert (
        raw_client.post(
            PREFIX + "/invitations/preview",
            json={"token": token},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    guest = (
        t["owner"].post(t["base"] + "/members", json={"display_name": "Charlie"}).json()
    )
    created = t["owner"].post(t["base"] + f"/members/{guest['id']}/invitations")
    assert created.status_code == 201
    newly_created = created.json()
    assert (
        t["owner"]
        .post(t["base"] + f"/invitations/{newly_created['id']}/revoke")
        .status_code
        == 200
    )
    fields = [record.fields for record in caplog.records if hasattr(record, "fields")]
    assert fields, "The check must capture actual structured request records"
    assert token not in json.dumps(fields) and token not in caplog.text
    assert (
        newly_created["token"] not in json.dumps(fields)
        and newly_created["token"] not in caplog.text
    )
    assert all("token" not in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "violation",
    [
        "duplicate_hash",
        "cross_group",
        "accepted_without_actor",
        "revoked_without_actor",
        "both_terminal",
        "bad_hash",
        "invalid_actor",
        "invalid_accepting_actor",
        "invalid_revoking_actor",
        "accept_after_expiry",
        "invalid_expiry",
    ],
)
def test_postgresql_invitation_constraints(invited, db_session, violation):
    t = invited
    row = db_session.get(TripInvitationRow, UUID(t["invitation"]["id"]))
    values = {
        column.name: getattr(row, column.name)
        for column in TripInvitationRow.__table__.columns
    }
    values.update(id=uuid4(), token_hash=hashlib.sha256(uuid4().bytes).hexdigest())
    if violation == "duplicate_hash":
        values["token_hash"] = row.token_hash
    elif violation == "cross_group":
        other = t["owner"].post(PREFIX + "/groups", json={"name": "Other"}).json()
        values["group_id"] = UUID(other["id"])
    elif violation == "accepted_without_actor":
        values["accepted_at"] = datetime.now(UTC)
    elif violation == "revoked_without_actor":
        values["revoked_at"] = datetime.now(UTC)
    elif violation == "both_terminal":
        values.update(
            accepted_at=datetime.now(UTC),
            accepted_by_user_id=row.created_by_user_id,
            revoked_at=datetime.now(UTC),
            revoked_by_user_id=row.created_by_user_id,
        )
    elif violation == "bad_hash":
        values["token_hash"] = "not-a-digest"
    elif violation == "invalid_actor":
        values["created_by_user_id"] = uuid4()
    elif violation == "invalid_accepting_actor":
        values.update(accepted_at=datetime.now(UTC), accepted_by_user_id=uuid4())
    elif violation == "invalid_revoking_actor":
        values.update(revoked_at=datetime.now(UTC), revoked_by_user_id=uuid4())
    elif violation == "accept_after_expiry":
        values.update(
            accepted_at=row.expires_at, accepted_by_user_id=row.created_by_user_id
        )
    else:
        values["expires_at"] = row.created_at
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(TripInvitationRow(**values))
        db_session.flush()


def test_acceptance_rolls_back_association_when_metadata_write_fails(
    invited, db_session, monkeypatch
):
    t = invited
    actor = User(
        UUID(t["robert"]["id"]), t["robert"]["email"], t["robert"]["display_name"]
    )
    # Independent savepoint session, matching the application transaction boundary.
    with Session(
        bind=db_session.connection(),
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    ) as session:
        original_flush = session.flush

        def fail(objects=None):
            if any(
                isinstance(row, TripInvitationRow) and row.accepted_at is not None
                for row in session.dirty
            ):
                raise RuntimeError("simulated metadata flush failure")
            return original_flush(objects)

        monkeypatch.setattr(session, "flush", fail)
        with pytest.raises(RuntimeError, match="simulated metadata"):
            InvitationService(session, actor).accept(t["invitation"]["token"])
    db_session.expire_all()
    assert db_session.get(GroupMemberRow, UUID(t["guest"]["id"])).user_id is None
    assert (
        db_session.get(TripInvitationRow, UUID(t["invitation"]["id"])).accepted_at
        is None
    )


@pytest.fixture
def committed_invitation(pg_engine):
    """Real separate transactions for races, never the shared test savepoint."""
    from app.application.service import TripTabService
    from app.persistence.repository import LedgerRepository

    users = [
        User(uuid4(), f"race-{uuid4()}@example.com", name)
        for name in ["Owner", "Bob", "Eve"]
    ]
    with Session(pg_engine, expire_on_commit=False) as s:
        with s.begin():
            repo = LedgerRepository(s)
            for u in users:
                repo.save_user(u)
        trips = TripTabService(s, users[0])
        group = trips.create_group("Local race fixture")
        guest = trips.create_guest_member(group.id, "Guest")
        second = trips.create_guest_member(group.id, "Second guest")
        inv, token = InvitationService(s, users[0]).create(group.id, guest.id)
        inv2, token2 = InvitationService(s, users[0]).create(group.id, second.id)
    try:
        yield users, group, guest, second, inv, token, inv2, token2
    finally:
        with pg_engine.begin() as c:
            c.execute(
                text("DELETE FROM trip_invitations WHERE group_id=:id"),
                {"id": group.id},
            )
            c.execute(
                text("DELETE FROM group_members WHERE group_id=:id"), {"id": group.id}
            )
            c.execute(text("DELETE FROM groups WHERE id=:id"), {"id": group.id})
            for u in users:
                c.execute(text("DELETE FROM users WHERE id=:id"), {"id": u.id})


@pytest.mark.parametrize(
    "race",
    ["different_users_same_token", "same_user_same_token", "same_user_two_guests"],
)
def test_concurrent_acceptance_uses_real_postgresql_transactions(
    pg_engine, committed_invitation, race, monkeypatch
):
    users, group, guest, second, inv, token, inv2, token2 = committed_invitation
    barrier = Barrier(2)
    if race == "same_user_two_guests":
        from app.persistence.repository import LedgerRepository

        read_barrier = Barrier(2)
        membership = LedgerRepository.get_membership

        def simultaneous_unlinked_read(repo, group_id, user_id):
            result = membership(repo, group_id, user_id)
            assert result is None
            read_barrier.wait(timeout=10)
            return result

        monkeypatch.setattr(
            LedgerRepository, "get_membership", simultaneous_unlinked_read
        )
    attempts = [
        (users[1], token),
        (
            users[1] if race != "different_users_same_token" else users[2],
            token2 if race == "same_user_two_guests" else token,
        ),
    ]

    def claim(pair):
        actor, raw = pair
        with Session(pg_engine, expire_on_commit=False) as s:
            barrier.wait(timeout=10)
            try:
                return ("ok", InvitationService(s, actor).accept(raw).id)
            except InvitationConflict:
                return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, attempts))
    assert sorted(r[0] for r in results) == (
        ["ok", "ok"] if race == "same_user_same_token" else ["conflict", "ok"]
    )
    with Session(pg_engine) as s:
        linked = list(
            s.scalars(
                select(GroupMemberRow).where(
                    GroupMemberRow.group_id == group.id,
                    GroupMemberRow.user_id == users[1].id,
                )
            )
        )
        if race != "different_users_same_token":
            assert len(linked) == 1
        rows = list(
            s.scalars(
                select(TripInvitationRow).where(TripInvitationRow.group_id == group.id)
            )
        )
        assert sum(row.accepted_at is not None for row in rows) == 1
        assert all(
            (row.accepted_at is None) == (row.accepted_by_user_id is None)
            for row in rows
        )
        for row in rows:
            target = s.get(GroupMemberRow, row.target_member_id)
            assert target.user_id == row.accepted_by_user_id


def test_revocation_wins_while_acceptance_waits_for_target_lock(
    pg_engine, committed_invitation, monkeypatch
):
    users, group, guest, second, inv, token, inv2, token2 = committed_invitation
    entered = Event()
    lock_member = InvitationService._member

    def waiting_for_target(service, group_id, member_id):
        entered.set()
        return lock_member(service, group_id, member_id)

    monkeypatch.setattr(InvitationService, "_member", waiting_for_target)

    def claim():
        with Session(pg_engine) as s:
            with pytest.raises(ResourceNotFound):
                InvitationService(s, users[1]).accept(token)

    with Session(pg_engine) as s:
        with s.begin():
            s.execute(
                select(GroupMemberRow)
                .where(GroupMemberRow.id == guest.id)
                .with_for_update()
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(claim)
                assert entered.wait(5)
                row = s.get(TripInvitationRow, inv.id)
                row.revoked_at = datetime.now(UTC)
                row.revoked_by_user_id = users[0].id
                s.flush()
                # Commit the winning revocation before waiting for the blocked claim.
                s.commit()
                future.result(timeout=10)
    with Session(pg_engine) as s:
        assert s.get(GroupMemberRow, guest.id).user_id is None
