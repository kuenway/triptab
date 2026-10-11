"""Pydantic HTTP contracts, separate from domain values."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt

from app.domain import Expense, Group, GroupMember, Settlement

Amount = Annotated[StrictInt, Field(gt=0, le=9_223_372_036_854_775_807)]
SplitAmount = Annotated[StrictInt, Field(ge=0, le=9_223_372_036_854_775_807)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GroupCreate(RequestModel):
    name: str


class GroupResponse(BaseModel):
    id: UUID
    name: str
    currency: Literal["TWD"]
    currency_scale: Literal[0]

    @classmethod
    def from_domain(cls, group: Group) -> "GroupResponse":
        return cls(
            id=group.id,
            name=group.name,
            currency=group.currency,
            currency_scale=group.currency_scale,
        )


class MemberCreate(RequestModel):
    display_name: str


class MemberResponse(BaseModel):
    id: UUID
    group_id: UUID
    display_name: str
    user_id: UUID | None
    role: Literal["owner", "member"]

    @classmethod
    def from_domain(cls, member: GroupMember) -> "MemberResponse":
        return cls(
            id=member.id,
            group_id=member.group_id,
            display_name=member.display_name,
            user_id=member.user_id,
            role=member.role,
        )


class SplitCreate(RequestModel):
    member_id: UUID
    amount: SplitAmount


class EqualExpenseCreate(RequestModel):
    description: str
    amount: Amount
    payer_member_id: UUID
    split_strategy: Literal["equal"]
    participant_member_ids: list[UUID] = Field(min_length=1)
    occurred_at: AwareDatetime


class ExactExpenseCreate(RequestModel):
    description: str
    amount: Amount
    payer_member_id: UUID
    split_strategy: Literal["exact"]
    splits: list[SplitCreate] = Field(min_length=1)
    occurred_at: AwareDatetime


ExpenseCreate = Annotated[
    EqualExpenseCreate | ExactExpenseCreate, Field(discriminator="split_strategy")
]


class SplitResponse(BaseModel):
    member_id: UUID
    amount: int


class FinancialAudit(BaseModel):
    status: Literal["active", "voided"] = "active"
    void_reason: str | None = None
    void_created_at: AwareDatetime | None = None
    void_created_by_user_id: UUID | None = None
    replaces_id: UUID | None = None
    replaced_by_id: UUID | None = None


class VoidRequest(RequestModel):
    reason: str


class ExpenseCorrection(VoidRequest):
    replacement: ExpenseCreate


class ExpenseResponse(FinancialAudit):
    id: UUID
    group_id: UUID
    description: str
    amount: int
    payer_member_id: UUID
    split_strategy: Literal["equal", "exact"]
    splits: list[SplitResponse]
    occurred_at: AwareDatetime
    created_at: AwareDatetime
    created_by_user_id: UUID

    @classmethod
    def from_domain(
        cls, expense: Expense, audit: dict | None = None
    ) -> "ExpenseResponse":
        return cls(
            **(audit or {}),
            id=expense.id,
            group_id=expense.group_id,
            description=expense.description,
            amount=expense.amount_minor,
            payer_member_id=expense.payer_member_id,
            split_strategy=expense.split_strategy.value,
            splits=[
                SplitResponse(member_id=split.member_id, amount=split.amount_minor)
                for split in expense.splits
            ],
            occurred_at=expense.occurred_at,
            created_at=expense.created_at,
            created_by_user_id=expense.created_by_user_id,
        )


class MemberBalance(BaseModel):
    member_id: UUID
    display_name: str
    amount: int


class BalancesResponse(BaseModel):
    group_id: UUID
    currency: Literal["TWD"]
    balances: list[MemberBalance]


class SettlementSuggestionResponse(BaseModel):
    from_member_id: UUID
    from_display_name: str
    to_member_id: UUID
    to_display_name: str
    amount: Annotated[StrictInt, Field(gt=0)]


class SettlementSuggestionsResponse(BaseModel):
    group_id: UUID
    currency: Literal["TWD"]
    suggestions: list[SettlementSuggestionResponse]


class SettlementSuggestionConfirm(RequestModel):
    from_member_id: UUID
    to_member_id: UUID
    amount: Amount


class SettlementCreate(RequestModel):
    from_member_id: UUID
    to_member_id: UUID
    amount: Amount
    occurred_at: AwareDatetime


class SettlementCorrection(VoidRequest):
    replacement: SettlementCreate


class SettlementResponse(FinancialAudit):
    id: UUID
    group_id: UUID
    from_member_id: UUID
    from_display_name: str
    to_member_id: UUID
    to_display_name: str
    amount: int
    occurred_at: AwareDatetime
    created_at: AwareDatetime
    created_by_user_id: UUID

    @classmethod
    def from_domain(
        cls, settlement: Settlement, names: dict[UUID, str], audit: dict | None = None
    ) -> "SettlementResponse":
        return cls(
            **(audit or {}),
            id=settlement.id,
            group_id=settlement.group_id,
            from_member_id=settlement.from_member_id,
            from_display_name=names[settlement.from_member_id],
            to_member_id=settlement.to_member_id,
            to_display_name=names[settlement.to_member_id],
            amount=settlement.amount_minor,
            occurred_at=settlement.occurred_at,
            created_at=settlement.created_at,
            created_by_user_id=settlement.created_by_user_id,
        )
