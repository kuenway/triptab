"""Persistence tests use PostgreSQL, never an in-memory database substitute."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import AccountingValidationError, calculate_balances
from app.domain import (
    Expense,
    ExpenseSplit,
    Group,
    GroupMember,
    Settlement,
    SplitStrategy,
    User,
)
from app.persistence.models import (
    ExpenseRow,
    ExpenseSplitRow,
    GroupMemberRow,
    SettlementRow,
    UserRow,
)
from app.persistence.repository import LedgerRepository

pytestmark = pytest.mark.integration

OCCURRED = datetime(2026, 10, 2, 20, 0, tzinfo=timezone(timedelta(hours=8)))
RECORDED = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


def seed_group(session: Session) -> tuple[User, Group, tuple[GroupMember, ...]]:
    repo = LedgerRepository(session)
    user = User(id=uuid4(), email=f"{uuid4()}@example.test", display_name="Alice")
    group = Group(id=uuid4(), name="Trip")
    members = (
        GroupMember(
            id=uuid4(), group_id=group.id, display_name="Alice", user_id=user.id
        ),
        GroupMember(id=uuid4(), group_id=group.id, display_name="Bob"),
        GroupMember(id=uuid4(), group_id=group.id, display_name="Carol"),
    )
    repo.save_user(user)
    repo.save_group(group)
    for member in members:
        repo.save_member(member)
    return user, group, members


def make_expense(user: User, group: Group, members: tuple[GroupMember, ...]) -> Expense:
    return Expense(
        id=uuid4(),
        group_id=group.id,
        payer_member_id=members[0].id,
        description="Dinner",
        amount_minor=900,
        split_strategy=SplitStrategy.EQUAL,
        splits=tuple(ExpenseSplit(member.id, 300) for member in members),
        occurred_at=OCCURRED,
        created_at=RECORDED,
        created_by_user_id=user.id,
    )


def make_settlement(
    user: User, group: Group, sender: GroupMember, recipient: GroupMember
) -> Settlement:
    return Settlement(
        id=uuid4(),
        group_id=group.id,
        from_member_id=sender.id,
        to_member_id=recipient.id,
        amount_minor=100,
        occurred_at=OCCURRED,
        created_at=RECORDED,
        created_by_user_id=user.id,
    )


def test_user_group_and_both_member_kinds_round_trip(db_session: Session) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
    db_session.expunge_all()
    repo = LedgerRepository(db_session)

    assert repo.get_user(user.id) == user
    assert repo.get_group(group.id) == group
    assert repo.get_member(members[0].id) == members[0]
    assert repo.get_member(members[1].id) == members[1]
    assert not repo.get_member(members[0].id).is_guest
    assert repo.get_member(members[1].id).is_guest
    assert set(repo.list_members(group.id)) == set(members)
    assert db_session.get(UserRow, user.id).created_at.utcoffset() is not None


def test_expense_and_settlement_round_trip_preserves_domain_meaning(
    db_session: Session,
) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
        expense = make_expense(user, group, members)
        settlement = make_settlement(user, group, members[1], members[0])
        repo = LedgerRepository(db_session)
        repo.save_expense(expense)
        repo.save_settlement(settlement)
    db_session.expunge_all()
    repo = LedgerRepository(db_session)

    loaded_expense = repo.get_expense(expense.id)
    loaded_settlement = repo.get_settlement(settlement.id)
    assert loaded_expense == replace(
        expense, splits=tuple(sorted(expense.splits, key=lambda s: s.member_id))
    )
    assert loaded_settlement == settlement
    assert loaded_expense.occurred_at.utcoffset() is not None
    assert loaded_expense.created_at.utcoffset() is not None
    assert loaded_expense.occurred_at != loaded_expense.created_at
    assert loaded_expense.split_strategy is SplitStrategy.EQUAL
    assert isinstance(loaded_expense.amount_minor, int)
    assert loaded_expense.payer_member_id == members[0].id
    assert {split.member_id: split.amount_minor for split in loaded_expense.splits} == {
        member.id: 300 for member in members
    }
    assert repo.list_expenses(group.id) == (loaded_expense,)
    assert repo.list_settlements(group.id) == (loaded_settlement,)


def test_persisted_history_feeds_existing_accounting_engine(
    db_session: Session,
) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
        LedgerRepository(db_session).save_expense(make_expense(user, group, members))
    db_session.expunge_all()
    repo = LedgerRepository(db_session)

    balances = calculate_balances(
        repo.get_group(group.id),
        repo.list_members(group.id),
        repo.list_expenses(group.id),
        repo.list_settlements(group.id),
    )
    assert balances == {
        members[0].id: 600,
        members[1].id: -300,
        members[2].id: -300,
    }


def test_missing_group_member_reference_is_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        with db_session.begin():
            db_session.add(
                GroupMemberRow(id=uuid4(), group_id=uuid4(), display_name="X")
            )
            db_session.flush()


def test_cross_group_payer_is_rejected_by_database(db_session: Session) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
        other = Group(id=uuid4(), name="Other")
        LedgerRepository(db_session).save_group(other)
        foreign = GroupMember(id=uuid4(), group_id=other.id, display_name="X")
        LedgerRepository(db_session).save_member(foreign)

    with pytest.raises(IntegrityError):
        with db_session.begin():
            db_session.add(
                ExpenseRow(
                    id=uuid4(),
                    group_id=group.id,
                    payer_member_id=foreign.id,
                    description="Invalid",
                    amount_minor=10,
                    split_strategy="exact",
                    occurred_at=OCCURRED,
                    created_at=RECORDED,
                    created_by_user_id=user.id,
                )
            )
            db_session.flush()


def test_cross_group_split_is_rejected_by_database(db_session: Session) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
        other = Group(id=uuid4(), name="Other")
        LedgerRepository(db_session).save_group(other)
        foreign = GroupMember(id=uuid4(), group_id=other.id, display_name="X")
        LedgerRepository(db_session).save_member(foreign)
        expense = make_expense(user, group, members)
        LedgerRepository(db_session).save_expense(expense)

    with pytest.raises(IntegrityError):
        with db_session.begin():
            db_session.add(
                ExpenseSplitRow(
                    expense_id=expense.id,
                    group_id=group.id,
                    member_id=foreign.id,
                    amount_minor=0,
                )
            )
            db_session.flush()


@pytest.mark.parametrize("foreign_side", ["from_member_id", "to_member_id"])
def test_cross_group_settlement_is_rejected_by_database(
    db_session: Session, foreign_side: str
) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
        other = Group(id=uuid4(), name="Other")
        LedgerRepository(db_session).save_group(other)
        foreign = GroupMember(id=uuid4(), group_id=other.id, display_name="X")
        LedgerRepository(db_session).save_member(foreign)

    values = {"from_member_id": members[1].id, "to_member_id": members[0].id}
    values[foreign_side] = foreign.id
    with pytest.raises(IntegrityError):
        with db_session.begin():
            db_session.add(
                SettlementRow(
                    id=uuid4(),
                    group_id=group.id,
                    amount_minor=100,
                    occurred_at=OCCURRED,
                    created_at=RECORDED,
                    created_by_user_id=user.id,
                    **values,
                )
            )
            db_session.flush()


@pytest.mark.parametrize("kind", ["expense", "split", "settlement"])
def test_database_rejects_invalid_local_amount(db_session: Session, kind: str) -> None:
    extra_member_id: UUID | None = None
    with db_session.begin():
        user, group, members = seed_group(db_session)
        expense = make_expense(user, group, members)
        if kind == "split":
            extra_member = GroupMember(id=uuid4(), group_id=group.id, display_name="D")
            LedgerRepository(db_session).save_member(extra_member)
            extra_member_id = extra_member.id
            LedgerRepository(db_session).save_expense(expense)

    with pytest.raises(IntegrityError):
        with db_session.begin():
            if kind == "expense":
                db_session.add(
                    ExpenseRow(
                        id=uuid4(),
                        group_id=group.id,
                        payer_member_id=members[0].id,
                        description="Invalid",
                        amount_minor=0,
                        split_strategy="exact",
                        occurred_at=OCCURRED,
                        created_at=RECORDED,
                        created_by_user_id=user.id,
                    )
                )
            elif kind == "split":
                assert extra_member_id is not None
                db_session.add(
                    ExpenseSplitRow(
                        expense_id=expense.id,
                        group_id=group.id,
                        member_id=extra_member_id,
                        amount_minor=-1,
                    )
                )
            else:
                db_session.add(
                    SettlementRow(
                        id=uuid4(),
                        group_id=group.id,
                        from_member_id=members[1].id,
                        to_member_id=members[0].id,
                        amount_minor=0,
                        occurred_at=OCCURRED,
                        created_at=RECORDED,
                        created_by_user_id=user.id,
                    )
                )
            db_session.flush()


def test_invalid_expense_total_is_rejected_before_write(db_session: Session) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
    invalid = replace(
        make_expense(user, group, members),
        splits=(ExpenseSplit(members[1].id, 899),),
    )

    with pytest.raises(AccountingValidationError):
        with db_session.begin():
            LedgerRepository(db_session).save_expense(invalid)
    assert db_session.get(ExpenseRow, invalid.id) is None


def test_failed_split_write_rolls_back_parent_expense(db_session: Session) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
        extra_member = GroupMember(id=uuid4(), group_id=group.id, display_name="D")
        LedgerRepository(db_session).save_member(extra_member)
    expense = make_expense(user, group, members)

    with pytest.raises(IntegrityError):
        with db_session.begin():
            LedgerRepository(db_session).save_expense(expense)
            db_session.add(
                ExpenseSplitRow(
                    expense_id=expense.id,
                    group_id=group.id,
                    member_id=extra_member.id,
                    amount_minor=-1,
                )
            )
            db_session.flush()
    assert db_session.get(ExpenseRow, expense.id) is None


def test_failed_settlement_write_rolls_back(db_session: Session) -> None:
    with db_session.begin():
        user, group, members = seed_group(db_session)
    transfer = make_settlement(user, group, members[1], members[0])

    with pytest.raises(IntegrityError):
        with db_session.begin():
            LedgerRepository(db_session).save_settlement(transfer)
            db_session.add(
                SettlementRow(
                    id=uuid4(),
                    group_id=group.id,
                    from_member_id=members[1].id,
                    to_member_id=members[0].id,
                    amount_minor=0,
                    occurred_at=OCCURRED,
                    created_at=RECORDED,
                    created_by_user_id=user.id,
                )
            )
            db_session.flush()
    assert db_session.get(SettlementRow, transfer.id) is None


def test_expected_constraints_exist_on_migrated_schema(pg_engine: Engine) -> None:
    inspector = inspect(pg_engine)
    assert {
        "users",
        "groups",
        "group_members",
        "expenses",
        "expense_splits",
        "settlements",
    }.issubset(inspector.get_table_names())
    assert "ck_expenses_amount_positive" in {
        item["name"] for item in inspector.get_check_constraints("expenses")
    }
    assert "ck_expense_splits_amount_nonnegative" in {
        item["name"] for item in inspector.get_check_constraints("expense_splits")
    }
    assert "ck_settlements_amount_positive" in {
        item["name"] for item in inspector.get_check_constraints("settlements")
    }
    assert "fk_expenses_group_payer_member" in {
        item["name"] for item in inspector.get_foreign_keys("expenses")
    }
    assert "fk_expense_splits_group_member" in {
        item["name"] for item in inspector.get_foreign_keys("expense_splits")
    }
    assert {"fk_settlements_group_sender", "fk_settlements_group_recipient"}.issubset(
        {item["name"] for item in inspector.get_foreign_keys("settlements")}
    )
