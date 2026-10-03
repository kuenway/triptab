"""Thin versioned routes calling application use cases."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_service
from app.api.schemas import (
    BalancesResponse,
    EqualExpenseCreate,
    ExactExpenseCreate,
    ExpenseCreate,
    ExpenseResponse,
    GroupCreate,
    GroupResponse,
    MemberBalance,
    MemberCreate,
    MemberResponse,
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
    if isinstance(request, EqualExpenseCreate):
        expense = service.create_expense(
            group_id=group_id,
            description=request.description,
            amount=request.amount,
            payer_member_id=request.payer_member_id,
            split_strategy=SplitStrategy.EQUAL,
            participant_member_ids=tuple(request.participant_member_ids),
            occurred_at=request.occurred_at,
        )
    else:
        assert isinstance(request, ExactExpenseCreate)
        expense = service.create_expense(
            group_id=group_id,
            description=request.description,
            amount=request.amount,
            payer_member_id=request.payer_member_id,
            split_strategy=SplitStrategy.EXACT,
            splits=tuple(
                ExpenseSplit(member_id=split.member_id, amount_minor=split.amount)
                for split in request.splits
            ),
            occurred_at=request.occurred_at,
        )
    return ExpenseResponse.from_domain(expense)


@router.get(
    "/groups/{group_id}/expenses",
    response_model=list[ExpenseResponse],
    tags=["expenses"],
)
def list_expenses(group_id: UUID, service: ServiceDependency) -> list[ExpenseResponse]:
    return [
        ExpenseResponse.from_domain(expense)
        for expense in service.list_expenses(group_id)
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
    return ExpenseResponse.from_domain(service.get_expense(group_id, expense_id))


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
