from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.accounting import (
    AccountingValidationError,
    allocate_equal,
    calculate_balances,
    validate_exact_splits,
    validate_expense,
    validate_settlement,
)
from app.domain import (
    Expense,
    ExpenseSplit,
    Group,
    GroupMember,
    Settlement,
    SplitStrategy,
)

A, B, C, D = (UUID(int=value) for value in range(1, 5))
ACTOR = UUID(int=99)
DEFAULT_EXPENSE_ID = UUID(int=1000)
DEFAULT_SETTLEMENT_ID = UUID(int=2000)
WHEN = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def context() -> tuple[Group, tuple[GroupMember, ...]]:
    group = Group(id=UUID(int=100), name="Trip")
    members = tuple(
        GroupMember(id=member_id, group_id=group.id, display_name=str(member_id))
        for member_id in (A, B, C, D)
    )
    return group, members


def expense(
    group: Group,
    payer: UUID,
    splits: tuple[ExpenseSplit, ...],
    *,
    amount: int = 900,
    strategy: SplitStrategy = SplitStrategy.EXACT,
    record_id: UUID = DEFAULT_EXPENSE_ID,
) -> Expense:
    return Expense(
        id=record_id,
        group_id=group.id,
        description="Dinner",
        amount_minor=amount,
        payer_member_id=payer,
        split_strategy=strategy,
        splits=splits,
        occurred_at=WHEN,
        created_at=WHEN,
        created_by_user_id=ACTOR,
    )


def settlement(
    group: Group,
    sender: UUID,
    recipient: UUID,
    amount: int,
    *,
    record_id: UUID = DEFAULT_SETTLEMENT_ID,
) -> Settlement:
    return Settlement(
        id=record_id,
        group_id=group.id,
        from_member_id=sender,
        to_member_id=recipient,
        amount_minor=amount,
        occurred_at=WHEN,
        created_at=WHEN,
        created_by_user_id=ACTOR,
    )


def amounts(splits: tuple[ExpenseSplit, ...]) -> dict[UUID, int]:
    return {split.member_id: split.amount_minor for split in splits}


@pytest.mark.parametrize(
    ("amount", "participants", "expected"),
    [
        (900, (A, B, C), {A: 300, B: 300, C: 300}),
        (100, (A, B, C), {A: 34, B: 33, C: 33}),
        (5, (A, B, C), {A: 2, B: 2, C: 1}),
        (7, (B,), {B: 7}),
        (2, (A, B, C), {A: 1, B: 1, C: 0}),
    ],
)
def test_equal_allocation_cases(
    amount: int, participants: tuple[UUID, ...], expected: dict[UUID, int]
) -> None:
    result = allocate_equal(amount, participants)

    assert amounts(result) == expected
    assert sum(split.amount_minor for split in result) == amount
    assert len(result) == len(participants)


def test_equal_allocation_is_independent_of_input_order() -> None:
    assert allocate_equal(100, (C, A, B)) == allocate_equal(100, (A, B, C))


@pytest.mark.parametrize("participants", [(), (A, A)])
def test_equal_rejects_empty_or_duplicate_participants(
    participants: tuple[UUID, ...],
) -> None:
    with pytest.raises(AccountingValidationError):
        allocate_equal(100, participants)


@pytest.mark.parametrize("amount", [0, -1, 1.5, True])
def test_equal_rejects_invalid_amount(amount: object) -> None:
    with pytest.raises(AccountingValidationError):
        allocate_equal(amount, (A,))


def test_exact_accepts_final_allocations() -> None:
    splits = (
        ExpenseSplit(C, 100),
        ExpenseSplit(A, 500),
        ExpenseSplit(B, 300),
    )

    assert validate_exact_splits(900, splits) == (
        ExpenseSplit(A, 500),
        ExpenseSplit(B, 300),
        ExpenseSplit(C, 100),
    )


@pytest.mark.parametrize("total", [899, 901])
def test_exact_rejects_total_too_low_or_high(total: int) -> None:
    with pytest.raises(AccountingValidationError, match="total"):
        validate_exact_splits(900, (ExpenseSplit(A, total),))


def test_exact_allows_zero_allocation() -> None:
    result = validate_exact_splits(900, (ExpenseSplit(A, 900), ExpenseSplit(B, 0)))

    assert amounts(result) == {A: 900, B: 0}


@pytest.mark.parametrize(
    "splits",
    [(), (ExpenseSplit(A, 450), ExpenseSplit(A, 450))],
)
def test_exact_rejects_empty_or_duplicate_splits(
    splits: tuple[ExpenseSplit, ...],
) -> None:
    with pytest.raises(AccountingValidationError):
        validate_exact_splits(900, splits)


