"""Suggestions settle zero-sum balances without recording payments."""

from dataclasses import FrozenInstanceError
from itertools import permutations
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.accounting import AccountingValidationError, suggest_settlements
from app.domain import DomainValidationError, SettlementSuggestion

A, B, C, D, E = (UUID(int=value) for value in range(1, 6))


def assert_settles(
    balances: dict[UUID, int], suggestions: tuple[SettlementSuggestion, ...]
) -> None:
    remaining = balances.copy()
    for suggestion in suggestions:
        sender, recipient = suggestion.from_member_id, suggestion.to_member_id
        assert type(suggestion.amount) is int and suggestion.amount > 0
        assert sender in balances and recipient in balances
        assert sender != recipient
        assert balances[sender] < 0 < balances[recipient]
        remaining[sender] += suggestion.amount
        remaining[recipient] -= suggestion.amount
        assert sum(remaining.values()) == 0
    assert all(amount == 0 for amount in remaining.values())


@pytest.mark.parametrize(
    ("balances", "expected"),
    [
        ({A: 300, B: -300}, ((B, A, 300),)),
        ({A: 600, B: -200, C: -400}, ((C, A, 400), (B, A, 200))),
        ({A: 200, B: 400, C: -600}, ((C, B, 400), (C, A, 200))),
        (
            {A: 600, B: 400, C: -700, D: -300, E: 0},
            ((C, A, 600), (C, B, 100), (D, B, 300)),
        ),
        ({A: 0, B: 0}, ()),
        ({}, ()),
    ],
)
def test_basic_suggestion_plans(
    balances: dict[UUID, int], expected: tuple[tuple[UUID, UUID, int], ...]
) -> None:
    original = balances.copy()
    suggestions = suggest_settlements(balances)
    assert suggestions == tuple(SettlementSuggestion(*value) for value in expected)
    assert suggestions == suggest_settlements(balances)
    assert_settles(balances, suggestions)
    assert balances == original


@pytest.mark.parametrize(
    ("balances", "expected"),
    [
        ({B: 300, A: 300, C: -600}, ((C, A, 300), (C, B, 300))),
        ({C: -300, B: -300, A: 600}, ((B, A, 300), (C, A, 300))),
        ({D: -300, C: -300, B: 300, A: 300}, ((C, A, 300), (D, B, 300))),
    ],
)
def test_uuid_ties_and_every_input_order(
    balances: dict[UUID, int], expected: tuple[tuple[UUID, UUID, int], ...]
) -> None:
    for order in permutations(balances):
        reordered = {member_id: balances[member_id] for member_id in order}
        assert suggest_settlements(reordered) == tuple(
            SettlementSuggestion(*value) for value in expected
        )


@pytest.mark.parametrize("balances", [{A: 1}, {A: 600, B: -599}, {A: -1}])
def test_nonzero_total_is_rejected(balances: dict[UUID, int]) -> None:
    with pytest.raises(AccountingValidationError, match="total zero"):
        suggest_settlements(balances)


@pytest.mark.parametrize("amount", [True, 0.5, "1", None])
def test_balances_require_integer_ntd(amount: object) -> None:
    with pytest.raises(AccountingValidationError, match="integer NTD"):
        suggest_settlements({A: amount})


def test_balances_require_uuid_members() -> None:
    with pytest.raises(AccountingValidationError, match="UUID"):
        suggest_settlements({"Alice": 0})


@pytest.mark.parametrize("amount", [0, -1, True, 0.5])
def test_suggestion_requires_positive_integer_ntd(amount: object) -> None:
    with pytest.raises(DomainValidationError):
        SettlementSuggestion(A, B, amount)


def test_suggestion_is_an_immutable_value_with_distinct_uuid_members() -> None:
    suggestion = SettlementSuggestion(A, B, 300)
    with pytest.raises(FrozenInstanceError):
        suggestion.amount = 100
    with pytest.raises(DomainValidationError):
        SettlementSuggestion(A, A, 300)
    with pytest.raises(DomainValidationError):
        SettlementSuggestion("Alice", B, 300)
    with pytest.raises(DomainValidationError):
        SettlementSuggestion(A, "Bob", 300)


@settings(max_examples=150)
@given(
    values=st.lists(st.integers(min_value=-10_000, max_value=10_000), max_size=10),
    data=st.data(),
)
def test_generated_zero_sum_balance_properties(
    values: list[int], data: st.DataObject
) -> None:
    balances = {UUID(int=index + 1): amount for index, amount in enumerate(values)}
    balances[UUID(int=len(values) + 1)] = -sum(values)
    original = tuple(balances.items())
    suggestions = suggest_settlements(balances)

    assert_settles(balances, suggestions)
    order = data.draw(st.permutations(tuple(balances)))
    reordered = {member_id: balances[member_id] for member_id in order}
    assert suggest_settlements(reordered) == suggestions
    assert tuple(balances.items()) == original
