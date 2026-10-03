"""Deterministic TWD accounting without I/O or mutable ledger state."""

from collections.abc import Iterable
from uuid import UUID

from app.domain import (
    Expense,
    ExpenseSplit,
    Group,
    GroupMember,
    Settlement,
    SplitStrategy,
)


class AccountingValidationError(ValueError):
    """The supplied allocations or group ledger are financially inconsistent."""


def _positive_amount(amount_minor: object) -> None:
    if type(amount_minor) is not int or amount_minor <= 0:
        raise AccountingValidationError(
            "amount_minor must be a positive integer NTD amount"
        )


def _participant_ids(participant_ids: Iterable[UUID]) -> tuple[UUID, ...]:
    ids = tuple(participant_ids)
    if not ids:
        raise AccountingValidationError("at least one participant is required")
    if any(not isinstance(member_id, UUID) for member_id in ids):
        raise AccountingValidationError("participant IDs must be UUID values")
    if len(ids) != len(set(ids)):
        raise AccountingValidationError("participant IDs must be unique")
    return tuple(sorted(ids))


def allocate_equal(
    amount_minor: int, participant_ids: Iterable[UUID]
) -> tuple[ExpenseSplit, ...]:
    """Allocate whole NTD; lower UUIDs receive the first remainder units."""
    _positive_amount(amount_minor)
    ids = _participant_ids(participant_ids)
    quotient, remainder = divmod(amount_minor, len(ids))
    return tuple(
        ExpenseSplit(member_id=member_id, amount_minor=quotient + (index < remainder))
        for index, member_id in enumerate(ids)
    )


def validate_exact_splits(
    amount_minor: int, splits: Iterable[ExpenseSplit]
) -> tuple[ExpenseSplit, ...]:
    """Return validated final allocations in stable member-ID order."""
    _positive_amount(amount_minor)
    values = tuple(splits)
    if any(not isinstance(split, ExpenseSplit) for split in values):
        raise AccountingValidationError("splits must contain ExpenseSplit values")
    _participant_ids(split.member_id for split in values)
    if sum(split.amount_minor for split in values) != amount_minor:
        raise AccountingValidationError("split amounts must total the expense amount")
    return tuple(sorted(values, key=lambda split: split.member_id))


def _member_ids(group: Group, members: Iterable[GroupMember]) -> set[UUID]:
    if not isinstance(group, Group):
        raise AccountingValidationError("group must be a Group value")
    ids: set[UUID] = set()
    for member in members:
        if not isinstance(member, GroupMember):
            raise AccountingValidationError("members must contain GroupMember values")
        if member.group_id != group.id:
            raise AccountingValidationError("member belongs to a different group")
        if member.id in ids:
            raise AccountingValidationError("group member IDs must be unique")
        ids.add(member.id)
    return ids


def _validate_expense(
    group_id: UUID, member_ids: set[UUID], expense: Expense
) -> tuple[ExpenseSplit, ...]:
    if not isinstance(expense, Expense):
        raise AccountingValidationError("expenses must contain Expense values")
    if expense.group_id != group_id:
        raise AccountingValidationError("expense belongs to a different group")
    if expense.payer_member_id not in member_ids:
        raise AccountingValidationError("expense payer is not in the group")

    splits = validate_exact_splits(expense.amount_minor, expense.splits)
    if any(split.member_id not in member_ids for split in splits):
        raise AccountingValidationError("expense participant is not in the group")
    if expense.split_strategy is SplitStrategy.EQUAL:
        expected = allocate_equal(
            expense.amount_minor, (split.member_id for split in splits)
        )
        if splits != expected:
            raise AccountingValidationError(
                "equal splits do not match the deterministic allocation"
            )
    elif expense.split_strategy is not SplitStrategy.EXACT:
        raise AccountingValidationError("unsupported split strategy")
    return splits


def validate_expense(
    group: Group, members: Iterable[GroupMember], expense: Expense
) -> None:
    """Check an expense against explicitly supplied group membership."""
    ids = _member_ids(group, members)
    _validate_expense(group.id, ids, expense)


def _validate_settlement(
    group_id: UUID, member_ids: set[UUID], settlement: Settlement
) -> None:
    if not isinstance(settlement, Settlement):
        raise AccountingValidationError("settlements must contain Settlement values")
    if settlement.group_id != group_id:
        raise AccountingValidationError("settlement belongs to a different group")
    if settlement.from_member_id not in member_ids:
        raise AccountingValidationError("settlement sender is not in the group")
    if settlement.to_member_id not in member_ids:
        raise AccountingValidationError("settlement recipient is not in the group")


def validate_settlement(
    group: Group, members: Iterable[GroupMember], settlement: Settlement
) -> None:
    """Check both sides of a transfer against the supplied group."""
    ids = _member_ids(group, members)
    _validate_settlement(group.id, ids, settlement)


def calculate_balances(
    group: Group,
    members: Iterable[GroupMember],
    expenses: Iterable[Expense],
    settlements: Iterable[Settlement],
) -> dict[UUID, int]:
    """Derive one integer NTD net balance per supplied group member."""
    member_ids = _member_ids(group, members)
    balances = {member_id: 0 for member_id in sorted(member_ids)}
    seen_expenses: set[UUID] = set()
    seen_settlements: set[UUID] = set()

    for expense in expenses:
        splits = _validate_expense(group.id, member_ids, expense)
        if expense.id in seen_expenses:
            raise AccountingValidationError("expense appears more than once")
        seen_expenses.add(expense.id)
        balances[expense.payer_member_id] += expense.amount_minor
        for split in splits:
            balances[split.member_id] -= split.amount_minor

    for settlement in settlements:
        _validate_settlement(group.id, member_ids, settlement)
        if settlement.id in seen_settlements:
            raise AccountingValidationError("settlement appears more than once")
        seen_settlements.add(settlement.id)
        balances[settlement.from_member_id] += settlement.amount_minor
        balances[settlement.to_member_id] -= settlement.amount_minor

    if sum(balances.values()) != 0:
        raise AccountingValidationError("group balances must total zero")
    return balances
