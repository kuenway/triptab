"""Membership, owner/author permissions, and scoped resources over real PostgreSQL."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain import Group, GroupMember
from app.persistence.models import ExpenseRow, GroupMemberRow, GroupRow
from app.persistence.repository import LedgerRepository

pytestmark = pytest.mark.integration
OCCURRED = "2026-10-03T12:00:00Z"


@pytest.fixture
def trip_accounts(account_clients, db_session):
    owner, alice = account_clients("Alice")
    author, bob = account_clients("Bob")
    member, charlie = account_clients("Charlie")
    outsider, eve = account_clients("Eve")
    response = owner.post("/api/v1/groups", json={"name": "Private trip"})
    assert response.status_code == 201
    group = response.json()
    base = f"/api/v1/groups/{group['id']}"
    owner_member = owner.get(base + "/members").json()[0]
    repo = LedgerRepository(db_session)
    bob_member = GroupMember(uuid4(), UUID(group["id"]), "Bob", UUID(bob["id"]))
    charlie_member = GroupMember(
        uuid4(), UUID(group["id"]), "Charlie", UUID(charlie["id"])
    )
    # Account linking has no public API in M9. Fixtures explicitly establish it.
    repo.save_member(bob_member)
    repo.save_member(charlie_member)
    guest = owner.post(base + "/members", json={"display_name": "Guest"}).json()
    expense = {
        "description": "Dinner",
        "amount": 900,
        "payer_member_id": owner_member["id"],
        "split_strategy": "equal",
        "participant_member_ids": [
            owner_member["id"],
            str(bob_member.id),
            str(charlie_member.id),
        ],
        "occurred_at": OCCURRED,
    }
    settlement = {
        "from_member_id": str(bob_member.id),
        "to_member_id": owner_member["id"],
        "amount": 300,
        "occurred_at": OCCURRED,
    }
    return {
        "owner": owner,
        "author": author,
        "member": member,
        "outsider": outsider,
        "users": [alice, bob, charlie, eve],
        "group": group,
        "base": base,
        "expense": expense,
        "settlement": settlement,
        "guest": guest,
        "owner_member": owner_member,
    }


def test_groups_are_private_and_owner_is_linked_financial_member(trip_accounts):
    t = trip_accounts
    assert t["owner"].get("/api/v1/groups").json() == [t["group"]]
    assert t["author"].get("/api/v1/groups").json() == [t["group"]]
    assert t["outsider"].get("/api/v1/groups").json() == []
    assert t["outsider"].get(t["base"]).status_code == 404
    assert t["owner_member"]["role"] == "owner"
    assert t["owner_member"]["user_id"] == t["users"][0]["id"]
    assert t["guest"]["role"] == "member" and t["guest"]["user_id"] is None
    members = t["owner"].get(t["base"] + "/members").json()
    assert sum(item["user_id"] == t["users"][0]["id"] for item in members) == 1
    assert all("email" not in item for item in members)
    assert len(t["owner"].get(t["base"] + "/balances").json()["balances"]) == 4


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "/members",
        "/expenses",
        "/settlements",
        "/balances",
        "/settlement-suggestions",
    ],
)
def test_outsider_cannot_read_any_trip_resource(trip_accounts, suffix):
    t = trip_accounts
    response = t["outsider"].get(t["base"] + suffix)
    assert response.status_code == 404
    assert response.json() == {"detail": "group not found"}


@pytest.mark.parametrize(
    "who,status", [("owner", 201), ("member", 403), ("outsider", 404)]
)
def test_only_owner_can_add_guest(trip_accounts, who, status):
    t = trip_accounts
    assert (
        t[who]
        .post(t["base"] + "/members", json={"display_name": "Traveler"})
        .status_code
        == status
    )


@pytest.mark.parametrize(
    "who,status", [("author", 201), ("member", 201), ("outsider", 404)]
)
def test_expense_creation_uses_current_authenticated_actor(
    trip_accounts, db_session, who, status
):
    t = trip_accounts
    response = t[who].post(t["base"] + "/expenses", json=t["expense"])
    assert response.status_code == status
    if status == 201:
        user_id = t[who].get("/api/v1/auth/me").json()["user"]["id"]
        assert response.json()["created_by_user_id"] == user_id
        assert db_session.get(
            ExpenseRow, UUID(response.json()["id"])
        ).created_by_user_id == UUID(user_id)


@pytest.mark.parametrize("field", ["created_by_user_id", "user_id", "actor_id"])
def test_client_actor_spoofing_is_rejected(trip_accounts, field):
    t = trip_accounts
    assert (
        t["author"]
        .post(t["base"] + "/expenses", json=t["expense"] | {field: t["users"][0]["id"]})
        .status_code
        == 422
    )
    assert (
        t["author"]
        .post(
            t["base"] + "/settlements",
            json=t["settlement"] | {field: t["users"][0]["id"]},
        )
        .status_code
        == 422
    )
    assert (
        t["owner"]
        .post(
            t["base"] + "/members",
            json={"display_name": "Account", "user_id": t["users"][1]["id"]},
        )
        .status_code
        == 422
    )


@pytest.mark.parametrize("kind", ["expense", "settlement"])
@pytest.mark.parametrize("operation", ["void", "corrections"])
@pytest.mark.parametrize(
    "who,status", [("author", 200), ("owner", 200), ("member", 403), ("outsider", 404)]
)
def test_financial_change_requires_author_or_owner(
    trip_accounts, db_session, kind, operation, who, status
):
    t = trip_accounts
    original = t["author"].post(t["base"] + f"/{kind}s", json=t[kind]).json()
    path = f"{t['base']}/{kind}s/{original['id']}/{operation}"
    payload = {"reason": "Correction"}
    if operation == "corrections":
        payload["replacement"] = t[kind] | {"amount": 990 if kind == "expense" else 200}
    response = t[who].post(path, json=payload)
    assert response.status_code == (
        201 if operation == "corrections" and status == 200 else status
    ), response.text
    if status == 200:
        actor_id = t[who].get("/api/v1/auth/me").json()["user"]["id"]
        audit = {
            item["id"]: item for item in t["owner"].get(t["base"] + f"/{kind}s").json()
        }
        assert audit[original["id"]]["void_created_by_user_id"] == actor_id
        assert audit[original["id"]]["created_by_user_id"] == t["users"][1]["id"]
        if operation == "corrections":
            assert response.json()["created_by_user_id"] == actor_id
        void = getattr(LedgerRepository(db_session), f"get_{kind}_void")(
            UUID(original["id"])
        )
        assert void.created_by_user_id == UUID(actor_id)
    else:
        assert t["owner"].get(t["base"] + f"/{kind}s").json() == [original]


@pytest.mark.parametrize(
    "who,status", [("author", 201), ("owner", 201), ("member", 403), ("outsider", 404)]
)
def test_payment_creation_requires_sender_recipient_or_owner(
    trip_accounts, who, status
):
    t = trip_accounts
    response = t[who].post(t["base"] + "/settlements", json=t["settlement"])
    assert response.status_code == status


def test_recipient_can_record_and_owner_can_record_between_guests(trip_accounts):
    t = trip_accounts
    charlie_id = next(
        item["id"]
        for item in t["owner"].get(t["base"] + "/members").json()
        if item["display_name"] == "Charlie"
    )
    assert (
        t["member"]
        .post(
            t["base"] + "/settlements",
            json=t["settlement"] | {"to_member_id": charlie_id},
        )
        .status_code
        == 201
    )
    second_guest = (
        t["owner"]
        .post(t["base"] + "/members", json={"display_name": "Other guest"})
        .json()
    )
    response = t["owner"].post(
        t["base"] + "/settlements",
        json=t["settlement"]
        | {
            "from_member_id": t["guest"]["id"],
            "to_member_id": second_guest["id"],
            "amount": 500,
        },
    )
    assert response.status_code == 201


@pytest.mark.parametrize("kind", ["expense", "settlement"])
@pytest.mark.parametrize("operation", ["read", "void", "corrections"])
def test_nested_financial_idor_requires_authorized_group_and_scoped_target(
    trip_accounts, kind, operation
):
    t = trip_accounts
    other = t["owner"].post("/api/v1/groups", json={"name": "Second owned trip"}).json()
    original = t["author"].post(t["base"] + f"/{kind}s", json=t[kind]).json()
    wrong_scope = f"/api/v1/groups/{other['id']}/{kind}s/{original['id']}"
    if operation == "read":
        if kind == "expense":
            assert t["owner"].get(wrong_scope).status_code == 404
            assert (
                t["outsider"].get(t["base"] + f"/expenses/{original['id']}").status_code
                == 404
            )
        else:
            assert (
                t["owner"].get(f"/api/v1/groups/{other['id']}/settlements").json() == []
            )
    else:
        payload = {"reason": "Wrong scope"}
        if operation == "corrections":
            payload["replacement"] = t[kind]
        assert (
            t["owner"].post(wrong_scope + f"/{operation}", json=payload).status_code
            == 404
        )
        assert (
            t["outsider"]
            .post(f"{t['base']}/{kind}s/{original['id']}/{operation}", json=payload)
            .status_code
            == 404
        )
    assert t["author"].get(t["base"] + f"/{kind}s").json() == [original]


def test_owner_membership_creation_failure_rolls_back_group(
    client, db_session, monkeypatch
):
    saved = LedgerRepository.save_member

    def fail_after_flush(repo, member):
        saved(repo, member)
        raise IntegrityError("forced membership failure", {}, Exception("rollback"))

    monkeypatch.setattr(LedgerRepository, "save_member", fail_after_flush)
    response = client.post("/api/v1/groups", json={"name": "Atomic ownership"})
    assert response.status_code == 422
    assert db_session.scalar(select(GroupRow.id)) is None
    assert db_session.scalar(select(GroupMemberRow.id)) is None


def test_legacy_unowned_group_is_not_exposed_to_registered_users(client, db_session):
    group = Group(uuid4(), "Legacy trip")
    LedgerRepository(db_session).save_group(group)
    assert client.get("/api/v1/groups").json() == []
    assert client.get(f"/api/v1/groups/{group.id}").status_code == 404


def test_role_and_membership_constraints_round_trip(trip_accounts, db_session):
    t = trip_accounts
    repo = LedgerRepository(db_session)
    member = repo.get_membership(UUID(t["group"]["id"]), UUID(t["users"][0]["id"]))
    assert member.role == "owner" and not member.is_guest
    assert (
        repo.get_membership(UUID(t["group"]["id"]), UUID(t["users"][1]["id"])).role
        == "member"
    )
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            GroupMemberRow(
                id=uuid4(),
                group_id=member.group_id,
                user_id=UUID(t["users"][3]["id"]),
                display_name="Second owner",
                role="owner",
            )
        )
        db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            GroupMemberRow(
                id=uuid4(),
                group_id=member.group_id,
                display_name="Guest owner",
                role="owner",
            )
        )
        db_session.flush()


@pytest.mark.parametrize(
    "suffix",
    [
        "groups",
        "groups/{gid}",
        "groups/{gid}/members",
        "groups/{gid}/expenses",
        "groups/{gid}/expenses/{eid}",
        "groups/{gid}/balances",
        "groups/{gid}/settlement-suggestions",
        "groups/{gid}/settlements",
    ],
)
def test_product_gets_require_authentication(raw_client, suffix):
    path = "/api/v1/" + suffix.format(gid=uuid4(), eid=uuid4())
    assert raw_client.get(path).status_code == 401


@pytest.mark.parametrize(
    "kind,operation",
    [
        ("expenses", "create"),
        ("settlements", "create"),
        ("expenses", "void"),
        ("expenses", "corrections"),
        ("settlements", "void"),
        ("settlements", "corrections"),
        ("members", "create"),
        ("groups", "create"),
    ],
)
def test_all_product_posts_require_authentication(raw_client, kind, operation):
    path = (
        "/api/v1/groups"
        if kind == "groups"
        else f"/api/v1/groups/{uuid4()}/{kind}"
        + (f"/{uuid4()}/{operation}" if operation != "create" else "")
    )
    assert raw_client.post(path, json={}).status_code == 401


def test_author_cannot_use_correction_to_record_unrelated_payment(trip_accounts):
    t = trip_accounts
    original = t["author"].post(t["base"] + "/settlements", json=t["settlement"]).json()
    replacement = t["settlement"] | {"from_member_id": t["guest"]["id"]}
    response = t["author"].post(
        f"{t['base']}/settlements/{original['id']}/corrections",
        json={"reason": "Different sender", "replacement": replacement},
    )
    assert response.status_code == 403
    assert t["owner"].get(t["base"] + "/settlements").json() == [original]
    assert (
        t["owner"]
        .post(
            f"{t['base']}/settlements/{original['id']}/corrections",
            json={
                "reason": "Owner confirms actual payment",
                "replacement": replacement,
            },
        )
        .status_code
        == 201
    )


def test_author_can_correct_payment_to_be_the_recipient(trip_accounts):
    t = trip_accounts
    original = t["author"].post(t["base"] + "/settlements", json=t["settlement"]).json()
    replacement = t["settlement"] | {
        "from_member_id": t["owner_member"]["id"],
        "to_member_id": t["settlement"]["from_member_id"],
        "amount": 200,
    }
    response = t["author"].post(
        f"{t['base']}/settlements/{original['id']}/corrections",
        json={"reason": "Direction was reversed", "replacement": replacement},
    )
    assert response.status_code == 201
    assert response.json()["from_member_id"] == replacement["from_member_id"]
    assert response.json()["to_member_id"] == replacement["to_member_id"]


@pytest.mark.parametrize("kind", ["expenses", "settlements"])
def test_note_less_void_preserves_owner_author_and_idor_rules(trip_accounts, kind):
    t = trip_accounts
    payload = t["expense"] if kind == "expenses" else t["settlement"]
    record = t["author"].post(t["base"] + "/" + kind, json=payload)
    assert record.status_code == 201
    path = t["base"] + "/" + kind + "/" + record.json()["id"]
    assert t["member"].post(path + "/void", json={}).status_code == 403
    assert t["outsider"].post(path + "/void", json={}).status_code == 404
    assert t["author"].get(t["base"] + "/" + kind).json()[0]["status"] == "active"
    assert t["owner"].post(path + "/void", json={}).status_code == 200
    assert t["author"].get(t["base"] + "/" + kind).json()[0]["void_reason"] is None
