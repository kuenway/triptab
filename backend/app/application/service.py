"""Small transactional use cases over the existing ledger contracts."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import (
    allocate_equal,
    calculate_balances,
    suggest_settlements,
    validate_exact_splits,
)
from app.application.auth import PermissionDenied
from app.domain import (
    Expense,
    ExpenseSplit,
    ExpenseVoid,
    Group,
    GroupMember,
    Settlement,
    SettlementSuggestion,
    SettlementVoid,
    SplitStrategy,
    User,
)
from app.domain.names import canonical_traveler_name
from app.persistence.models import GroupMemberRow, GroupRow, TripInvitationRow
from app.persistence.repository import LedgerRepository


class ResourceNotFound(Exception):
    """A resource is absent from the requested group scope."""


class FinancialConflict(Exception):
    """A financial record or derived suggestion is no longer current."""


class MemberRemovalConflict(Exception):
    """Only unclaimed guests without financial history can be removed."""

    def __init__(
        self, message: str, *, group_id: UUID, member_id: UUID, reason: str
    ) -> None:
        super().__init__(message)
        self.diagnostics = {
            "group_id": str(group_id),
            "member_id": str(member_id),
            "removal_rejection_reason": reason,
        }


class MemberNameConflict(Exception):
    """A traveler already uses this canonical display name in the trip."""


class TripTabService:
    def __init__(self, session: Session, current_user: User) -> None:
        self.current_user = current_user
        self.session = session
        self.repo = LedgerRepository(session)

    def _membership(self, group_id: UUID) -> GroupMember:
        member = self.repo.get_membership(group_id, self.current_user.id)
        if member is None:
            raise ResourceNotFound("group not found")
        return member

    def _require_owner(self, group_id: UUID) -> None:
        if self._membership(group_id).role != "owner":
            raise PermissionDenied("only the group owner may manage travelers")

    def _require_record_author(self, group_id: UUID, author_id: UUID) -> None:
        if (
            self._membership(group_id).role != "owner"
            and author_id != self.current_user.id
        ):
            raise PermissionDenied(
                "only the recording author or group owner may change this record"
            )

    def _group(self, group_id: UUID) -> Group:
        self._membership(group_id)
        group = self.repo.get_group(group_id)
        if group is None:
            raise ResourceNotFound("group not found")
        return group

    def create_group(self, name: str) -> Group:
        group = Group(id=uuid4(), name=name)
        with self.session.begin():
            self.repo.save_group(group)
            self.repo.save_member(
                GroupMember(
                    id=uuid4(),
                    group_id=group.id,
                    display_name=self.current_user.display_name,
                    user_id=self.current_user.id,
                    role="owner",
                )
            )
        return group

    def list_groups(self) -> tuple[Group, ...]:
        return self.repo.list_groups(self.current_user.id)

    def get_group(self, group_id: UUID) -> Group:
        return self._group(group_id)

    def create_guest_member(self, group_id: UUID, display_name: str) -> GroupMember:
        member = GroupMember(
            id=uuid4(), group_id=group_id, display_name=display_name.strip()
        )
        with self.session.begin():
            self._group(group_id)
            self._require_owner(group_id)
            # Serialize the check and insert across application workers per Trip.
            self.session.execute(
                select(GroupRow.id).where(GroupRow.id == group_id).with_for_update()
            )
            canonical = canonical_traveler_name(member.display_name)
            if any(
                canonical_traveler_name(existing.display_name) == canonical
                for existing in self.repo.list_members(group_id)
            ):
                raise MemberNameConflict(
                    f'A traveler named "{member.display_name}" '
                    "already exists in this trip."
                )
            self.repo.save_member(member)
        return member

    def list_members(self, group_id: UUID) -> tuple[GroupMember, ...]:
        self._group(group_id)
        return self.repo.list_members(group_id)

    def remove_guest_member(self, group_id: UUID, member_id: UUID) -> None:
        try:
            with self.session.begin():
                self._require_owner(group_id)
                member = self.session.scalar(
                    select(GroupMemberRow)
                    .where(
                        GroupMemberRow.group_id == group_id,
                        GroupMemberRow.id == member_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if member is None:
                    raise ResourceNotFound("member not found")
                if member.role == "owner" or member.user_id is not None:
                    raise MemberRemovalConflict(
                        "only unclaimed guests can be removed",
                        group_id=group_id,
                        member_id=member_id,
                        reason="owner" if member.role == "owner" else "linked_member",
                    )
                if self.repo.has_member_financial_history(group_id, member_id):
                    raise MemberRemovalConflict(
                        "This traveler has financial history and cannot be removed.",
                        group_id=group_id,
                        member_id=member_id,
                        reason="financial_reference",
                    )
                # Match the member-first invitation lock order.
                self.session.execute(
                    update(TripInvitationRow)
                    .where(
                        TripInvitationRow.group_id == group_id,
                        TripInvitationRow.target_member_id == member_id,
                        TripInvitationRow.accepted_at.is_(None),
                        TripInvitationRow.revoked_at.is_(None),
                    )
                    .values(
                        revoked_at=datetime.now(UTC),
                        revoked_by_user_id=self.current_user.id,
                    )
                )
                self.session.execute(
                    update(TripInvitationRow)
                    .where(
                        TripInvitationRow.group_id == group_id,
                        TripInvitationRow.target_member_id == member_id,
                        TripInvitationRow.revoked_at.is_not(None),
                    )
                    .values(target_member_id=None)
                )
                self.session.delete(member)
                self.session.flush()
        except IntegrityError as error:
            # A concurrent financial insert can win before the member lock. FKs
            # remain the final defense; rollback also restores invitation metadata.
            constraint = getattr(
                getattr(error.orig, "diag", None), "constraint_name", None
            )
            if constraint in {
                "fk_expenses_group_payer_member",
                "fk_expense_splits_group_member",
                "fk_settlements_group_sender",
                "fk_settlements_group_recipient",
            }:
                raise MemberRemovalConflict(
                    "This traveler has financial history and cannot be removed.",
                    group_id=group_id,
                    member_id=member_id,
                    reason=constraint,
                ) from None
            raise

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
        with self._financial_transaction(group_id):
            return self._create_expense(
                group_id,
                description,
                amount,
                payer_member_id,
                split_strategy,
                occurred_at,
                participant_member_ids,
                splits,
            )

    def _create_expense(
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
            created_by_user_id=self.current_user.id,
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
            self.repo.list_expenses(group_id, effective=True),
            self.repo.list_settlements(group_id, effective=True),
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

    def record_settlement(
        self,
        group_id: UUID,
        from_member_id: UUID,
        to_member_id: UUID,
        amount: int,
        occurred_at: datetime,
    ) -> Settlement:
        with self._financial_transaction(group_id):
            return self._record_settlement(
                group_id, from_member_id, to_member_id, amount, occurred_at
            )

    def _require_settlement_participants(
        self, group_id: UUID, from_member_id: UUID, to_member_id: UUID
    ) -> None:
        self._group(group_id)
        member_ids = {member.id for member in self.repo.list_members(group_id)}
        if from_member_id not in member_ids:
            raise ResourceNotFound("sender member not found in group")
        if to_member_id not in member_ids:
            raise ResourceNotFound("recipient member not found in group")
        membership = self._membership(group_id)
        if membership.role != "owner" and membership.id not in {
            from_member_id,
            to_member_id,
        }:
            raise PermissionDenied(
                "only sender, recipient, or group owner may record a payment"
            )

    def confirm_settlement_suggestion(
        self, group_id: UUID, from_member_id: UUID, to_member_id: UUID, amount: int
    ) -> Settlement:
        with self._financial_transaction(group_id):
            self._require_settlement_participants(
                group_id, from_member_id, to_member_id
            )
            _, _, suggestions = self.get_settlement_suggestions(group_id)
            match = next(
                (
                    suggestion
                    for suggestion in suggestions
                    if (
                        suggestion.from_member_id,
                        suggestion.to_member_id,
                        suggestion.amount,
                    )
                    == (from_member_id, to_member_id, amount)
                ),
                None,
            )
            if match is None:
                raise FinancialConflict("settlement suggestion has changed")
            return self._record_settlement(
                group_id,
                match.from_member_id,
                match.to_member_id,
                match.amount,
                datetime.now(UTC),
            )

    def _record_settlement(
        self,
        group_id: UUID,
        from_member_id: UUID,
        to_member_id: UUID,
        amount: int,
        occurred_at: datetime,
    ) -> Settlement:
        self._require_settlement_participants(group_id, from_member_id, to_member_id)
        settlement = Settlement(
            id=uuid4(),
            group_id=group_id,
            from_member_id=from_member_id,
            to_member_id=to_member_id,
            amount_minor=amount,
            occurred_at=occurred_at.astimezone(UTC),
            created_at=datetime.now(UTC),
            created_by_user_id=self.current_user.id,
        )
        # The existing repository runs contextual validation before flushing.
        self.repo.save_settlement(settlement)
        return settlement

    def get_settlement(self, group_id: UUID, settlement_id: UUID) -> Settlement:
        self._group(group_id)
        settlement = self.repo.get_settlement(settlement_id)
        if settlement is None or settlement.group_id != group_id:
            raise ResourceNotFound("settlement not found in group")
        return settlement

    def list_settlements(self, group_id: UUID) -> tuple[Settlement, ...]:
        self._group(group_id)
        return tuple(
            sorted(
                self.repo.list_settlements(group_id),
                key=lambda settlement: (settlement.occurred_at, settlement.id),
                reverse=True,
            )
        )

    def correct_expense(
        self,
        group_id: UUID,
        target_id: UUID,
        reason: str,
        description: str,
        amount: int,
        payer_member_id: UUID,
        split_strategy: SplitStrategy,
        occurred_at: datetime,
        participant_member_ids: tuple[UUID, ...] | None = None,
        splits: tuple[ExpenseSplit, ...] | None = None,
    ) -> Expense:
        with self._financial_transaction(group_id):
            self._active_expense(group_id, target_id)
            replacement = self._create_expense(
                group_id,
                description,
                amount,
                payer_member_id,
                split_strategy,
                occurred_at,
                participant_member_ids,
                splits,
            )
            self.repo.save_expense_void(
                ExpenseVoid(
                    target_id,
                    group_id,
                    reason,
                    datetime.now(UTC),
                    self.current_user.id,
                    replacement.id,
                )
            )
            return replacement

    def correct_settlement(
        self,
        group_id: UUID,
        target_id: UUID,
        reason: str,
        from_member_id: UUID,
        to_member_id: UUID,
        amount: int,
        occurred_at: datetime,
    ) -> Settlement:
        with self._financial_transaction(group_id):
            self._active_settlement(group_id, target_id)
            replacement = self._record_settlement(
                group_id, from_member_id, to_member_id, amount, occurred_at
            )
            self.repo.save_settlement_void(
                SettlementVoid(
                    target_id,
                    group_id,
                    reason,
                    datetime.now(UTC),
                    self.current_user.id,
                    replacement.id,
                )
            )
            return replacement

    @contextmanager
    def _financial_transaction(self, group_id: UUID) -> Iterator[None]:
        try:
            with self.session.begin():
                self._group(group_id)
                self.repo.lock_group_finances(group_id)
                yield
        except IntegrityError as error:
            # A competing void/correction may win after our active-state check.
            constraint = getattr(
                getattr(error.orig, "diag", None), "constraint_name", None
            )
            if constraint in {"pk_expense_voids", "pk_settlement_voids"}:
                raise FinancialConflict("record already voided or corrected") from error
            raise

    def _active_expense(self, group_id: UUID, target_id: UUID) -> Expense:
        self._group(group_id)
        record = self.repo.get_expense(target_id)
        if record is None or record.group_id != group_id:
            raise ResourceNotFound("expense not found in group")
        self._require_record_author(group_id, record.created_by_user_id)
        if self.repo.get_expense_void(target_id) is not None:
            raise FinancialConflict("expense already voided or corrected")
        return record

    def void_expense(self, group_id: UUID, target_id: UUID, reason: str) -> ExpenseVoid:
        with self._financial_transaction(group_id):
            self._active_expense(group_id, target_id)
            void = ExpenseVoid(
                target_id, group_id, reason, datetime.now(UTC), self.current_user.id
            )
            self.repo.save_expense_void(void)
            return void

    def expense_audit(self, group_id: UUID) -> dict[UUID, dict]:
        self._group(group_id)
        audit: dict[UUID, dict] = {}
        for void in self.repo.list_expense_voids(group_id):
            audit.setdefault(void.expense_id, {}).update(
                status="voided",
                void_reason=void.reason,
                void_created_at=void.created_at,
                void_created_by_user_id=void.created_by_user_id,
                replaced_by_id=void.replacement_id,
            )
            if void.replacement_id is not None:
                audit.setdefault(void.replacement_id, {})["replaces_id"] = (
                    void.expense_id
                )
        return audit

    def _active_settlement(self, group_id: UUID, target_id: UUID) -> Settlement:
        self._group(group_id)
        record = self.repo.get_settlement(target_id)
        if record is None or record.group_id != group_id:
            raise ResourceNotFound("settlement not found in group")
        self._require_record_author(group_id, record.created_by_user_id)
        if self.repo.get_settlement_void(target_id) is not None:
            raise FinancialConflict("settlement already voided or corrected")
        return record

    def void_settlement(
        self, group_id: UUID, target_id: UUID, reason: str
    ) -> SettlementVoid:
        with self._financial_transaction(group_id):
            self._active_settlement(group_id, target_id)
            void = SettlementVoid(
                target_id, group_id, reason, datetime.now(UTC), self.current_user.id
            )
            self.repo.save_settlement_void(void)
            return void

    def settlement_audit(self, group_id: UUID) -> dict[UUID, dict]:
        self._group(group_id)
        audit: dict[UUID, dict] = {}
        for void in self.repo.list_settlement_voids(group_id):
            audit.setdefault(void.settlement_id, {}).update(
                status="voided",
                void_reason=void.reason,
                void_created_at=void.created_at,
                void_created_by_user_id=void.created_by_user_id,
                replaced_by_id=void.replacement_id,
            )
            if void.replacement_id is not None:
                audit.setdefault(void.replacement_id, {})["replaces_id"] = (
                    void.settlement_id
                )
        return audit
