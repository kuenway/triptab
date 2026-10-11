"""Exact current suggestions and all financial writers serialize per Trip."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_authorization import trip_accounts as trip_accounts

from app.application.service import FinancialConflict, TripTabService
from app.domain import GroupMember, SplitStrategy, User
from app.persistence.models import GroupMemberRow, GroupRow
from app.persistence.repository import LedgerRepository

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


def seed_api(t):
    assert (
        t["owner"].post(t["base"] + "/expenses", json=t["expense"]).status_code == 201
    )
    return t["owner"].get(t["base"] + "/settlement-suggestions").json()["suggestions"]


def payload(s):
    return {key: s[key] for key in ("from_member_id", "to_member_id", "amount")}


def bob_suggestion(t):
    return next(
        s
        for s in seed_api(t)
        if s["from_member_id"] == t["settlement"]["from_member_id"]
    )


def test_exact_confirmation_stale_retry_and_no_store(trip_accounts):
    t = trip_accounts
    suggestion = bob_suggestion(t)
    path = t["base"] + "/settlement-suggestions/confirm"
    first = t["owner"].post(path, json=payload(suggestion))
    assert first.status_code == 201
    assert payload(first.json()) == payload(suggestion)
    assert first.json()["created_by_user_id"] == t["users"][0]["id"]
    assert first.json()["status"] == "active"
    before = t["owner"].get(t["base"] + "/balances").json()
    second = t["author"].post(path, json=payload(suggestion))
    assert second.status_code == 409
    assert second.json() == {"detail": "settlement suggestion has changed"}
    assert t["owner"].get(t["base"] + "/balances").json() == before
    assert len(t["owner"].get(t["base"] + "/settlements").json()) == 1
    for response in (first, second):
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("change", ["amount", "direction", "unrelated_participant"])
def test_mismatch_does_not_write(trip_accounts, change):
    t = trip_accounts
    s = payload(seed_api(t)[0])
    if change == "amount":
        s["amount"] += 1
    elif change == "direction":
        s["from_member_id"], s["to_member_id"] = s["to_member_id"], s["from_member_id"]
    else:
        s["to_member_id"] = t["guest"]["id"]
    assert (
        t["owner"]
        .post(t["base"] + "/settlement-suggestions/confirm", json=s)
        .status_code
        == 409
    )
    assert t["owner"].get(t["base"] + "/settlements").json() == []


@pytest.mark.parametrize(
    "actor,status",
    [("owner", 201), ("author", 201), ("member", 403), ("outsider", 404)],
)
def test_permissions(trip_accounts, actor, status):
    t = trip_accounts
    s = bob_suggestion(t)
    result = t[actor].post(
        t["base"] + "/settlement-suggestions/confirm", json=payload(s)
    )
    assert result.status_code == status
    assert len(t["owner"].get(t["base"] + "/settlements").json()) == (status == 201)


def test_nonowner_recipient(trip_accounts):
    t = trip_accounts
    expense = {**t["expense"], "payer_member_id": t["settlement"]["from_member_id"]}
    assert t["author"].post(t["base"] + "/expenses", json=expense).status_code == 201
    s = t["owner"].get(t["base"] + "/settlement-suggestions").json()["suggestions"][0]
    assert s["to_member_id"] == t["settlement"]["from_member_id"]
    assert (
        t["author"]
        .post(t["base"] + "/settlement-suggestions/confirm", json=payload(s))
        .status_code
        == 201
    )


def test_auth_idor_validation(trip_accounts, raw_client):
    t = trip_accounts
    s = payload(seed_api(t)[0])
    path = t["base"] + "/settlement-suggestions/confirm"
    assert raw_client.post(path, json=s).status_code == 401
    for amount in (0, "300"):
        assert t["owner"].post(path, json={**s, "amount": amount}).status_code == 422
    assert (
        t["owner"].post(path, json={**s, "from_member_id": str(uuid4())}).status_code
        == 404
    )
    other = t["owner"].post("/api/v1/groups", json={"name": "Other"}).json()
    path = f"/api/v1/groups/{other['id']}/settlement-suggestions/confirm"
    for actor in ("owner", "author"):
        assert t[actor].post(path, json=s).status_code == 404
    assert t["owner"].get(t["base"] + "/settlements").json() == []


@pytest.mark.parametrize(
    "header,value",
    [
        ("Origin", ""),
        ("Origin", "https://evil.example"),
        ("X-CSRF-Token", ""),
        ("X-CSRF-Token", "wrong"),
    ],
)
def test_csrf_and_origin(trip_accounts, header, value):
    t = trip_accounts
    s = payload(seed_api(t)[0])
    result = t["owner"].post(
        t["base"] + "/settlement-suggestions/confirm", json=s, headers={header: value}
    )
    assert result.status_code == 403
    assert t["owner"].get(t["base"] + "/settlements").json() == []


@pytest.mark.parametrize("amount", [100, 400])
def test_generic_partial_and_overpayment_still_valid(trip_accounts, amount):
    t = trip_accounts
    seed_api(t)
    result = t["owner"].post(
        t["base"] + "/settlements", json={**t["settlement"], "amount": amount}
    )
    assert result.status_code == 201
    balances = t["owner"].get(t["base"] + "/balances").json()["balances"]
    assert (
        next(
            b["amount"]
            for b in balances
            if b["member_id"] == t["settlement"]["from_member_id"]
        )
        == amount - 300
    )


@pytest.fixture
def race_ledger(pg_engine):
    """Committed fixture: workers use independent DB connections/transactions."""
    users = [
        User(uuid4(), f"m17c-{uuid4()}@example.com", name) for name in ("Alice", "Bob")
    ]
    with Session(pg_engine, expire_on_commit=False) as session:
        repo = LedgerRepository(session)
        with session.begin():
            for user in users:
                repo.save_user(user)
        service = TripTabService(session, users[0])
        group = service.create_group("Disposable M17C race fixture")
        with session.begin():
            alice = repo.list_members(group.id)[0]
            bob = GroupMember(uuid4(), group.id, "Bob", users[1].id)
            repo.save_member(bob)
        expense = service.create_expense(
            group.id,
            "Dinner",
            600,
            alice.id,
            SplitStrategy.EQUAL,
            NOW,
            (alice.id, bob.id),
        )
    try:
        yield users, group, alice, bob, expense
    finally:
        # Disposable local test fixture only.
        with pg_engine.begin() as c:
            for table in (
                "settlement_voids",
                "expense_voids",
                "expense_splits",
                "settlements",
                "expenses",
                "group_members",
            ):
                c.execute(
                    text(f"DELETE FROM {table} WHERE group_id=:id"), {"id": group.id}
                )
            c.execute(text("DELETE FROM groups WHERE id=:id"), {"id": group.id})
            for user in users:
                c.execute(text("DELETE FROM users WHERE id=:id"), {"id": user.id})


def test_simultaneous_confirmations_exactly_one_commits(pg_engine, race_ledger):
    users, group, alice, bob, _ = race_ledger
    barrier = Barrier(2)

    def run(actor):
        with Session(pg_engine) as session:
            barrier.wait(timeout=10)
            try:
                TripTabService(session, users[actor]).confirm_settlement_suggestion(
                    group.id, bob.id, alice.id, 300
                )
                return "success"
            except FinancialConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, i) for i in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == ["conflict", "success"]
    with Session(pg_engine) as session:
        service = TripTabService(session, users[0])
        assert len(service.list_settlements(group.id)) == 1
        assert all(amount == 0 for _, amount in service.get_balances(group.id)[1])


@pytest.mark.parametrize(
    "mutation",
    [
        "settlement",
        "expense",
        "expense_correct",
        "expense_void",
        "settlement_correct",
        "settlement_void",
    ],
)
@pytest.mark.parametrize("first", ["mutation", "confirmation"])
def test_all_financial_writers_serialize(
    pg_engine, race_ledger, monkeypatch, mutation, first
):
    users, group, alice, bob, expense = race_ledger
    original = None
    if mutation.startswith("settlement_"):
        with Session(pg_engine) as s:
            original = TripTabService(s, users[0]).record_settlement(
                group.id, bob.id, alice.id, 10, NOW
            )
    locked, release, waiting = Event(), Event(), Event()
    lock = LedgerRepository.lock_group_finances

    def pause(repo, group_id):
        if repo.session.info.get("first"):
            lock(repo, group_id)
            locked.set()
            assert release.wait(10)
        else:
            waiting.set()
            lock(repo, group_id)

    monkeypatch.setattr(LedgerRepository, "lock_group_finances", pause)
    amount = 290 if original else 300

    def run(which):
        with Session(pg_engine) as s:
            s.info["first"] = which == first
            service = TripTabService(s, users[0])
            if which == "confirmation":
                try:
                    service.confirm_settlement_suggestion(
                        group.id, bob.id, alice.id, amount
                    )
                    return "success"
                except FinancialConflict:
                    return "conflict"
            if mutation == "settlement":
                service.record_settlement(group.id, bob.id, alice.id, 300, NOW)
            elif mutation == "expense":
                service.create_expense(
                    group.id,
                    "Bob dinner",
                    600,
                    bob.id,
                    SplitStrategy.EQUAL,
                    NOW,
                    (alice.id, bob.id),
                )
            elif mutation == "expense_correct":
                service.correct_expense(
                    group.id,
                    expense.id,
                    "Receipt",
                    "Dinner",
                    800,
                    alice.id,
                    SplitStrategy.EQUAL,
                    NOW,
                    (alice.id, bob.id),
                )
            elif mutation == "expense_void":
                service.void_expense(group.id, expense.id, "Duplicate")
            elif mutation == "settlement_correct":
                service.correct_settlement(
                    group.id, original.id, "Actual amount", bob.id, alice.id, 20, NOW
                )
            else:
                service.void_settlement(group.id, original.id, "Not transferred")
            return "mutation"

    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(run, first)
        assert locked.wait(10)
        follower = pool.submit(
            run, "confirmation" if first == "mutation" else "mutation"
        )
        try:
            assert waiting.wait(10)
            with pg_engine.connect() as observer:
                deadline = datetime.now(UTC).timestamp() + 5
                while datetime.now(UTC).timestamp() < deadline:
                    count = observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() "
                            "AND wait_event_type='Lock'"
                        )
                    )
                    if count:
                        break
                else:
                    pytest.fail("follower did not block on a PostgreSQL lock")
            assert not follower.done()
        finally:
            release.set()
        results = [leader.result(timeout=15), follower.result(timeout=15)]
    assert results == (
        ["mutation", "conflict"] if first == "mutation" else ["success", "mutation"]
    )
    expected = {
        "settlement": 0,
        "expense": 0,
        "expense_correct": 400,
        "expense_void": 0,
        "settlement_correct": 280,
        "settlement_void": 300,
    }[mutation]
    if first == "confirmation":
        expected -= amount
    with Session(pg_engine) as s:
        service = TripTabService(s, users[0])
        values = {m.id: value for m, value in service.get_balances(group.id)[1]}
        assert values == {alice.id: expected, bob.id: -expected}
        settlements = service.list_settlements(group.id)
        assert sum(r.amount_minor == amount for r in settlements) == int(
            first == "confirmation"
        ) + int(mutation == "settlement")


def test_financial_lock_allows_member_first_fk_key_share(pg_engine, race_ledger):
    _, group, _, bob, _ = race_ledger
    with Session(pg_engine) as financial, financial.begin():
        LedgerRepository(financial).lock_group_finances(group.id)
        with Session(pg_engine) as other, other.begin():
            other.execute(text("SET LOCAL lock_timeout='1s'"))
            other.execute(
                select(GroupMemberRow.id)
                .where(GroupMemberRow.id == bob.id)
                .with_for_update()
            )
            # Matches Group FK key-share acquisition after invitation/member locks.
            other.execute(
                select(GroupRow.id)
                .where(GroupRow.id == group.id)
                .with_for_update(read=True, key_share=True)
            )
