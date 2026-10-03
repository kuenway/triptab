"""Exercise the public API through FastAPI, PostgreSQL, and accounting."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.application.service import DEVELOPMENT_ACTOR
from app.domain import Settlement
from app.main import app
from app.persistence.models import UserRow
from app.persistence.repository import LedgerRepository

pytestmark = pytest.mark.integration
OCCURRED = "2026-10-02T20:00:00+08:00"


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    connection = db_session.connection()

    def test_session() -> Iterator[Session]:
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)


def group(client: TestClient, name: str = "Trip") -> dict:
    response = client.post("/api/v1/groups", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def member(client: TestClient, group_id: str, name: str) -> dict:
    response = client.post(
        f"/api/v1/groups/{group_id}/members", json={"display_name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def equal_payload(payer_id: str, participant_ids: list[str], amount: int = 900) -> dict:
    return {
        "description": "Dinner",
        "amount": amount,
        "payer_member_id": payer_id,
        "split_strategy": "equal",
        "participant_member_ids": participant_ids,
        "occurred_at": OCCURRED,
    }


def balances(client: TestClient, group_id: str) -> dict[str, int]:
    response = client.get(f"/api/v1/groups/{group_id}/balances")
    assert response.status_code == 200, response.text
    return {item["member_id"]: item["amount"] for item in response.json()["balances"]}


def test_health_and_openapi_contract(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/v1/groups" in paths
    assert "/api/v1/groups/{group_id}/expenses" in paths
    assert "/api/v1/groups/{group_id}/balances" in paths
    assert "/api/v1/groups/{group_id}/settlement-suggestions" in paths
    assert "201" in paths["/api/v1/groups"]["post"]["responses"]


def test_group_create_list_get_and_missing(client: TestClient) -> None:
    created = group(client)
    assert created["currency"] == "TWD"
    assert created["currency_scale"] == 0
    assert client.get(f"/api/v1/groups/{created['id']}").json() == created
    assert client.get("/api/v1/groups").json() == [created]
    assert client.get(f"/api/v1/groups/{uuid4()}").status_code == 404
    assert client.post("/api/v1/groups", json={"name": "   "}).status_code == 422
    assert (
        client.post("/api/v1/groups", json={"name": "X", "currency": "USD"}).status_code
        == 422
    )


def test_guest_members_are_scoped_to_group(client: TestClient) -> None:
    first = group(client)
    second = group(client, "Other")
    alice = member(client, first["id"], "Alice")
    member(client, second["id"], "Bob")
    assert alice["user_id"] is None
    assert client.get(f"/api/v1/groups/{first['id']}/members").json() == [alice]
    assert client.get(f"/api/v1/groups/{uuid4()}/members").status_code == 404
    assert (
        client.post(
            f"/api/v1/groups/{uuid4()}/members", json={"display_name": "X"}
        ).status_code
        == 404
    )


def test_equal_expense_stored_splits_and_derived_balances(client: TestClient) -> None:
    trip = group(client)
    alice, bob, charlie = (
        member(client, trip["id"], name) for name in ("Alice", "Bob", "Charlie")
    )
    response = client.post(
        f"/api/v1/groups/{trip['id']}/expenses",
        json=equal_payload(alice["id"], [alice["id"], bob["id"], charlie["id"]]),
    )
    assert response.status_code == 201, response.text
    expense = response.json()
    assert expense["split_strategy"] == "equal"
    assert expense["amount"] == 900
    assert {split["member_id"]: split["amount"] for split in expense["splits"]} == {
        alice["id"]: 300,
        bob["id"]: 300,
        charlie["id"]: 300,
    }
    assert datetime.fromisoformat(expense["occurred_at"]).utcoffset() is not None
    assert datetime.fromisoformat(expense["created_at"]).utcoffset() is not None
    assert balances(client, trip["id"]) == {
        alice["id"]: 600,
        bob["id"]: -300,
        charlie["id"]: -300,
    }
    assert (
        client.get(f"/api/v1/groups/{trip['id']}/expenses/{expense['id']}").json()
        == expense
    )


def test_payer_can_be_outside_equal_participants(client: TestClient) -> None:
    trip = group(client)
    alice, bob, charlie = (
        member(client, trip["id"], name) for name in ("Alice", "Bob", "Charlie")
    )
    response = client.post(
        f"/api/v1/groups/{trip['id']}/expenses",
        json=equal_payload(alice["id"], [bob["id"], charlie["id"]]),
    )
    assert response.status_code == 201, response.text
    assert {split["amount"] for split in response.json()["splits"]} == {450}
    assert balances(client, trip["id"]) == {
        alice["id"]: 900,
        bob["id"]: -450,
        charlie["id"]: -450,
    }


def test_exact_expense_and_invalid_allocations(client: TestClient) -> None:
    trip = group(client)
    alice = member(client, trip["id"], "Alice")
    bob = member(client, trip["id"], "Bob")
    payload = {
        "description": "Tickets",
        "amount": 900,
        "payer_member_id": alice["id"],
        "split_strategy": "exact",
        "splits": [
            {"member_id": alice["id"], "amount": 500},
            {"member_id": bob["id"], "amount": 400},
        ],
        "occurred_at": OCCURRED,
    }
    response = client.post(f"/api/v1/groups/{trip['id']}/expenses", json=payload)
    assert response.status_code == 201, response.text
    assert {item["amount"] for item in response.json()["splits"]} == {400, 500}
    assert balances(client, trip["id"]) == {alice["id"]: 400, bob["id"]: -400}

    wrong_total = {**payload, "splits": [{"member_id": bob["id"], "amount": 899}]}
    duplicate = {
        **payload,
        "splits": [
            {"member_id": bob["id"], "amount": 450},
            {"member_id": bob["id"], "amount": 450},
        ],
    }
    for invalid in (wrong_total, duplicate):
        assert (
            client.post(
                f"/api/v1/groups/{trip['id']}/expenses", json=invalid
            ).status_code
            == 422
        )
    assert len(client.get(f"/api/v1/groups/{trip['id']}/expenses").json()) == 1


def test_cross_group_payer_and_participant_rejected(client: TestClient) -> None:
    first = group(client)
    second = group(client, "Other")
    alice = member(client, first["id"], "Alice")
    foreign = member(client, second["id"], "Foreign")
    base = f"/api/v1/groups/{first['id']}/expenses"
    assert (
        client.post(base, json=equal_payload(foreign["id"], [alice["id"]])).status_code
        == 404
    )
    assert (
        client.post(base, json=equal_payload(alice["id"], [foreign["id"]])).status_code
        == 404
    )
    assert (
        client.post(
            base,
            json={
                "description": "Invalid",
                "amount": 900,
                "payer_member_id": alice["id"],
                "split_strategy": "exact",
                "splits": [{"member_id": foreign["id"], "amount": 900}],
                "occurred_at": OCCURRED,
            },
        ).status_code
        == 404
    )
    assert client.get(base).json() == []


def test_expense_history_order_and_group_scoping(client: TestClient) -> None:
    first = group(client)
    second = group(client, "Other")
    alice = member(client, first["id"], "Alice")
    member(client, second["id"], "Bob")
    base = f"/api/v1/groups/{first['id']}/expenses"
    older = client.post(base, json=equal_payload(alice["id"], [alice["id"]])).json()
    same_time = client.post(base, json=equal_payload(alice["id"], [alice["id"]])).json()
    newer_time = (datetime.fromisoformat(OCCURRED) + timedelta(days=1)).isoformat()
    newer = client.post(
        base,
        json={**equal_payload(alice["id"], [alice["id"]]), "occurred_at": newer_time},
    ).json()
    history = client.get(base).json()
    assert [item["id"] for item in history] == [
        newer["id"],
        *sorted([older["id"], same_time["id"]], reverse=True),
    ]
    assert (
        client.get(f"/api/v1/groups/{second['id']}/expenses/{older['id']}").status_code
        == 404
    )
    assert client.get(f"{base}/{uuid4()}").status_code == 404
    assert client.get(f"/api/v1/groups/{uuid4()}/expenses").status_code == 404


def test_zero_and_multiple_expense_balances_are_deterministic(
    client: TestClient,
) -> None:
    trip = group(client)
    alice = member(client, trip["id"], "Alice")
    bob = member(client, trip["id"], "Bob")
    charlie = member(client, trip["id"], "Charlie")
    before = client.get(f"/api/v1/groups/{trip['id']}/balances").json()
    assert {item["amount"] for item in before["balances"]} == {0}
    assert [item["member_id"] for item in before["balances"]] == sorted(
        [alice["id"], bob["id"], charlie["id"]]
    )
    base = f"/api/v1/groups/{trip['id']}/expenses"
    assert (
        client.post(
            base, json=equal_payload(alice["id"], [alice["id"], bob["id"]], 100)
        ).status_code
        == 201
    )
    assert (
        client.post(
            base, json=equal_payload(bob["id"], [alice["id"], bob["id"]], 60)
        ).status_code
        == 201
    )
    first_read = client.get(f"/api/v1/groups/{trip['id']}/balances").json()
    assert first_read == client.get(f"/api/v1/groups/{trip['id']}/balances").json()
    assert sum(item["amount"] for item in first_read["balances"]) == 0
    assert balances(client, trip["id"]) == {
        alice["id"]: 20,
        bob["id"]: -20,
        charlie["id"]: 0,
    }


def test_invalid_transport_values_and_missing_group(client: TestClient) -> None:
    trip = group(client)
    alice = member(client, trip["id"], "Alice")
    base = f"/api/v1/groups/{trip['id']}/expenses"
    payload = equal_payload(alice["id"], [alice["id"]])
    for invalid in (
        {**payload, "amount": 900.0},
        {**payload, "amount": 0},
        {**payload, "occurred_at": "2026-10-02T20:00:00"},
        {**payload, "split_strategy": "percentage"},
        {**payload, "splits": []},
        {**payload, "participant_member_ids": []},
    ):
        assert client.post(base, json=invalid).status_code == 422
    assert (
        client.post(f"/api/v1/groups/{uuid4()}/expenses", json=payload).status_code
        == 404
    )
    assert client.get(f"/api/v1/groups/{uuid4()}/balances").status_code == 404
    assert client.get(base).json() == []


def test_invalid_expense_does_not_persist_actor_or_history(
    client: TestClient, db_session: Session
) -> None:
    trip = group(client)
    alice = member(client, trip["id"], "Alice")
    payload = equal_payload(alice["id"], [alice["id"], alice["id"]])
    assert (
        client.post(f"/api/v1/groups/{trip['id']}/expenses", json=payload).status_code
        == 422
    )
    assert client.get(f"/api/v1/groups/{trip['id']}/expenses").json() == []
    assert db_session.get(UserRow, DEVELOPMENT_ACTOR.id) is None


def test_uuid_paths_reject_malformed_ids(client: TestClient) -> None:
    assert client.get("/api/v1/groups/not-a-uuid").status_code == 422
    assert UUID(group(client)["id"])


def assert_response_settles(current: dict[str, int], suggestions: list[dict]) -> None:
    remaining = current.copy()
    for suggestion in suggestions:
        sender = suggestion["from_member_id"]
        recipient = suggestion["to_member_id"]
        amount = suggestion["amount"]
        assert type(amount) is int and amount > 0
        assert sender != recipient
        assert current[sender] < 0 < current[recipient]
        remaining[sender] += amount
        remaining[recipient] -= amount
        assert sum(remaining.values()) == 0
    assert all(amount == 0 for amount in remaining.values())


def test_equal_expense_suggestions_are_read_only(
    client: TestClient, db_session: Session
) -> None:
    trip = group(client)
    alice, bob, charlie = (
        member(client, trip["id"], name) for name in ("Alice", "Bob", "Charlie")
    )
    history_path = f"/api/v1/groups/{trip['id']}/expenses"
    response = client.post(
        history_path,
        json=equal_payload(alice["id"], [alice["id"], bob["id"], charlie["id"]]),
    )
    assert response.status_code == 201, response.text
    current = balances(client, trip["id"])
    assert current == {alice["id"]: 600, bob["id"]: -300, charlie["id"]: -300}
    history = client.get(history_path).json()

    path = f"/api/v1/groups/{trip['id']}/settlement-suggestions"
    response = client.get(path)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result == {
        "group_id": trip["id"],
        "currency": "TWD",
        "suggestions": [
            {
                "from_member_id": debtor["id"],
                "from_display_name": debtor["display_name"],
                "to_member_id": alice["id"],
                "to_display_name": "Alice",
                "amount": 300,
            }
            for debtor in sorted([bob, charlie], key=lambda value: value["id"])
        ],
    }
    assert client.get(path).json() == result
    assert_response_settles(current, result["suggestions"])
    assert balances(client, trip["id"]) == current
    assert client.get(history_path).json() == history
    assert LedgerRepository(db_session).list_settlements(UUID(trip["id"])) == ()


def test_multiple_payer_suggestions_are_deterministic_and_group_scoped(
    client: TestClient,
) -> None:
    trip = group(client)
    travelers = [member(client, trip["id"], name) for name in ("A", "B", "C", "D")]
    ids = [traveler["id"] for traveler in travelers]
    for payer_id, amount in ((ids[0], 900), (ids[1], 600)):
        response = client.post(
            f"/api/v1/groups/{trip['id']}/expenses",
            json=equal_payload(payer_id, ids, amount),
        )
        assert response.status_code == 201, response.text

    other = group(client, "Other trip")
    foreign = [member(client, other["id"], name) for name in ("Foreign A", "Foreign B")]
    response = client.post(
        f"/api/v1/groups/{other['id']}/expenses",
        json=equal_payload(foreign[0]["id"], [value["id"] for value in foreign], 100),
    )
    assert response.status_code == 201, response.text

    current = balances(client, trip["id"])
    assert current == {ids[0]: 525, ids[1]: 225, ids[2]: -375, ids[3]: -375}
    path = f"/api/v1/groups/{trip['id']}/settlement-suggestions"
    response = client.get(path)
    assert response.status_code == 200, response.text
    result = response.json()
    assert client.get(path).json() == result
    assert_response_settles(current, result["suggestions"])
    names = {traveler["id"]: traveler["display_name"] for traveler in travelers}
    for suggestion in result["suggestions"]:
        assert suggestion["from_display_name"] == names[suggestion["from_member_id"]]
        assert suggestion["to_display_name"] == names[suggestion["to_member_id"]]
    assert balances(client, trip["id"]) == current


def test_settled_and_missing_group_suggestions(client: TestClient) -> None:
    trip = group(client)
    path = f"/api/v1/groups/{trip['id']}/settlement-suggestions"
    expected = {"group_id": trip["id"], "currency": "TWD", "suggestions": []}
    assert client.get(path).json() == expected
    alice = member(client, trip["id"], "Alice")
    assert client.get(path).json() == expected
    response = client.post(
        f"/api/v1/groups/{trip['id']}/expenses",
        json=equal_payload(alice["id"], [alice["id"]]),
    )
    assert response.status_code == 201, response.text
    assert client.get(path).json() == expected
    assert (
        client.get(f"/api/v1/groups/{uuid4()}/settlement-suggestions").status_code
        == 404
    )


def settlement_payload(sender: str, recipient: str, amount: int = 300) -> dict:
    return {
        "from_member_id": sender,
        "to_member_id": recipient,
        "amount": amount,
        "occurred_at": OCCURRED,
    }


def test_settlement_creation_round_trip_and_balance_refresh(
    client: TestClient, db_session: Session
) -> None:
    trip = group(client)
    alice, bob, charlie = (
        member(client, trip["id"], name) for name in ("Alice", "Bob", "Charlie")
    )
    expense = client.post(
        f"/api/v1/groups/{trip['id']}/expenses",
        json=equal_payload(alice["id"], [alice["id"], bob["id"], charlie["id"]]),
    )
    assert expense.status_code == 201, expense.text
    assert balances(client, trip["id"]) == {
        alice["id"]: 600,
        bob["id"]: -300,
        charlie["id"]: -300,
    }
    base = f"/api/v1/groups/{trip['id']}"
    assert client.get(f"{base}/settlements").json() == []
    client.get(f"{base}/settlement-suggestions")
    assert client.get(f"{base}/settlements").json() == []

    response = client.post(
        f"{base}/settlements", json=settlement_payload(bob["id"], alice["id"])
    )
    assert response.status_code == 201, response.text
    payment = response.json()
    assert payment["from_display_name"] == "Bob"
    assert payment["to_display_name"] == "Alice"
    assert payment["group_id"] == trip["id"]
    assert payment["amount"] == 300
    stored = LedgerRepository(db_session).get_settlement(UUID(payment["id"]))
    assert stored == Settlement(
        id=UUID(payment["id"]),
        group_id=UUID(trip["id"]),
        from_member_id=UUID(bob["id"]),
        to_member_id=UUID(alice["id"]),
        amount_minor=300,
        occurred_at=datetime.fromisoformat(OCCURRED),
        created_at=datetime.fromisoformat(payment["created_at"]),
        created_by_user_id=DEVELOPMENT_ACTOR.id,
    )
    assert client.get(f"{base}/settlements").json() == [payment]
    assert balances(client, trip["id"]) == {
        alice["id"]: 300,
        bob["id"]: 0,
        charlie["id"]: -300,
    }
    assert client.get(f"{base}/settlement-suggestions").json()["suggestions"] == [
        {
            "from_member_id": charlie["id"],
            "from_display_name": "Charlie",
            "to_member_id": alice["id"],
            "to_display_name": "Alice",
            "amount": 300,
        }
    ]


@pytest.mark.parametrize(("amount", "bob_balance"), [(100, -200), (400, 100)])
def test_partial_and_overpayments_are_actual_history(
    client: TestClient, amount: int, bob_balance: int
) -> None:
    trip = group(client)
    alice, bob = (member(client, trip["id"], name) for name in ("Alice", "Bob"))
    response = client.post(
        f"/api/v1/groups/{trip['id']}/expenses",
        json=equal_payload(alice["id"], [alice["id"], bob["id"]], 600),
    )
    assert response.status_code == 201, response.text
    response = client.post(
        f"/api/v1/groups/{trip['id']}/settlements",
        json=settlement_payload(bob["id"], alice["id"], amount),
    )
    assert response.status_code == 201, response.text
    assert balances(client, trip["id"]) == {
        alice["id"]: -bob_balance,
        bob["id"]: bob_balance,
    }


@pytest.mark.parametrize("amount", [0, -1, 1.5, True, "300", 2**63])
def test_settlement_invalid_amounts_leave_no_history(
    client: TestClient, amount: object, db_session: Session
) -> None:
    trip = group(client)
    alice, bob = (member(client, trip["id"], name) for name in ("Alice", "Bob"))
    base = f"/api/v1/groups/{trip['id']}/settlements"
    assert (
        client.post(
            base, json=settlement_payload(bob["id"], alice["id"], amount)
        ).status_code
        == 422
    )
    assert client.get(base).json() == []
    assert db_session.get(UserRow, DEVELOPMENT_ACTOR.id) is None


def test_settlement_transport_and_same_member_validation(client: TestClient) -> None:
    trip = group(client)
    alice, bob = (member(client, trip["id"], name) for name in ("Alice", "Bob"))
    payload = settlement_payload(bob["id"], alice["id"])
    base = f"/api/v1/groups/{trip['id']}/settlements"
    for invalid in (
        {**payload, "to_member_id": bob["id"]},
        {**payload, "occurred_at": "2026-10-03T12:30:00"},
        {**payload, "created_at": OCCURRED},
        {**payload, "created_by_user_id": str(uuid4())},
        {**payload, "from_member_id": "not-a-uuid"},
    ):
        assert client.post(base, json=invalid).status_code == 422
    assert client.get(base).json() == []


@pytest.mark.parametrize("side", ["from_member_id", "to_member_id"])
def test_settlement_missing_and_cross_group_members_rejected(
    client: TestClient, side: str
) -> None:
    trip, other = group(client), group(client, "Other")
    alice, bob = (member(client, trip["id"], name) for name in ("Alice", "Bob"))
    foreign = member(client, other["id"], "Foreign")
    base = f"/api/v1/groups/{trip['id']}/settlements"
    for member_id in (str(uuid4()), foreign["id"]):
        payload = {**settlement_payload(bob["id"], alice["id"]), side: member_id}
        assert client.post(base, json=payload).status_code == 404
    assert client.get(base).json() == []
    assert client.get(f"/api/v1/groups/{uuid4()}/settlements").status_code == 404
    assert (
        client.post(
            f"/api/v1/groups/{uuid4()}/settlements",
            json=settlement_payload(bob["id"], alice["id"]),
        ).status_code
        == 404
    )


def test_multiple_payments_history_order_and_stale_suggestion(
    client: TestClient,
) -> None:
    trip = group(client)
    alice, bob = (member(client, trip["id"], name) for name in ("Alice", "Bob"))
    base = f"/api/v1/groups/{trip['id']}"
    client.post(
        f"{base}/expenses",
        json=equal_payload(alice["id"], [alice["id"], bob["id"]], 600),
    )
    stale = client.get(f"{base}/settlement-suggestions").json()["suggestions"][0]
    assert stale["amount"] == 300
    recorded = []
    for amount, when in (
        (100, OCCURRED),
        (100, OCCURRED),
        (stale["amount"], "2026-10-04T12:30:00+08:00"),
    ):
        response = client.post(
            f"{base}/settlements",
            json={
                **settlement_payload(bob["id"], alice["id"], amount),
                "occurred_at": when,
            },
        )
        assert response.status_code == 201, response.text
        recorded.append(response.json())
    history = client.get(f"{base}/settlements").json()
    assert [item["id"] for item in history] == [
        recorded[2]["id"],
        *sorted([recorded[0]["id"], recorded[1]["id"]], reverse=True),
    ]
    assert client.get(f"{base}/settlements").json() == history
    assert balances(client, trip["id"]) == {alice["id"]: -200, bob["id"]: 200}
    assert balances(client, trip["id"]) == {alice["id"]: -200, bob["id"]: 200}
    other = group(client, "Other")
    assert client.get(f"/api/v1/groups/{other['id']}/settlements").json() == []


def test_failed_settlement_flush_rolls_back_payment_and_actor(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip = group(client)
    alice, bob = (member(client, trip["id"], name) for name in ("Alice", "Bob"))
    save = LedgerRepository.save_settlement

    def fail_after_flush(repo: LedgerRepository, settlement: Settlement) -> None:
        save(repo, settlement)
        raise IntegrityError(
            "private statement", None, Exception("private database error")
        )

    monkeypatch.setattr(LedgerRepository, "save_settlement", fail_after_flush)
    response = client.post(
        f"/api/v1/groups/{trip['id']}/settlements",
        json=settlement_payload(bob["id"], alice["id"]),
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "database constraint violation"}
    assert client.get(f"/api/v1/groups/{trip['id']}/settlements").json() == []
    assert db_session.get(UserRow, DEVELOPMENT_ACTOR.id) is None
    assert balances(client, trip["id"]) == {alice["id"]: 0, bob["id"]: 0}


@pytest.fixture
def correction_trip(client: TestClient) -> tuple[str, list[str], dict, dict]:
    gid = group(client)["id"]
    ids = [member(client, gid, name)["id"] for name in ("Alice", "Bob", "Charlie")]
    expense = client.post(
        f"/api/v1/groups/{gid}/expenses", json=equal_payload(ids[0], ids)
    ).json()
    payment = {
        "from_member_id": ids[1],
        "to_member_id": ids[0],
        "amount": 300,
        "occurred_at": OCCURRED,
    }
    return gid, ids, expense, payment


def test_expense_void_keeps_original_and_restores_empty_ledger(client, correction_trip):
    gid, ids, original, _ = correction_trip
    assert balances(client, gid) == dict(zip(ids, (600, -300, -300), strict=True))
    path = f"/api/v1/groups/{gid}/expenses/{original['id']}"
    response = client.post(path + "/void", json={"reason": "Wrong receipt"})
    assert response.status_code == 200, response.text
    voided = response.json()
    assert voided["status"] == "voided"
    assert voided["void_reason"] == "Wrong receipt"
    assert voided["void_created_by_user_id"] == str(DEVELOPMENT_ACTOR.id)
    assert voided["void_created_at"]
    assert voided["amount"] == original["amount"]
    assert voided["splits"] == original["splits"]
    assert client.get(path).json() == voided
    assert client.get(f"/api/v1/groups/{gid}/expenses").json() == [voided]
    assert balances(client, gid) == dict.fromkeys(ids, 0)
    assert (
        client.get(f"/api/v1/groups/{gid}/settlement-suggestions").json()["suggestions"]
        == []
    )
    assert client.post(path + "/void", json={"reason": "Again"}).status_code == 409
    assert (
        client.post(
            path + "/corrections",
            json={"reason": "Again", "replacement": equal_payload(ids[0], ids)},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("strategy", ["equal", "exact"])
def test_expense_correction_and_chain_preserve_original_splits(
    client, correction_trip, strategy
):
    gid, ids, original, _ = correction_trip
    path = f"/api/v1/groups/{gid}/expenses"
    payload = equal_payload(ids[0], ids, 990)
    if strategy == "exact":
        payload.pop("participant_member_ids")
        payload.update(
            split_strategy="exact",
            splits=[{"member_id": mid, "amount": 330} for mid in ids],
        )
    response = client.post(
        f"{path}/{original['id']}/corrections",
        json={"reason": "Receipt total", "replacement": payload},
    )
    assert response.status_code == 201, response.text
    replacement = response.json()
    assert replacement["id"] != original["id"]
    assert replacement["created_at"] != original["created_at"]
    assert replacement["replaces_id"] == original["id"]
    assert replacement["status"] == "active"
    assert replacement["split_strategy"] == strategy
    assert balances(client, gid) == dict(zip(ids, (660, -330, -330), strict=True))
    stored = client.get(f"{path}/{original['id']}").json()
    for field in (
        "amount",
        "splits",
        "description",
        "payer_member_id",
        "occurred_at",
        "created_at",
    ):
        assert stored[field] == original[field]
    assert stored["status"] == "voided"
    assert stored["replaced_by_id"] == replacement["id"]
    assert (
        client.post(
            f"{path}/{original['id']}/corrections",
            json={"reason": "Again", "replacement": payload},
        ).status_code
        == 409
    )
    third = client.post(
        f"{path}/{replacement['id']}/corrections",
        json={
            "reason": "Second correction",
            "replacement": equal_payload(ids[0], ids, 1200),
        },
    ).json()
    middle = client.get(f"{path}/{replacement['id']}").json()
    assert middle["status"] == "voided"
    assert middle["replaces_id"] == original["id"]
    assert middle["replaced_by_id"] == third["id"]
    assert third["replaces_id"] == replacement["id"]
    assert len(client.get(path).json()) == 3
    assert balances(client, gid) == dict(zip(ids, (800, -400, -400), strict=True))
    assert (
        client.post(
            f"{path}/{third['id']}/void", json={"reason": "Remove event"}
        ).status_code
        == 200
    )
    assert balances(client, gid) == dict.fromkeys(ids, 0)


def test_settlement_void_restores_pre_payment_balances(client, correction_trip):
    gid, ids, _, payload = correction_trip
    path = f"/api/v1/groups/{gid}/settlements"
    original = client.post(path, json=payload).json()
    assert balances(client, gid) == dict(zip(ids, (300, 0, -300), strict=True))
    response = client.post(
        f"{path}/{original['id']}/void", json={"reason": "Payment never happened"}
    )
    assert response.status_code == 200, response.text
    voided = response.json()
    assert voided["status"] == "voided"
    assert voided["amount"] == 300
    assert voided["created_at"] == original["created_at"]
    assert voided["void_created_by_user_id"] == str(DEVELOPMENT_ACTOR.id)
    assert client.get(path).json() == [voided]
    assert balances(client, gid) == dict(zip(ids, (600, -300, -300), strict=True))
    assert sorted(
        item["amount"]
        for item in client.get(f"/api/v1/groups/{gid}/settlement-suggestions").json()[
            "suggestions"
        ]
    ) == [300, 300]
    assert (
        client.post(
            f"{path}/{original['id']}/void", json={"reason": "Again"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{path}/{original['id']}/corrections",
            json={"reason": "Again", "replacement": payload},
        ).status_code
        == 409
    )


def test_settlement_correction_amount_and_members_chain(client, correction_trip):
    gid, ids, _, payload = correction_trip
    path = f"/api/v1/groups/{gid}/settlements"
    original = client.post(path, json=payload).json()
    response = client.post(
        f"{path}/{original['id']}/corrections",
        json={"reason": "Only paid 200", "replacement": {**payload, "amount": 200}},
    )
    assert response.status_code == 201, response.text
    replacement = response.json()
    assert replacement["id"] != original["id"]
    assert replacement["replaces_id"] == original["id"]
    assert balances(client, gid) == dict(zip(ids, (400, -100, -300), strict=True))
    third = client.post(
        f"{path}/{replacement['id']}/corrections",
        json={
            "reason": "Wrong travelers",
            "replacement": {
                **payload,
                "from_member_id": ids[0],
                "to_member_id": ids[2],
                "amount": 100,
            },
        },
    ).json()
    history = {item["id"]: item for item in client.get(path).json()}
    assert history[original["id"]]["amount"] == 300
    assert history[original["id"]]["status"] == "voided"
    assert history[original["id"]]["replaced_by_id"] == replacement["id"]
    assert history[replacement["id"]]["status"] == "voided"
    assert history[replacement["id"]]["replaced_by_id"] == third["id"]
    assert third["status"] == "active"
    assert balances(client, gid) == dict(zip(ids, (700, -300, -400), strict=True))
    assert (
        client.post(f"{path}/{third['id']}/void", json={"reason": "Remove"}).status_code
        == 200
    )
    assert balances(client, gid) == dict(zip(ids, (600, -300, -300), strict=True))


@pytest.mark.parametrize("kind", ["expenses", "settlements"])
@pytest.mark.parametrize("operation", ["void", "corrections"])
def test_void_and_correction_scope_and_missing_targets(
    client, correction_trip, kind, operation
):
    gid, _, expense, payment = correction_trip
    target = (
        expense
        if kind == "expenses"
        else client.post(f"/api/v1/groups/{gid}/settlements", json=payment).json()
    )
    replacement = (
        equal_payload(
            expense["payer_member_id"],
            [split["member_id"] for split in expense["splits"]],
        )
        if kind == "expenses"
        else payment
    )
    request = {"reason": "Wrong group"}
    if operation == "corrections":
        request["replacement"] = replacement
    other_gid = group(client, "Other")["id"]
    for scoped_gid, target_id in [
        (other_gid, target["id"]),
        (gid, str(uuid4())),
        (str(uuid4()), target["id"]),
    ]:
        response = client.post(
            f"/api/v1/groups/{scoped_gid}/{kind}/{target_id}/{operation}", json=request
        )
        assert response.status_code == 404, response.text
    assert balances(client, gid)[expense["payer_member_id"]] == (
        600 if kind == "expenses" else 300
    )


@pytest.mark.parametrize("kind", ["expenses", "settlements"])
@pytest.mark.parametrize(
    "invalid", ["blank_reason", "amount", "financial", "partial", "naive_time"]
)
def test_invalid_correction_rolls_back(client, correction_trip, kind, invalid):
    gid, ids, expense, payment = correction_trip
    target = (
        expense
        if kind == "expenses"
        else client.post(f"/api/v1/groups/{gid}/settlements", json=payment).json()
    )
    replacement = (
        equal_payload(ids[0], ids, 990)
        if kind == "expenses"
        else {**payment, "amount": 200}
    )
    request = {"reason": "Fix", "replacement": replacement}
    if invalid == "blank_reason":
        request["reason"] = "  "
    elif invalid == "amount":
        replacement["amount"] = 0
    elif invalid == "financial":
        if kind == "expenses":
            replacement["participant_member_ids"] = [ids[0], ids[0]]
        else:
            replacement["to_member_id"] = replacement["from_member_id"]
    elif invalid == "partial":
        request["replacement"] = {"amount": 990}
    else:
        replacement["occurred_at"] = "2026-10-03T12:00:00"
    path = f"/api/v1/groups/{gid}/{kind}"
    response = client.post(f"{path}/{target['id']}/corrections", json=request)
    assert response.status_code == 422, response.text
    assert client.get(path).json() == [target]


@pytest.mark.parametrize("kind", ["expense", "settlement"])
@pytest.mark.parametrize("stage", ["replacement", "void"])
def test_correction_failure_after_flush_is_atomic(
    client, correction_trip, monkeypatch, kind, stage
):
    gid, ids, expense, payment = correction_trip
    target = (
        expense
        if kind == "expense"
        else client.post(f"/api/v1/groups/{gid}/settlements", json=payment).json()
    )
    path = f"/api/v1/groups/{gid}/{kind}s"
    replacement = (
        equal_payload(ids[0], ids, 990)
        if kind == "expense"
        else {**payment, "amount": 200}
    )
    before_balances = balances(client, gid)
    method_name = f"save_{kind}" + ("_void" if stage == "void" else "")
    original_save = getattr(LedgerRepository, method_name)

    def fail_after_flush(self, value):
        original_save(self, value)
        raise IntegrityError("forced failure", {}, Exception("test rollback"))

    monkeypatch.setattr(LedgerRepository, method_name, fail_after_flush)
    response = client.post(
        f"{path}/{target['id']}/corrections",
        json={"reason": "Fix", "replacement": replacement},
    )
    assert response.status_code == 422
    assert client.get(path).json() == [target]
    assert balances(client, gid) == before_balances
    assert client.get(f"/api/v1/groups/{gid}/settlement-suggestions").status_code == 200


@pytest.mark.parametrize("kind", ["expense", "settlement"])
@pytest.mark.parametrize("operation", ["void", "corrections"])
def test_stale_active_check_duplicate_void_maps_to_conflict(
    client, correction_trip, monkeypatch, kind, operation
):
    gid, ids, expense, payment = correction_trip
    target = (
        expense
        if kind == "expense"
        else client.post(f"/api/v1/groups/{gid}/settlements", json=payment).json()
    )
    path = f"/api/v1/groups/{gid}/{kind}s"
    assert (
        client.post(f"{path}/{target['id']}/void", json={"reason": "First"}).status_code
        == 200
    )
    before = client.get(path).json()
    # Simulate a stale read; real PostgreSQL then rejects the duplicate PK.
    monkeypatch.setattr(LedgerRepository, f"get_{kind}_void", lambda *_: None)
    request = {"reason": "Competing attempt"}
    if operation == "corrections":
        request["replacement"] = (
            equal_payload(ids[0], ids, 990)
            if kind == "expense"
            else {**payment, "amount": 200}
        )
    response = client.post(f"{path}/{target['id']}/{operation}", json=request)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "record already voided or corrected"
    assert client.get(path).json() == before


@pytest.mark.parametrize("kind", ["expenses", "settlements"])
def test_blank_void_reason_keeps_record_active(client, correction_trip, kind):
    gid, _, expense, payment = correction_trip
    target = (
        expense
        if kind == "expenses"
        else client.post(f"/api/v1/groups/{gid}/settlements", json=payment).json()
    )
    path = f"/api/v1/groups/{gid}/{kind}"
    assert (
        client.post(f"{path}/{target['id']}/void", json={"reason": "  "}).status_code
        == 422
    )
    assert client.get(path).json() == [target]
