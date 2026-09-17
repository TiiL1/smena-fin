from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    rate: Mapped[float] = mapped_column(Float, default=8650)
    default_advance: Mapped[float] = mapped_column(Float, default=80000)
    unallocated_balance: Mapped[float] = mapped_column(Float, default=0)
    employer_debt: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    shifts: Mapped[list["Shift"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    goals: Mapped[list["Goal"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    incomes: Mapped[list["Income"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    fixed_costs: Mapped[list["FixedCost"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_shift_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    date: Mapped[str] = mapped_column(String(10))  # 'YYYY-MM-DD'
    coefficient: Mapped[float] = mapped_column(Float)

    user: Mapped[User] = relationship(back_populates="shifts")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    type: Mapped[str] = mapped_column(String(10))  # 'advance' | 'salary'
    for_month: Mapped[str] = mapped_column(String(7))  # 'YYYY-MM'
    calculated_amount: Mapped[float] = mapped_column(Float)
    actual_amount: Mapped[float] = mapped_column(Float)
    debt_after: Mapped[float] = mapped_column(Float)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="transactions")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str] = mapped_column(String(30))
    target_amount: Mapped[float] = mapped_column(Float)
    current_amount: Mapped[float] = mapped_column(Float, default=0)
    split_percent: Mapped[float] = mapped_column(Float, default=0)
    target_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 'YYYY-MM-DD'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="goals")
    contributions: Mapped[list["GoalContribution"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class GoalContribution(Base):
    """One deposit into a goal (top-up or a slice of a split), timestamped so
    we can compute a real pace instead of guessing from the current total."""

    __tablename__ = "goal_contributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(Integer, ForeignKey("goals.id"))
    amount: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    goal: Mapped[Goal] = relationship(back_populates="contributions")


class Expense(Base):
    """One-off spending, paid out of the unallocated balance."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(50), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    spent_at: Mapped[str] = mapped_column(String(10))  # 'YYYY-MM-DD'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="expenses")


class Income(Base):
    """Side income (courier gig, sale, gift...): lands straight in the
    unallocated balance, separate from salary payouts on purpose — payouts
    carry forMonth/debt logic that gig money must never touch."""

    __tablename__ = "incomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    amount: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    received_at: Mapped[str] = mapped_column(String(10))  # 'YYYY-MM-DD'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="incomes")


class FixedCost(Base):
    """Monthly obligation due on `day` (1-31), e.g. rent, loan, subscriptions."""

    __tablename__ = "fixed_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)
    day: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="fixed_costs")


DEFAULT_GOALS = [
    {"name": "Фонд поездки", "icon": "plane", "target_amount": 300000, "split_percent": 30},
    {"name": "Инвестиции", "icon": "trendingUp", "target_amount": 500000, "split_percent": 30},
    {"name": "Подушка безопасности", "icon": "shield", "target_amount": 400000, "split_percent": 40},
]
