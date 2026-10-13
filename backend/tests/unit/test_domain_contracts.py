from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.domain import (
    DomainValidationError,
    Expense,
    ExpenseSplit,
    Group,
    GroupMember,
    Settlement,
    SplitStrategy,
    User,
)


def aware_time() -> datetime:
    return datetime(2026, 10, 3, 12, 0, tzinfo=timezone(timedelta(hours=8)))


def expense() -> Expense:
    return Expense(
        id=uuid4(),
        group_id=uuid4(),
        description="Dinner",
        amount_minor=900,
        payer_member_id=uuid4(),
        split_strategy=SplitStrategy.EQUAL,
        splits=(ExpenseSplit(member_id=uuid4(), amount_minor=900),),
        occurred_at=aware_time(),
        created_at=aware_time(),
        created_by_user_id=uuid4(),
    )


def settlement() -> Settlement:
    return Settlement(
        id=uuid4(),
        group_id=uuid4(),
        from_member_id=uuid4(),
        to_member_id=uuid4(),
        amount_minor=300,
        occurred_at=aware_time(),
        created_at=aware_time(),
        created_by_user_id=uuid4(),
    )


def test_user_represents_application_identity() -> None:
    user = User(id=uuid4(), email="a@example.com", display_name="Alice")

    assert user.email == "a@example.com"
    assert user.display_name == "Alice"


def test_required_text_cannot_be_blank() -> None:
    with pytest.raises(DomainValidationError):
        User(id=uuid4(), email="  ", display_name="Alice")
    with pytest.raises(DomainValidationError):
        Group(id=uuid4(), name="  ")
    with pytest.raises(DomainValidationError):
        replace(expense(), description="  ")


def test_group_is_twd_with_integer_ntd_scale() -> None:
    group = Group(id=uuid4(), name="Trip")

    assert (group.currency, group.currency_scale) == ("TWD", 0)
    with pytest.raises(DomainValidationError):
        replace(group, currency="USD")
    with pytest.raises(DomainValidationError):
        replace(group, currency_scale=2)


def test_registered_and_guest_members_have_stable_financial_ids() -> None:
    user = User(id=uuid4(), email="a@example.com", display_name="Alice")
    group_id = uuid4()
    registered = GroupMember(
        id=uuid4(), group_id=group_id, display_name="Alice", user_id=user.id
    )
    guest = GroupMember(id=uuid4(), group_id=group_id, display_name="Bob")

    assert registered.user_id == user.id
    assert not registered.is_guest
    assert guest.user_id is None
    assert guest.is_guest
    assert registered.id != user.id


@pytest.mark.parametrize("strategy", [SplitStrategy.EQUAL, SplitStrategy.EXACT])
def test_expense_representations_support_both_initial_strategies(
    strategy: SplitStrategy,
) -> None:
    record = replace(expense(), split_strategy=strategy)

    assert record.split_strategy is strategy
    assert record.amount_minor == 900


def test_expense_payer_can_be_outside_split_participants() -> None:
    record = expense()

    assert all(split.member_id != record.payer_member_id for split in record.splits)


def test_expense_rejects_unsupported_strategy() -> None:
    with pytest.raises(DomainValidationError):
        replace(expense(), split_strategy="percentage")


@pytest.mark.parametrize("amount", [0, -1, 1.5, True, "1"])
def test_expense_requires_positive_integer_ntd_amount(amount: object) -> None:
    with pytest.raises(DomainValidationError):
        replace(expense(), amount_minor=amount)


@pytest.mark.parametrize("amount", [0, 1, 900])
def test_expense_split_allows_nonnegative_integer_ntd_amount(amount: int) -> None:
    split = ExpenseSplit(member_id=uuid4(), amount_minor=amount)

    assert split.amount_minor == amount


@pytest.mark.parametrize("amount", [-1, 0.5, True])
def test_expense_split_rejects_non_integer_or_negative_amount(amount: object) -> None:
    with pytest.raises(DomainValidationError):
        ExpenseSplit(member_id=uuid4(), amount_minor=amount)


