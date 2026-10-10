"""Claim existing guest identities with localized PostgreSQL transactions."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.service import ResourceNotFound, TripTabService
from app.domain import GroupMember, User
from app.persistence.mappers import member_from_row
from app.persistence.models import GroupMemberRow, GroupRow, TripInvitationRow

INVITATION_LIFETIME = timedelta(days=7)


class InvitationConflict(Exception):
    """The invitation or membership cannot transition to the requested state."""


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def preview_invitation(session: Session, token: str) -> dict:
    row = session.scalar(
        select(TripInvitationRow).where(
            TripInvitationRow.token_hash == token_digest(token)
        )
    )
    if row is None or row.status != "pending":
        raise ResourceNotFound("invitation unavailable")
    member = session.get(GroupMemberRow, row.target_member_id)
    if member is None or member.user_id is not None:
        raise ResourceNotFound("invitation unavailable")
    group = session.get(GroupRow, row.group_id)
    return {
        "trip_name": group.name,
        "member_display_name": member.display_name,
        "expires_at": row.expires_at,
    }


class InvitationService:
    def __init__(self, session: Session, current_user: User) -> None:
        self.session = session
        self.current_user = current_user
        self.trips = TripTabService(session, current_user)

    def _member(self, group_id: UUID, member_id: UUID) -> GroupMemberRow:
        row = self.session.scalar(
            select(GroupMemberRow)
            .where(GroupMemberRow.group_id == group_id, GroupMemberRow.id == member_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ResourceNotFound("member not found")
        return row

    def _lock_invitation(
        self, row: TripInvitationRow
    ) -> tuple[TripInvitationRow, GroupMemberRow]:
        # All transitions lock target member BEFORE invitation to avoid deadlocks.
        if row.target_member_id is None:
            raise ResourceNotFound("invitation unavailable")
        member = self._member(row.group_id, row.target_member_id)
        invitation = self.session.scalar(
            select(TripInvitationRow)
            .where(TripInvitationRow.id == row.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return invitation, member

    def create(self, group_id: UUID, member_id: UUID) -> tuple[TripInvitationRow, str]:
        with self.session.begin():
            self.trips._require_owner(group_id)
            member = self._member(group_id, member_id)
            if member.user_id is not None or member.role != "member":
                raise InvitationConflict("traveler is already account-linked")
            now = datetime.now(UTC)
            self.session.execute(
                update(TripInvitationRow)
                .where(
                    TripInvitationRow.group_id == group_id,
                    TripInvitationRow.target_member_id == member_id,
                    TripInvitationRow.accepted_at.is_(None),
                    TripInvitationRow.revoked_at.is_(None),
                )
                .values(revoked_at=now, revoked_by_user_id=self.current_user.id)
            )
            token = secrets.token_urlsafe(32)
            row = TripInvitationRow(
                id=uuid4(),
                group_id=group_id,
                target_member_id=member_id,
                target_member_snapshot_id=member_id,
                token_hash=token_digest(token),
                created_by_user_id=self.current_user.id,
                created_at=now,
                expires_at=now + INVITATION_LIFETIME,
            )
            self.session.add(row)
            self.session.flush()
        return row, token

    def list(self, group_id: UUID) -> tuple[TripInvitationRow, ...]:
        self.trips._require_owner(group_id)
        return tuple(
            self.session.scalars(
                select(TripInvitationRow)
                .where(TripInvitationRow.group_id == group_id)
                .order_by(
                    TripInvitationRow.created_at.desc(), TripInvitationRow.id.desc()
                )
            )
        )

    def revoke(self, group_id: UUID, invitation_id: UUID) -> TripInvitationRow:
        with self.session.begin():
            self.trips._require_owner(group_id)
            row = self.session.scalar(
                select(TripInvitationRow).where(
                    TripInvitationRow.id == invitation_id,
                    TripInvitationRow.group_id == group_id,
                )
            )
            if row is None:
                raise ResourceNotFound("invitation not found")
            if row.status != "pending":
                raise InvitationConflict("invitation is no longer pending")
            row, _member = self._lock_invitation(row)
            if row.status != "pending":
                raise InvitationConflict("invitation is no longer pending")
            row.revoked_at = datetime.now(UTC)
            row.revoked_by_user_id = self.current_user.id
            self.session.flush()
        return row

    def accept(self, token: str) -> GroupMember:
        try:
            with self.session.begin():
                row = self.session.scalar(
                    select(TripInvitationRow).where(
                        TripInvitationRow.token_hash == token_digest(token)
                    )
                )
                if row is None:
                    raise ResourceNotFound("invitation unavailable")
                row, member = self._lock_invitation(row)
                if row.accepted_at is not None:
                    if (
                        row.accepted_by_user_id == self.current_user.id
                        and member.user_id == self.current_user.id
                    ):
                        return member_from_row(member)
                    raise InvitationConflict("invitation was already accepted")
                now = datetime.now(UTC)
                if row.revoked_at is not None or row.expires_at <= now:
                    raise ResourceNotFound("invitation unavailable")
                if member.user_id is not None:
                    raise InvitationConflict("traveler is already account-linked")
                if self.trips.repo.get_membership(row.group_id, self.current_user.id):
                    raise InvitationConflict(
                        "account already has a traveler in this trip"
                    )
                # Change the account association only, never financial identity/history.
                member.user_id = self.current_user.id
                row.accepted_at = now
                row.accepted_by_user_id = self.current_user.id
                self.session.flush()
                result = member_from_row(member)
            return result
        except IntegrityError as error:
            constraint = getattr(
                getattr(error.orig, "diag", None), "constraint_name", None
            )
            if constraint == "uq_group_members_group_user":
                raise InvitationConflict(
                    "account already has a traveler in this trip"
                ) from None
            raise
