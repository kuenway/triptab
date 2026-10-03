"""Translate storage rows to immutable domain values."""

from app.domain import (
    Expense,
    ExpenseSplit,
    ExpenseVoid,
    Group,
    GroupMember,
    Settlement,
    SettlementVoid,
    SplitStrategy,
    User,
)
from app.persistence.models import (
    ExpenseRow,
    ExpenseVoidRow,
    GroupMemberRow,
    GroupRow,
    SettlementRow,
    SettlementVoidRow,
    UserRow,
)


def user_from_row(row: UserRow) -> User:
    return User(id=row.id, email=row.email, display_name=row.display_name)


def group_from_row(row: GroupRow) -> Group:
    return Group(
        id=row.id,
        name=row.name,
        currency=row.currency,
        currency_scale=row.currency_scale,
    )


def member_from_row(row: GroupMemberRow) -> GroupMember:
    return GroupMember(
        id=row.id,
        group_id=row.group_id,
        user_id=row.user_id,
        display_name=row.display_name,
    )


def expense_from_row(row: ExpenseRow) -> Expense:
    return Expense(
        id=row.id,
        group_id=row.group_id,
        payer_member_id=row.payer_member_id,
        description=row.description,
        amount_minor=row.amount_minor,
        split_strategy=SplitStrategy(row.split_strategy),
        splits=tuple(
            ExpenseSplit(member_id=split.member_id, amount_minor=split.amount_minor)
            for split in sorted(row.splits, key=lambda split: split.member_id)
        ),
        occurred_at=row.occurred_at,
        created_at=row.created_at,
        created_by_user_id=row.created_by_user_id,
    )


def settlement_from_row(row: SettlementRow) -> Settlement:
    return Settlement(
        id=row.id,
        group_id=row.group_id,
        from_member_id=row.from_member_id,
        to_member_id=row.to_member_id,
        amount_minor=row.amount_minor,
        occurred_at=row.occurred_at,
        created_at=row.created_at,
        created_by_user_id=row.created_by_user_id,
    )


def expense_void_from_row(row: ExpenseVoidRow) -> ExpenseVoid:
    return ExpenseVoid(
        expense_id=row.expense_id,
        group_id=row.group_id,
        reason=row.reason,
        created_at=row.created_at,
        created_by_user_id=row.created_by_user_id,
        replacement_id=row.replacement_id,
    )


def settlement_void_from_row(row: SettlementVoidRow) -> SettlementVoid:
    return SettlementVoid(
        settlement_id=row.settlement_id,
        group_id=row.group_id,
        reason=row.reason,
        created_at=row.created_at,
        created_by_user_id=row.created_by_user_id,
        replacement_id=row.replacement_id,
    )
