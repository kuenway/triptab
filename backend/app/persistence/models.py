"""SQLAlchemy storage representations; domain behavior lives elsewhere."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class Base(DeclarativeBase):
    metadata = metadata


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(trim(email)) > 0", name="email_nonblank"),
        CheckConstraint("email = lower(trim(email))", name="email_normalized"),
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_nonblank"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # NULL keeps historical users valid without making them login accounts.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class GroupRow(Base):
    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_nonblank"),
        CheckConstraint("currency = 'TWD'", name="currency_twd"),
        CheckConstraint("currency_scale = 0", name="currency_scale_zero"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="TWD"
    )
    currency_scale: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class GroupMemberRow(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "id", name="uq_group_members_group_id_id"),
        UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
        CheckConstraint("role IN ('owner', 'member')", name="role_supported"),
        CheckConstraint("role <> 'owner' OR user_id IS NOT NULL", name="owner_account"),
        Index(
            "uq_group_members_owner",
            "group_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
        Index("ix_group_members_user_id", "user_id"),
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_nonblank"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="member"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class ExpenseRow(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        UniqueConstraint("id", "group_id", name="uq_expenses_id_group_id"),
        ForeignKeyConstraint(
            ["group_id", "payer_member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_expenses_group_payer_member",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint(
            "split_strategy IN ('equal', 'exact')", name="split_strategy_supported"
        ),
        CheckConstraint("length(trim(description)) > 0", name="description_nonblank"),
        Index("ix_expenses_group_created_at", "group_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payer_member_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    split_strategy: Mapped[str] = mapped_column(String(10), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    splits: Mapped[list["ExpenseSplitRow"]] = relationship(
        back_populates="expense", lazy="selectin"
    )


class ExpenseSplitRow(Base):
    __tablename__ = "expense_splits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["expense_id", "group_id"],
            ["expenses.id", "expenses.group_id"],
            name="fk_expense_splits_expense_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["group_id", "member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_expense_splits_group_member",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount_minor >= 0", name="amount_nonnegative"),
    )

    expense_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    member_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expense: Mapped[ExpenseRow] = relationship(back_populates="splits")


class SettlementRow(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        UniqueConstraint("id", "group_id", name="uq_settlements_id_group_id"),
        ForeignKeyConstraint(
            ["group_id", "from_member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_settlements_group_sender",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["group_id", "to_member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_settlements_group_recipient",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint("from_member_id <> to_member_id", name="different_members"),
        Index("ix_settlements_group_created_at", "group_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_member_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    to_member_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ExpenseVoidRow(Base):
    __tablename__ = "expense_voids"
    __table_args__ = (
        ForeignKeyConstraint(
            ["expense_id", "group_id"],
            ["expenses.id", "expenses.group_id"],
            name="fk_expense_voids_target_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_id", "group_id"],
            ["expenses.id", "expenses.group_id"],
            name="fk_expense_voids_replacement_group",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="reason_nonblank"),
        CheckConstraint("replacement_id <> expense_id", name="new_replacement"),
        Index("ix_expense_voids_group_id", "group_id"),
    )

    expense_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    replacement_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        unique=True,
    )


class SettlementVoidRow(Base):
    __tablename__ = "settlement_voids"
    __table_args__ = (
        ForeignKeyConstraint(
            ["settlement_id", "group_id"],
            ["settlements.id", "settlements.group_id"],
            name="fk_settlement_voids_target_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_id", "group_id"],
            ["settlements.id", "settlements.group_id"],
            name="fk_settlement_voids_replacement_group",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="reason_nonblank"),
        CheckConstraint("replacement_id <> settlement_id", name="new_replacement"),
        Index("ix_settlement_voids_group_id", "group_id"),
    )

    settlement_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    replacement_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        unique=True,
    )


class AuthSessionRow(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),
        CheckConstraint("length(csrf_token) = 43", name="csrf_token_length"),
        CheckConstraint("expires_at > created_at", name="expiration_after_creation"),
        Index("ix_auth_sessions_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(43), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TripInvitationRow(Base):
    """Account claiming permission; never contains the raw bearer token."""

    __tablename__ = "trip_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        ForeignKeyConstraint(
            ["group_id", "target_member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_trip_invitations_group_target_member",
            ondelete="RESTRICT",
        ),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),
        CheckConstraint("expires_at > created_at", name="expiration_after_creation"),
        CheckConstraint(
            "(accepted_at IS NULL) = (accepted_by_user_id IS NULL)",
            name="accepted_metadata",
        ),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_user_id IS NULL)",
            name="revoked_metadata",
        ),
        CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL", name="one_terminal_state"
        ),
        CheckConstraint(
            "accepted_at IS NULL OR "
            "(accepted_at >= created_at AND accepted_at < expires_at)",
            name="accepted_time",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="revoked_time"
        ),
        CheckConstraint(
            "target_member_id IS NOT NULL OR revoked_at IS NOT NULL",
            name="detached_only_when_revoked",
        ),
        CheckConstraint(
            "target_member_id IS NULL OR target_member_id = target_member_snapshot_id",
            name="target_matches_snapshot",
        ),
        Index("ix_trip_invitations_group_target", "group_id", "target_member_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("groups.id", ondelete="RESTRICT")
    )
    target_member_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    target_member_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )

    @property
    def status(self) -> str:
        if self.accepted_at is not None:
            return "accepted"
        if self.revoked_at is not None:
            return "revoked"
        return "expired" if self.expires_at <= datetime.now(UTC) else "pending"
