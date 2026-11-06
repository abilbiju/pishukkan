from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, DateTime, Date, Numeric, Boolean, Text, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # income, expense, transfer, refund, lent, borrowed, repayment
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    category: Mapped[str] = mapped_column(String(80), default="Other", index=True)
    description: Mapped[str] = mapped_column(String(300))
    merchant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source: Mapped[str] = mapped_column(String(24), default="manual")
    receipt_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    __table_args__ = (Index("ix_tx_user_date", "user_id", "occurred_on"),)

class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(80), default="Overall")
    month: Mapped[str] = mapped_column(String(7))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    __table_args__ = (Index("ix_budget_user_month", "user_id", "month"),)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(40))
    transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
