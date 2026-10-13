"""Domain objects with only their own structural and value invariants."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID


class DomainValidationError(ValueError):
    """A value violates an invariant that one domain object can check alone."""


def _require_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise DomainValidationError(f"{name} must be a UUID")


def _require_nonblank(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{name} must be a nonblank string")


def _void_reason(reason: str | None, correction: bool) -> str | None:
    if correction:
        _require_nonblank("reason", reason)
    elif reason is not None:
        if not isinstance(reason, str):
            raise DomainValidationError("reason must be a string or null")
        if not reason.strip():
            return None
    # Preserve meaningful historical values exactly, including surrounding spaces.
    return reason


def _require_amount(name: str, value: object, *, allow_zero: bool = False) -> None:
    if type(value) is not int or value < 0 or (value == 0 and not allow_zero):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise DomainValidationError(f"{name} must be a {qualifier} integer NTD amount")


def _require_aware_datetime(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise DomainValidationError(f"{name} must be a timezone-aware datetime")


class SplitStrategy(StrEnum):
    EQUAL = "equal"
    EXACT = "exact"


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    display_name: str | None

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_nonblank("email", self.email)
        if self.display_name is not None:
            _require_nonblank("display_name", self.display_name)


@dataclass(frozen=True, slots=True)
class Group:
    id: UUID
    name: str
    currency: Literal["TWD"] = "TWD"
    currency_scale: Literal[0] = 0

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_nonblank("name", self.name)
        if self.currency != "TWD":
            raise DomainValidationError("currency must be TWD")
        if type(self.currency_scale) is not int or self.currency_scale != 0:
            raise DomainValidationError("currency_scale must be 0")


@dataclass(frozen=True, slots=True)
class GroupMember:
    id: UUID
    group_id: UUID
    display_name: str
    user_id: UUID | None = None
    role: Literal["owner", "member"] = "member"

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_uuid("group_id", self.group_id)
        _require_nonblank("display_name", self.display_name)
        if self.user_id is not None:
            _require_uuid("user_id", self.user_id)

        if self.role not in {"owner", "member"}:
            raise DomainValidationError("role must be owner or member")
        if self.role == "owner" and self.user_id is None:
            raise DomainValidationError("owner must be linked to a user")

    @property
    def is_guest(self) -> bool:
        return self.user_id is None


@dataclass(frozen=True, slots=True)
class ExpenseSplit:
    member_id: UUID
    amount_minor: int

    def __post_init__(self) -> None:
        _require_uuid("member_id", self.member_id)
        _require_amount("amount_minor", self.amount_minor, allow_zero=True)


@dataclass(frozen=True, slots=True)
class Expense:
    id: UUID
    group_id: UUID
    description: str
    amount_minor: int
    payer_member_id: UUID
    split_strategy: SplitStrategy
    splits: tuple[ExpenseSplit, ...]
    occurred_at: datetime
    created_at: datetime
    created_by_user_id: UUID

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_uuid("group_id", self.group_id)
        _require_nonblank("description", self.description)
        _require_amount("amount_minor", self.amount_minor)
        _require_uuid("payer_member_id", self.payer_member_id)
        if not isinstance(self.split_strategy, SplitStrategy):
            raise DomainValidationError("split_strategy must be EQUAL or EXACT")
        if not isinstance(self.splits, tuple) or not all(
            isinstance(split, ExpenseSplit) for split in self.splits
        ):
            raise DomainValidationError("splits must be a tuple of ExpenseSplit values")
        _require_aware_datetime("occurred_at", self.occurred_at)
        _require_aware_datetime("created_at", self.created_at)
        _require_uuid("created_by_user_id", self.created_by_user_id)


@dataclass(frozen=True, slots=True)
class SettlementSuggestion:
    """A proposed transfer, without a payment identity or recorded event."""

    from_member_id: UUID
    to_member_id: UUID
    amount: int

    def __post_init__(self) -> None:
        _require_uuid("from_member_id", self.from_member_id)
        _require_uuid("to_member_id", self.to_member_id)
        if self.from_member_id == self.to_member_id:
            raise DomainValidationError("suggestion members must be different")
        _require_amount("amount", self.amount)


@dataclass(frozen=True, slots=True)
class Settlement:
    id: UUID
    group_id: UUID
    from_member_id: UUID
    to_member_id: UUID
    amount_minor: int
    occurred_at: datetime
    created_at: datetime
    created_by_user_id: UUID

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_uuid("group_id", self.group_id)
        _require_uuid("from_member_id", self.from_member_id)
        _require_uuid("to_member_id", self.to_member_id)
        if self.from_member_id == self.to_member_id:
            raise DomainValidationError("settlement members must be different")
        _require_amount("amount_minor", self.amount_minor)
        _require_aware_datetime("occurred_at", self.occurred_at)
        _require_aware_datetime("created_at", self.created_at)
        _require_uuid("created_by_user_id", self.created_by_user_id)


@dataclass(frozen=True, slots=True)
class ExpenseVoid:
    expense_id: UUID
    group_id: UUID
    reason: str | None
    created_at: datetime
    created_by_user_id: UUID
    replacement_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid("expense_id", self.expense_id)
        _require_uuid("group_id", self.group_id)
        object.__setattr__(
            self, "reason", _void_reason(self.reason, self.replacement_id is not None)
        )
        _require_aware_datetime("created_at", self.created_at)
        _require_uuid("created_by_user_id", self.created_by_user_id)
        if self.replacement_id is not None:
            _require_uuid("replacement_id", self.replacement_id)
            if self.replacement_id == self.expense_id:
                raise DomainValidationError("replacement must be a new record")


@dataclass(frozen=True, slots=True)
class SettlementVoid:
    settlement_id: UUID
    group_id: UUID
    reason: str | None
    created_at: datetime
    created_by_user_id: UUID
    replacement_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid("settlement_id", self.settlement_id)
        _require_uuid("group_id", self.group_id)
        object.__setattr__(
            self, "reason", _void_reason(self.reason, self.replacement_id is not None)
        )
        _require_aware_datetime("created_at", self.created_at)
        _require_uuid("created_by_user_id", self.created_by_user_id)
        if self.replacement_id is not None:
            _require_uuid("replacement_id", self.replacement_id)
            if self.replacement_id == self.settlement_id:
                raise DomainValidationError("replacement must be a new record")
