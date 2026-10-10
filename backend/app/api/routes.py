"""Thin versioned routes calling application use cases."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_service
from app.api.schemas import (
    BalancesResponse,
    EqualExpenseCreate,
    ExactExpenseCreate,
    ExpenseCorrection,
    ExpenseCreate,
    ExpenseResponse,
    GroupCreate,
    GroupResponse,
    MemberBalance,
    MemberCreate,
    MemberResponse,
    SettlementCorrection,
    SettlementCreate,
    SettlementResponse,
    SettlementSuggestionResponse,
    SettlementSuggestionsResponse,
    VoidRequest,
)
from app.application.service import TripTabService
from app.domain import ExpenseSplit, SplitStrategy

router = APIRouter(prefix="/api/v1")
ServiceDependency = Annotated[TripTabService, Depends(get_service)]


@router.post("/groups", response_model=GroupResponse, status_code=201, tags=["groups"])
def create_group(request: GroupCreate, service: ServiceDependency) -> GroupResponse:
    return GroupResponse.from_domain(service.create_group(request.name))


@router.get("/groups", response_model=list[GroupResponse], tags=["groups"])
def list_groups(service: ServiceDependency) -> list[GroupResponse]:
    return [GroupResponse.from_domain(group) for group in service.list_groups()]


@router.get("/groups/{group_id}", response_model=GroupResponse, tags=["groups"])
def get_group(group_id: UUID, service: ServiceDependency) -> GroupResponse:
    return GroupResponse.from_domain(service.get_group(group_id))


@router.post(
    "/groups/{group_id}/members",
    response_model=MemberResponse,
    status_code=201,
    tags=["members"],
)
def create_member(
    group_id: UUID,
    request: MemberCreate,
    service: ServiceDependency,
) -> MemberResponse:
    return MemberResponse.from_domain(
        service.create_guest_member(group_id, request.display_name)
    )


@router.get(
    "/groups/{group_id}/members", response_model=list[MemberResponse], tags=["members"]
)
def list_members(group_id: UUID, service: ServiceDependency) -> list[MemberResponse]:
    return [
        MemberResponse.from_domain(member) for member in service.list_members(group_id)
    ]


@router.delete(
    "/groups/{group_id}/members/{member_id}", status_code=204, tags=["members"]
)
def remove_member(
    group_id: UUID, member_id: UUID, service: ServiceDependency
) -> Response:
    service.remove_guest_member(group_id, member_id)
    return Response(status_code=204)


@router.post(
    "/groups/{group_id}/expenses",
    response_model=ExpenseResponse,
    status_code=201,
    tags=["expenses"],
)
def create_expense(
    group_id: UUID,
    request: ExpenseCreate,
    service: ServiceDependency,
) -> ExpenseResponse:
    expense = service.create_expense(group_id=group_id, **expense_values(request))
    return ExpenseResponse.from_domain(expense)


def expense_values(request: EqualExpenseCreate | ExactExpenseCreate) -> dict:
    values = dict(
        description=request.description,
        amount=request.amount,
        payer_member_id=request.payer_member_id,
        occurred_at=request.occurred_at,
        split_strategy=SplitStrategy(request.split_strategy),
    )
    if isinstance(request, EqualExpenseCreate):
        values["participant_member_ids"] = tuple(request.participant_member_ids)
    else:
        values["splits"] = tuple(
            ExpenseSplit(split.member_id, split.amount) for split in request.splits
        )
    return values


@router.get(
    "/groups/{group_id}/expenses",
    response_model=list[ExpenseResponse],
    tags=["expenses"],
)
def list_expenses(group_id: UUID, service: ServiceDependency) -> list[ExpenseResponse]:
    expenses = service.list_expenses(group_id)
    audit = service.expense_audit(group_id)
    return [
        ExpenseResponse.from_domain(expense, audit.get(expense.id))
        for expense in expenses
    ]


@router.get(
    "/groups/{group_id}/expenses/{expense_id}",
    response_model=ExpenseResponse,
    tags=["expenses"],
)
def get_expense(
    group_id: UUID,
    expense_id: UUID,
    service: ServiceDependency,
) -> ExpenseResponse:
    expense = service.get_expense(group_id, expense_id)
    return ExpenseResponse.from_domain(
        expense, service.expense_audit(group_id).get(expense.id)
    )


@router.get(
    "/groups/{group_id}/balances", response_model=BalancesResponse, tags=["balances"]
)
def get_balances(group_id: UUID, service: ServiceDependency) -> BalancesResponse:
    group, values = service.get_balances(group_id)
    return BalancesResponse(
        group_id=group.id,
        currency=group.currency,
        balances=[
            MemberBalance(
                member_id=member.id, display_name=member.display_name, amount=amount
            )
            for member, amount in values
        ],
    )


@router.get(
    "/groups/{group_id}/settlement-suggestions",
    response_model=SettlementSuggestionsResponse,
    tags=["settlement-suggestions"],
)
def get_settlement_suggestions(
    group_id: UUID, service: ServiceDependency
) -> SettlementSuggestionsResponse:
    group, members, suggestions = service.get_settlement_suggestions(group_id)
    names = {member.id: member.display_name for member in members}
    return SettlementSuggestionsResponse(
        group_id=group.id,
        currency=group.currency,
        suggestions=[
            SettlementSuggestionResponse(
                from_member_id=suggestion.from_member_id,
                from_display_name=names[suggestion.from_member_id],
                to_member_id=suggestion.to_member_id,
                to_display_name=names[suggestion.to_member_id],
                amount=suggestion.amount,
            )
            for suggestion in suggestions
        ],
    )


@router.post(
    "/groups/{group_id}/settlements",
    response_model=SettlementResponse,
    status_code=201,
    tags=["settlements"],
)
def record_settlement(
    group_id: UUID, request: SettlementCreate, service: ServiceDependency
) -> SettlementResponse:
    settlement = service.record_settlement(
        group_id=group_id,
        from_member_id=request.from_member_id,
        to_member_id=request.to_member_id,
        amount=request.amount,
        occurred_at=request.occurred_at,
    )
    names = {
        member.id: member.display_name for member in service.list_members(group_id)
    }
    return SettlementResponse.from_domain(settlement, names)


@router.get(
    "/groups/{group_id}/settlements",
    response_model=list[SettlementResponse],
    tags=["settlements"],
)
def list_settlements(
    group_id: UUID, service: ServiceDependency
) -> list[SettlementResponse]:
    names = {
        member.id: member.display_name for member in service.list_members(group_id)
    }
    settlements = service.list_settlements(group_id)
    audit = service.settlement_audit(group_id)
    return [
        SettlementResponse.from_domain(settlement, names, audit.get(settlement.id))
        for settlement in settlements
    ]


@router.post(
    "/groups/{group_id}/expenses/{expense_id}/void",
    response_model=ExpenseResponse,
    tags=["expenses"],
)
def void_expense(
    group_id: UUID, expense_id: UUID, request: VoidRequest, service: ServiceDependency
) -> ExpenseResponse:
    service.void_expense(group_id, expense_id, request.reason)
    return get_expense(group_id, expense_id, service)


@router.post(
    "/groups/{group_id}/expenses/{expense_id}/corrections",
    response_model=ExpenseResponse,
    status_code=201,
    tags=["expenses"],
)
def correct_expense(
    group_id: UUID,
    expense_id: UUID,
    request: ExpenseCorrection,
    service: ServiceDependency,
) -> ExpenseResponse:
    replacement = service.correct_expense(
        group_id=group_id,
        target_id=expense_id,
        reason=request.reason,
        **expense_values(request.replacement),
    )
    return ExpenseResponse.from_domain(
        replacement, service.expense_audit(group_id).get(replacement.id)
    )


@router.post(
    "/groups/{group_id}/settlements/{settlement_id}/void",
    response_model=SettlementResponse,
    tags=["settlements"],
)
def void_settlement(
    group_id: UUID,
    settlement_id: UUID,
    request: VoidRequest,
    service: ServiceDependency,
) -> SettlementResponse:
    service.void_settlement(group_id, settlement_id, request.reason)
    settlement = service.get_settlement(group_id, settlement_id)
    names = {
        member.id: member.display_name for member in service.list_members(group_id)
    }
    return SettlementResponse.from_domain(
        settlement, names, service.settlement_audit(group_id).get(settlement_id)
    )


@router.post(
    "/groups/{group_id}/settlements/{settlement_id}/corrections",
    response_model=SettlementResponse,
    status_code=201,
    tags=["settlements"],
)
def correct_settlement(
    group_id: UUID,
    settlement_id: UUID,
    request: SettlementCorrection,
    service: ServiceDependency,
) -> SettlementResponse:
    replacement = service.correct_settlement(
        group_id=group_id,
        target_id=settlement_id,
        reason=request.reason,
        **request.replacement.model_dump(),
    )
    names = {
        member.id: member.display_name for member in service.list_members(group_id)
    }
    return SettlementResponse.from_domain(
        replacement, names, service.settlement_audit(group_id).get(replacement.id)
    )