def test_exact_rejects_malformed_split_values() -> None:
    with pytest.raises(AccountingValidationError):
        validate_exact_splits(900, ("not a split",))


@pytest.mark.parametrize("amount", [0, -1, 1.5, True])
def test_exact_rejects_invalid_expense_amount(amount: object) -> None:
    with pytest.raises(AccountingValidationError):
        validate_exact_splits(amount, (ExpenseSplit(A, 1),))


def test_context_accepts_payer_outside_participants() -> None:
    group, members = context()
    record = expense(group, A, (ExpenseSplit(B, 450), ExpenseSplit(C, 450)))

    validate_expense(group, members, record)
    assert calculate_balances(group, members, (record,), ()) == {
        A: 900,
        B: -450,
        C: -450,
        D: 0,
    }


def test_context_accepts_canonical_equal_splits() -> None:
    group, members = context()
    record = expense(
        group,
        A,
        allocate_equal(100, (C, A, B)),
        amount=100,
        strategy=SplitStrategy.EQUAL,
    )

    validate_expense(group, members, record)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"payer_member_id": UUID(int=999)}, "payer"),
        ({"group_id": UUID(int=101)}, "different group"),
        ({"splits": (ExpenseSplit(UUID(int=999), 900),)}, "participant"),
        ({"splits": (ExpenseSplit(B, 450), ExpenseSplit(B, 450))}, "unique"),
        ({"splits": ()}, "at least one"),
        ({"splits": (ExpenseSplit(B, 100),)}, "total"),
    ],
)
def test_context_rejects_invalid_expense(
    change: dict[str, object], message: str
) -> None:
    group, members = context()
    record = replace(expense(group, A, (ExpenseSplit(B, 900),)), **change)

    with pytest.raises(AccountingValidationError, match=message):
        validate_expense(group, members, record)


def test_context_rejects_noncanonical_equal_remainder() -> None:
    group, members = context()
    record = expense(
        group,
        A,
        (ExpenseSplit(A, 33), ExpenseSplit(B, 34), ExpenseSplit(C, 33)),
        amount=100,
        strategy=SplitStrategy.EQUAL,
    )

    with pytest.raises(AccountingValidationError, match="deterministic"):
        validate_expense(group, members, record)


def test_context_rejects_foreign_or_duplicate_members() -> None:
    group, members = context()
    record = expense(group, A, (ExpenseSplit(B, 900),))

    with pytest.raises(AccountingValidationError, match="different group"):
        validate_expense(
            group, (*members, GroupMember(UUID(int=999), UUID(int=101), "X")), record
        )
    with pytest.raises(AccountingValidationError, match="unique"):
        validate_expense(group, (*members, members[0]), record)


def test_one_expense_balance_signs_and_zero_member() -> None:
    group, members = context()
    record = expense(
        group, A, (ExpenseSplit(A, 300), ExpenseSplit(B, 300), ExpenseSplit(C, 300))
    )

    balances = calculate_balances(group, members, (record,), ())

    assert balances == {A: 600, B: -300, C: -300, D: 0}
    assert sum(balances.values()) == 0


def test_multiple_expenses_with_different_payers() -> None:
    group, members = context()
    first = expense(
        group, A, (ExpenseSplit(A, 300), ExpenseSplit(B, 300), ExpenseSplit(C, 300))
    )
    second = expense(
        group,
        B,
        (ExpenseSplit(A, 100), ExpenseSplit(B, 100)),
        amount=200,
        record_id=UUID(int=1001),
    )

    expected = {A: 500, B: -200, C: -300, D: 0}
    assert calculate_balances(group, members, (first, second), ()) == expected
    assert calculate_balances(group, members, (first, second), ()) == expected


def test_full_settlement_sender_increases_and_recipient_decreases() -> None:
    group, members = context()
    record = expense(
        group, A, (ExpenseSplit(A, 300), ExpenseSplit(B, 300), ExpenseSplit(C, 300))
    )
    transfer = settlement(group, B, A, 300)

    assert calculate_balances(group, members, (record,), (transfer,)) == {
        A: 300,
        B: 0,
        C: -300,
        D: 0,
    }


def test_partial_and_multiple_settlements() -> None:
    group, members = context()
    record = expense(group, A, (ExpenseSplit(B, 300), ExpenseSplit(C, 600)))
    transfers = (
        settlement(group, B, A, 100),
        settlement(group, B, A, 200, record_id=UUID(int=2001)),
        settlement(group, C, A, 300, record_id=UUID(int=2002)),
    )

    assert calculate_balances(group, members, (record,), transfers) == {
        A: 300,
        B: 0,
        C: -300,
        D: 0,
    }
    assert calculate_balances(group, members, (record,), transfers[:1])[B] == -200


