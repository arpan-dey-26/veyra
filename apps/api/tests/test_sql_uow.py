"""SQL unit of work: INSERT order must follow call order (FK parents first).

Regression: without ORM relationships SQLAlchemy may emit a donor/session/membership INSERT
before its user INSERT; PostgreSQL then rejects the FK and the API answered 409 "conflict".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError
from app.core.ids import uuid7
from app.modules.donors.models import Donor
from app.modules.identity.errors import EmailTakenError
from app.modules.identity.models import User
from app.persistence.sql import SqlUnitOfWork

NOW = datetime(2026, 9, 28, tzinfo=UTC)


class RecordingSession:
    """Stands in for AsyncSession: records what reaches the database, in order."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.pending: list[object] = []
        self.flushed: list[str] = []
        self.fail_with = fail_with
        self.rolled_back = False

    def add(self, row: object) -> None:
        self.pending.append(row)

    async def flush(self) -> None:
        if self.fail_with:
            raise self.fail_with
        self.flushed.extend(type(r).__name__ for r in self.pending)
        self.pending.clear()

    async def rollback(self) -> None:
        self.rolled_back = True


def _user() -> User:
    return User(
        id=uuid7(),
        email="a@b.in",
        mobile="+919999999999",
        full_name="A B",
        password_hash="x",
        role="DONOR",
        status="active",
        is_demo=False,
        failed_login_count=0,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_parent_rows_reach_the_database_before_dependants() -> None:
    session = RecordingSession()
    uow = SqlUnitOfWork(session)  # type: ignore[arg-type]
    user = _user()
    await uow.users.add(user)
    await uow.donors.add(
        Donor(
            id=uuid7(),
            user_id=user.id,
            blood_group="O+",
            address="12 Park St",
            city="Kolkata",
            state="West Bengal",
            pin_code="700016",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    assert session.flushed == ["User", "Donor"]


def _integrity(constraint: str) -> IntegrityError:
    class Orig(Exception):
        pass

    return IntegrityError("INSERT", {}, Orig(f'violates unique constraint "{constraint}"'))


@pytest.mark.parametrize(
    ("constraint", "error"),
    [("uq_users_email", EmailTakenError), ("fk_donors_user_id_users", ConflictError)],
)
async def test_flush_time_constraint_errors_are_mapped(constraint: str, error: Any) -> None:
    session = RecordingSession(fail_with=_integrity(constraint))
    uow = SqlUnitOfWork(session)  # type: ignore[arg-type]
    with pytest.raises(error):
        await uow.users.add(_user())
    assert session.rolled_back
