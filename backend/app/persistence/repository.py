"""Concrete storage operations; callers own commit and rollback."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.accounting import validate_expense, validate_settlement
from app.domain import (
    Expense,
    ExpenseVoid,
    Group,
    GroupMember,
    Settlement,
    SettlementVoid,
    User,
)
from app.persistence.mappers import (
    expense_from_row,
    expense_void_from_row,
    group_from_row,
    member_from_row,
    settlement_from_row,
    settlement_void_from_row,
    user_from_row,
)
from app.persistence.models import (
    ExpenseRow,
    ExpenseSplitRow,
    ExpenseVoidRow,
    GroupMemberRow,
    GroupRow,
    SettlementRow,
    SettlementVoidRow,
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

    def list_groups(self, user_id: UUID) -> tuple[Group, ...]:
        rows = self.session.scalars(
            select(GroupRow)
            .join(GroupMemberRow, GroupMemberRow.group_id == GroupRow.id)
            .where(GroupMemberRow.user_id == user_id)
            .order_by(GroupRow.id)
        )
        return tuple(group_from_row(row) for row in rows)

    def save_member(self, member: GroupMember) -> None:
        self.session.add(
            GroupMemberRow(
                id=member.id,
                group_id=member.group_id,
                user_id=member.user_id,
                role=member.role,
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

    def has_member_financial_history(self, group_id: UUID, member_id: UUID) -> bool:
        # Include originals of voided/corrected records, even with a zero balance.
        return bool(
            self.session.scalar(
                select(
                    or_(
                        select(ExpenseRow.id)
                        .where(
                            ExpenseRow.group_id == group_id,
                            ExpenseRow.payer_member_id == member_id,
                        )
                        .exists(),
                        select(ExpenseSplitRow.expense_id)
                        .where(
                            ExpenseSplitRow.group_id == group_id,
                            ExpenseSplitRow.member_id == member_id,
                        )
                        .exists(),
                        select(SettlementRow.id)
                        .where(
                            SettlementRow.group_id == group_id,
                            or_(
                                SettlementRow.from_member_id == member_id,
                                SettlementRow.to_member_id == member_id,
                            ),
                        )
                        .exists(),
                    )
                )
            )
        )

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

    def list_expenses(
        self, group_id: UUID, *, effective: bool = False
    ) -> tuple[Expense, ...]:
        rows = self.session.scalars(
            select(ExpenseRow)
            .where(ExpenseRow.group_id == group_id)
            .where(
                ~select(ExpenseVoidRow.expense_id)
                .where(ExpenseVoidRow.expense_id == ExpenseRow.id)
                .exists()
                if effective
                else True
            )
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

    def list_settlements(
        self, group_id: UUID, *, effective: bool = False
    ) -> tuple[Settlement, ...]:
        rows = self.session.scalars(
            select(SettlementRow)
            .where(SettlementRow.group_id == group_id)
            .where(
                ~select(SettlementVoidRow.settlement_id)
                .where(SettlementVoidRow.settlement_id == SettlementRow.id)
                .exists()
                if effective
                else True
            )
            .order_by(SettlementRow.created_at, SettlementRow.id)
        )
        return tuple(settlement_from_row(row) for row in rows)

    def save_expense_void(self, void: ExpenseVoid) -> None:
        self.session.add(
            ExpenseVoidRow(
                expense_id=void.expense_id,
                group_id=void.group_id,
                reason=void.reason,
                created_at=void.created_at,
                created_by_user_id=void.created_by_user_id,
                replacement_id=void.replacement_id,
            )
        )
        self.session.flush()

    def get_expense_void(self, target_id: UUID) -> ExpenseVoid | None:
        row = self.session.get(ExpenseVoidRow, target_id)
        return expense_void_from_row(row) if row else None

    def list_expense_voids(self, group_id: UUID) -> tuple[ExpenseVoid, ...]:
        rows = self.session.scalars(
            select(ExpenseVoidRow).where(ExpenseVoidRow.group_id == group_id)
        )
        return tuple(expense_void_from_row(row) for row in rows)

    def save_settlement_void(self, void: SettlementVoid) -> None:
        self.session.add(
            SettlementVoidRow(
                settlement_id=void.settlement_id,
                group_id=void.group_id,
                reason=void.reason,
                created_at=void.created_at,
                created_by_user_id=void.created_by_user_id,
                replacement_id=void.replacement_id,
            )
        )
        self.session.flush()

    def get_settlement_void(self, target_id: UUID) -> SettlementVoid | None:
        row = self.session.get(SettlementVoidRow, target_id)
        return settlement_void_from_row(row) if row else None

    def list_settlement_voids(self, group_id: UUID) -> tuple[SettlementVoid, ...]:
        rows = self.session.scalars(
            select(SettlementVoidRow).where(SettlementVoidRow.group_id == group_id)
        )
        return tuple(settlement_void_from_row(row) for row in rows)

    def get_membership(self, group_id: UUID, user_id: UUID) -> GroupMember | None:
        row = self.session.scalar(
            select(GroupMemberRow).where(
                GroupMemberRow.group_id == group_id, GroupMemberRow.user_id == user_id
            )
        )
        return member_from_row(row) if row else None