def test_overpayment_can_reverse_balance_direction() -> None:
    group, members = context()
    record = expense(group, A, (ExpenseSplit(B, 300), ExpenseSplit(C, 600)))

    balances = calculate_balances(
        group, members, (record,), (settlement(group, B, A, 400),)
    )

    assert balances == {A: 500, B: 100, C: -600, D: 0}
    assert sum(balances.values()) == 0


def test_valid_settlement_preserves_group_total() -> None:
    group, members = context()
    before = calculate_balances(group, members, (), ())
    transfer = settlement(group, B, A, 100)

    validate_settlement(group, members, transfer)
    after = calculate_balances(group, members, (), (transfer,))
    assert before == {A: 0, B: 0, C: 0, D: 0}
    assert after == {A: -100, B: 100, C: 0, D: 0}
    assert sum(after.values()) == sum(before.values()) == 0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"group_id": UUID(int=101)}, "different group"),
        ({"from_member_id": UUID(int=999)}, "sender"),
        ({"to_member_id": UUID(int=999)}, "recipient"),
    ],
)
def test_cross_group_or_unknown_settlement_rejected(
    change: dict[str, object], message: str
) -> None:
    group, members = context()
    record = replace(settlement(group, B, A, 100), **change)

    with pytest.raises(AccountingValidationError, match=message):
        calculate_balances(group, members, (), (record,))


def test_malformed_history_rejected_before_returning_balances() -> None:
    group, members = context()
    valid = expense(group, A, (ExpenseSplit(B, 900),))
    invalid = replace(valid, splits=(ExpenseSplit(B, 800),), id=UUID(int=1001))

    with pytest.raises(AccountingValidationError, match="total"):
        calculate_balances(group, members, (valid, invalid), ())
    with pytest.raises(AccountingValidationError, match="more than once"):
        calculate_balances(group, members, (valid, valid), ())


def test_duplicate_settlement_history_is_rejected() -> None:
    group, members = context()
    transfer = settlement(group, B, A, 100)

    with pytest.raises(AccountingValidationError, match="more than once"):
        calculate_balances(group, members, (), (transfer, transfer))


@given(
    amount=st.integers(min_value=1, max_value=10_000),
    participant_numbers=st.lists(
        st.integers(min_value=1, max_value=10), min_size=1, max_size=10, unique=True
    ),
)
def test_equal_allocation_properties(
    amount: int, participant_numbers: list[int]
) -> None:
    ids = tuple(UUID(int=number) for number in participant_numbers)
    result = allocate_equal(amount, ids)
    values = [split.amount_minor for split in result]

    assert sum(values) == amount
    assert min(values) >= 0
    assert max(values) - min(values) <= 1
    assert amounts(result) == amounts(allocate_equal(amount, reversed(ids)))


@settings(max_examples=80)
@given(
    expense_specs=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=3),
            st.integers(min_value=1, max_value=1000),
            st.lists(
                st.integers(min_value=0, max_value=3),
                min_size=1,
                max_size=4,
                unique=True,
            ),
        ),
        max_size=12,
    ),
    settlement_specs=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=3),
            st.integers(min_value=1, max_value=3),
            st.integers(min_value=1, max_value=1000),
        ),
        max_size=12,
    ),
)
def test_generated_valid_histories_always_sum_to_zero(
    expense_specs: list[tuple[int, int, list[int]]],
    settlement_specs: list[tuple[int, int, int]],
) -> None:
    group, members = context()
    member_ids = (A, B, C, D)
    expenses = tuple(
        expense(
            group,
            member_ids[payer_index],
            allocate_equal(
                amount, (member_ids[index] for index in participant_indexes)
            ),
            amount=amount,
            strategy=SplitStrategy.EQUAL,
            record_id=UUID(int=1000 + index),
        )
        for index, (payer_index, amount, participant_indexes) in enumerate(
            expense_specs
        )
    )
    settlements = tuple(
        settlement(
            group,
            member_ids[sender_index],
            member_ids[(sender_index + offset) % 4],
            amount,
            record_id=UUID(int=2000 + index),
        )
        for index, (sender_index, offset, amount) in enumerate(settlement_specs)
    )

    balances = calculate_balances(group, members, expenses, settlements)

    assert set(balances) == set(member_ids)
    assert sum(balances.values()) == 0
