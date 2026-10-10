"""Invitation bodies keep bearer secrets out of URLs and validation diagnostics."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, Field, SecretStr

from app.api.dependencies import (
    CurrentUserDependency,
    SessionDependency,
    require_origin,
)
from app.api.schemas import MemberResponse, RequestModel
from app.application.invitations import InvitationService, preview_invitation
from app.persistence.models import TripInvitationRow

router = APIRouter(prefix="/api/v1", tags=["invitations"])


class InvitationToken(RequestModel):
    token: Annotated[SecretStr, Field(min_length=43, max_length=43)]


class InvitationResponse(RequestModel):
    id: UUID
    group_id: UUID
    target_member_id: UUID
    created_by_user_id: UUID
    created_at: AwareDatetime
    expires_at: AwareDatetime
    accepted_at: AwareDatetime | None
    accepted_by_user_id: UUID | None
    revoked_at: AwareDatetime | None
    revoked_by_user_id: UUID | None
    status: Literal["pending", "accepted", "revoked", "expired"]

    @classmethod
    def from_row(cls, row: TripInvitationRow) -> "InvitationResponse":
        return cls(**{name: getattr(row, name) for name in cls.model_fields})


class CreatedInvitation(InvitationResponse):
    token: str


class InvitationPreview(RequestModel):
    trip_name: str
    member_display_name: str
    expires_at: AwareDatetime


def service(
    session: SessionDependency, current: CurrentUserDependency
) -> InvitationService:
    return InvitationService(session, current.user)


Service = Annotated[InvitationService, Depends(service)]


@router.post(
    "/groups/{group_id}/members/{member_id}/invitations",
    response_model=CreatedInvitation,
    status_code=201,
)
def create(
    group_id: UUID,
    member_id: UUID,
    invitations: Service,
    payload: RequestModel | None = None,
) -> CreatedInvitation:
    row, token = invitations.create(group_id, member_id)
    return CreatedInvitation(
        **InvitationResponse.from_row(row).model_dump(), token=token
    )


@router.get("/groups/{group_id}/invitations", response_model=list[InvitationResponse])
def list_invitations(group_id: UUID, invitations: Service) -> list[InvitationResponse]:
    return [InvitationResponse.from_row(row) for row in invitations.list(group_id)]


@router.post(
    "/groups/{group_id}/invitations/{invitation_id}/revoke",
    response_model=InvitationResponse,
)
def revoke(
    group_id: UUID,
    invitation_id: UUID,
    invitations: Service,
    payload: RequestModel | None = None,
) -> InvitationResponse:
    return InvitationResponse.from_row(invitations.revoke(group_id, invitation_id))


@router.post(
    "/invitations/preview",
    response_model=InvitationPreview,
    dependencies=[Depends(require_origin)],
)
def preview(payload: InvitationToken, session: SessionDependency) -> InvitationPreview:
    return InvitationPreview(
        **preview_invitation(session, payload.token.get_secret_value())
    )


@router.post("/invitations/accept", response_model=MemberResponse)
def accept(payload: InvitationToken, invitations: Service) -> MemberResponse:
    return MemberResponse.from_domain(
        invitations.accept(payload.token.get_secret_value())
    )
