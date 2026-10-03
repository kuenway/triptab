"""Concrete storage operations; callers own commit and rollback."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.accounting import validate_expense, validate_settlement
from app.domain import Expense, Group, GroupMember, Settlement, User
from app.persistence.mappers import (
    expense_from_row,
    group_from_row,
    member_from_row,
    settlement_from_row,
    user_from_row,
)
from app.persistence.models import (
    ExpenseRow,
    ExpenseSplitRow,
    GroupMemberRow,
    GroupRow,
    SettlementRow,
    UserRow,
)


class LedgerRepository:
    """A focused repository bound to one caller-owned SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save_user(self, user: User) -> None:
        self.session.add(
            UserRow(id=user.id, email=user.email, display_name=user.display_name)
        )
        self.session.flush()

    def get_user(self, user_id: UUID) -> User | None:
        row = self.session.get(UserRow, user_id)
        return user_from_row(row) if row else None

    def save_group(self, group: Group) -> None:
        self.session.add(
            GroupRow(
                id=group.id,
                name=group.name,
                currency=group.currency,
                currency_scale=group.currency_scale,
            )
        )
        self.session.flush()

    def get_group(self, group_id: UUID) -> Group | None:
        row = self.session.get(GroupRow, group_id)
        return group_from_row(row) if row else None

    def list_groups(self) -> tuple[Group, ...]:
        rows = self.session.scalars(select(GroupRow).order_by(GroupRow.id))
        return tuple(group_from_row(row) for row in rows)

    def save_member(self, member: GroupMember) -> None:
        self.session.add(
            GroupMemberRow(
                id=member.id,
                group_id=member.group_id,
                user_id=member.user_id,
                display_name=member.display_name,
            )
        )
        self.session.flush()

    def get_member(self, member_id: UUID) -> GroupMember | None:
        row = self.session.get(GroupMemberRow, member_id)
        return member_from_row(row) if row else None

    def list_members(self, group_id: UUID) -> tuple[GroupMember, ...]:
        rows = self.session.scalars(
            select(GroupMemberRow)
            .where(GroupMemberRow.group_id == group_id)
            .order_by(GroupMemberRow.id)
        )
        return tuple(member_from_row(row) for row in rows)

    def _group_context(self, group_id: UUID) -> tuple[Group, tuple[GroupMember, ...]]:
        group = self.get_group(group_id)
        if group is None:
            raise ValueError("group does not exist")
        return group, self.list_members(group_id)

    def save_expense(self, expense: Expense) -> None:
        group, members = self._group_context(expense.group_id)
        validate_expense(group, members, expense)
        row = ExpenseRow(
            id=expense.id,
            group_id=expense.group_id,
            payer_member_id=expense.payer_member_id,
            description=expense.description,
            amount_minor=expense.amount_minor,
            split_strategy=expense.split_strategy.value,
            occurred_at=expense.occurred_at,
            created_at=expense.created_at,
            created_by_user_id=expense.created_by_user_id,
            splits=[
                ExpenseSplitRow(
                    expense_id=expense.id,
                    group_id=expense.group_id,
                    member_id=split.member_id,
                    amount_minor=split.amount_minor,
                )
                for split in expense.splits
            ],
        )
        self.session.add(row)
        self.session.flush()

    def get_expense(self, expense_id: UUID) -> Expense | None:
        row = self.session.scalar(
            select(ExpenseRow)
            .where(ExpenseRow.id == expense_id)
            .options(selectinload(ExpenseRow.splits))
        )
        return expense_from_row(row) if row else None

    def list_expenses(self, group_id: UUID) -> tuple[Expense, ...]:
        rows = self.session.scalars(
            select(ExpenseRow)
            .where(ExpenseRow.group_id == group_id)
            .order_by(ExpenseRow.created_at, ExpenseRow.id)
            .options(selectinload(ExpenseRow.splits))
        )
        return tuple(expense_from_row(row) for row in rows)

    def save_settlement(self, settlement: Settlement) -> None:
        group, members = self._group_context(settlement.group_id)
        validate_settlement(group, members, settlement)
        self.session.add(
            SettlementRow(
                id=settlement.id,
                group_id=settlement.group_id,
                from_member_id=settlement.from_member_id,
                to_member_id=settlement.to_member_id,
                amount_minor=settlement.amount_minor,
                occurred_at=settlement.occurred_at,
                created_at=settlement.created_at,
                created_by_user_id=settlement.created_by_user_id,
            )
        )
        self.session.flush()

    def get_settlement(self, settlement_id: UUID) -> Settlement | None:
        row = self.session.get(SettlementRow, settlement_id)
        return settlement_from_row(row) if row else None

    def list_settlements(self, group_id: UUID) -> tuple[Settlement, ...]:
        rows = self.session.scalars(
            select(SettlementRow)
            .where(SettlementRow.group_id == group_id)
            .order_by(SettlementRow.created_at, SettlementRow.id)
        )
        return tuple(settlement_from_row(row) for row in rows)