def test_expense_keeps_contextual_allocation_checks_for_later_services() -> None:
    record = replace(
        expense(),
        splits=(ExpenseSplit(member_id=uuid4(), amount_minor=100),),
    )

    assert record.amount_minor == 900
    assert record.splits[0].amount_minor == 100


def test_settlement_represents_an_external_transfer() -> None:
    record = settlement()

    assert record.amount_minor == 300
    assert record.from_member_id != record.to_member_id


@pytest.mark.parametrize("amount", [0, -1, 1.5, True])
def test_settlement_requires_positive_integer_ntd_amount(amount: object) -> None:
    with pytest.raises(DomainValidationError):
        replace(settlement(), amount_minor=amount)


def test_settlement_rejects_same_sender_and_recipient() -> None:
    record = settlement()

    with pytest.raises(DomainValidationError):
        replace(record, to_member_id=record.from_member_id)


@pytest.mark.parametrize("field", ["occurred_at", "created_at"])
@pytest.mark.parametrize("record_factory", [expense, settlement])
def test_financial_timestamps_must_be_timezone_aware(
    field: str, record_factory: Callable[[], Expense | Settlement]
) -> None:
    record = record_factory()

    with pytest.raises(DomainValidationError):
        replace(record, **{field: datetime(2026, 10, 3, 12, 0)})


def test_occurred_and_created_timestamps_can_differ() -> None:
    record = replace(expense(), occurred_at=aware_time() - timedelta(days=1))

    assert record.occurred_at < record.created_at


@pytest.mark.parametrize("bad_id", [None, "not-a-uuid"])
def test_required_ids_have_uuid_shape(bad_id: object) -> None:
    with pytest.raises(DomainValidationError):
        replace(expense(), payer_member_id=bad_id)


def test_expense_requires_immutable_split_sequence() -> None:
    record = expense()

    with pytest.raises(DomainValidationError):
        replace(record, splits=list(record.splits))


@pytest.mark.parametrize("record_factory", [expense, settlement])
def test_financial_records_cannot_be_mutated(
    record_factory: Callable[[], Expense | Settlement],
) -> None:
    record = record_factory()

    with pytest.raises(AttributeError):
        record.amount_minor = 1


@pytest.mark.parametrize("kind", ["expense", "settlement"])
def test_void_values_are_immutable_and_validate_audit_fields(kind):
    from dataclasses import FrozenInstanceError

    from app.domain import DomainValidationError, ExpenseVoid, SettlementVoid

    cls = ExpenseVoid if kind == "expense" else SettlementVoid
    values = {
        f"{kind}_id": uuid4(),
        "group_id": uuid4(),
        "reason": "Mistake",
        "created_at": datetime.now(UTC),
        "created_by_user_id": uuid4(),
    }
    void = cls(**values)
    with pytest.raises(FrozenInstanceError):
        void.reason = "rewrite"
    for changes in (
        {"reason": "  ", "replacement_id": uuid4()},
        {"reason": None, "replacement_id": uuid4()},
        {"reason": 42},
        {"created_at": datetime(2026, 1, 1)},
        {"created_by_user_id": "bad"},
        {"replacement_id": values[f"{kind}_id"]},
    ):
        with pytest.raises(DomainValidationError):
            cls(**(values | changes))


def test_guest_cannot_be_owner_and_roles_are_explicit():
    with pytest.raises(DomainValidationError):
        GroupMember(uuid4(), uuid4(), "Guest", role="owner")
    with pytest.raises(DomainValidationError):
        GroupMember(uuid4(), uuid4(), "Member", role="admin")


@pytest.mark.parametrize("kind", ["expense", "settlement"])
@pytest.mark.parametrize("reason", [None, "", " \t\n\u3000"])
def test_deletion_note_normalization_preserves_immutable_audit(kind, reason):
    from app.domain import ExpenseVoid, SettlementVoid

    cls = ExpenseVoid if kind == "expense" else SettlementVoid
    value = cls(
        **{
            f"{kind}_id": uuid4(),
            "group_id": uuid4(),
            "reason": reason,
            "created_at": datetime.now(UTC),
            "created_by_user_id": uuid4(),
        }
    )
    assert value.reason is None
