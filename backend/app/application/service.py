"""Small transactional use cases over the existing ledger contracts."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.accounting import (
    allocate_equal,
    calculate_balances,
    suggest_settlements,
    validate_exact_splits,
)
from app.domain import (
    Expense,
    ExpenseSplit,
    Group,
    GroupMember,
    SettlementSuggestion,
    SplitStrategy,
    User,
)
from app.persistence.repository import LedgerRepository

# Milestone 4 has no authentication. This internal user satisfies the approved
# recording-actor contract without presenting a caller as an authenticated user.
DEVELOPMENT_ACTOR = User(
    id=UUID("f2c34ceb-dc48-4de7-8fe0-5820e5f2be4d"),
    email="local-development@triptab.invalid",
    display_name="TripTab local development",
)


class ResourceNotFound(Exception):
    """A resource is absent from the requested group scope."""


class TripTabService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = LedgerRepository(session)

    def _group(self, group_id: UUID) -> Group:
        group = self.repo.get_group(group_id)
        if group is None:
            raise ResourceNotFound("group not found")
        return group

    def create_group(self, name: str) -> Group:
        group = Group(id=uuid4(), name=name)
        with self.session.begin():
            self.repo.save_group(group)
        return group

    def list_groups(self) -> tuple[Group, ...]:
        return self.repo.list_groups()

    def get_group(self, group_id: UUID) -> Group:
        return self._group(group_id)

    def create_guest_member(self, group_id: UUID, display_name: str) -> GroupMember:
        member = GroupMember(id=uuid4(), group_id=group_id, display_name=display_name)
        with self.session.begin():
            self._group(group_id)
            self.repo.save_member(member)
        return member

    def list_members(self, group_id: UUID) -> tuple[GroupMember, ...]:
        self._group(group_id)
        return self.repo.list_members(group_id)

    def create_expense(
        self,
        group_id: UUID,
        description: str,
        amount: int,
        payer_member_id: UUID,
        split_strategy: SplitStrategy,
        occurred_at: datetime,
        participant_member_ids: tuple[UUID, ...] | None = None,
        splits: tuple[ExpenseSplit, ...] | None = None,
    ) -> Expense:
        with self.session.begin():
            self._group(group_id)
            member_ids = {member.id for member in self.repo.list_members(group_id)}
            if payer_member_id not in member_ids:
                raise ResourceNotFound("payer member not found in group")
            if split_strategy is SplitStrategy.EQUAL:
                if participant_member_ids is None:
                    raise ValueError("equal participants are required")
                allocations = allocate_equal(amount, participant_member_ids)
            else:
                if splits is None:
                    raise ValueError("exact splits are required")
                allocations = validate_exact_splits(amount, splits)
            if any(split.member_id not in member_ids for split in allocations):
                raise ResourceNotFound("participant member not found in group")
            if self.repo.get_user(DEVELOPMENT_ACTOR.id) is None:
                self.repo.save_user(DEVELOPMENT_ACTOR)
            expense = Expense(
                id=uuid4(),
                group_id=group_id,
                description=description,
                amount_minor=amount,
                payer_member_id=payer_member_id,
                split_strategy=split_strategy,
                splits=allocations,
                occurred_at=occurred_at.astimezone(UTC),
                created_at=datetime.now(UTC),
                created_by_user_id=DEVELOPMENT_ACTOR.id,
            )
            self.repo.save_expense(expense)
        return expense

    def list_expenses(self, group_id: UUID) -> tuple[Expense, ...]:
        self._group(group_id)
        return tuple(
            sorted(
                self.repo.list_expenses(group_id),
                key=lambda expense: (expense.occurred_at, expense.id),
                reverse=True,
            )
        )

    def get_expense(self, group_id: UUID, expense_id: UUID) -> Expense:
        self._group(group_id)
        expense = self.repo.get_expense(expense_id)
        if expense is None or expense.group_id != group_id:
            raise ResourceNotFound("expense not found in group")
        return expense

    def get_balances(
        self, group_id: UUID
    ) -> tuple[Group, tuple[tuple[GroupMember, int], ...]]:
        group = self._group(group_id)
        members = self.repo.list_members(group_id)
        balances = calculate_balances(
            group,
            members,
            self.repo.list_expenses(group_id),
            self.repo.list_settlements(group_id),
        )
        return group, tuple((member, balances[member.id]) for member in members)

    def get_settlement_suggestions(
        self, group_id: UUID
    ) -> tuple[Group, tuple[GroupMember, ...], tuple[SettlementSuggestion, ...]]:
        group, values = self.get_balances(group_id)
        suggestions = suggest_settlements(
            {member.id: amount for member, amount in values}
        )
        return group, tuple(member for member, _ in values), suggestions
