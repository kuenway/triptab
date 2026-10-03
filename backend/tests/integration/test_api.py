"""Exercise the public API through FastAPI, PostgreSQL, and accounting."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.application.service import DEVELOPMENT_ACTOR
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
