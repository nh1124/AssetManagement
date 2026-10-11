from datetime import datetime
import enum

from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Boolean, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from ..database import Base

class AccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    INCOME = "income"
    EXPENSE = "expense"


class AccountRole(str, enum.Enum):
    DEFENSE = "defense"
    GROWTH = "growth"
    EARMARKED = "earmarked"
    OPERATING = "operating"
    UNASSIGNED = "unassigned"


class Account(Base):
    """Double-entry accounting: Each account has a type and balance."""
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint('client_id', 'name', name='_client_account_uc'),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    account_type = Column(String)  # asset, liability, income, expense
    balance = Column(Float, default=0)
    parent_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    expected_return = Column(Float, default=0.0)  # Annual return rate % for asset accounts
    role = Column(String, default=AccountRole.UNASSIGNED.value, server_default=AccountRole.UNASSIGNED.value, nullable=False)
    role_target_amount = Column(Float, nullable=True)
    liability_kind = Column(String, nullable=True)  # card | loan | other; only a card settles monthly
    liability_closing_day = Column(Integer, nullable=True)
    liability_payment_day = Column(Integer, nullable=True)
    liability_payment_month_offset = Column(Integer, default=0, server_default="0", nullable=False)
    liability_payment_policy = Column(String, default="full", server_default="full", nullable=False)
    liability_minimum_payment = Column(Float, nullable=True)
    liability_fixed_payment_amount = Column(Float, nullable=True)
    liability_installment_months = Column(Integer, nullable=True)
    liability_revolving_rate = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    
    client = relationship("Client", back_populates="accounts")
    entries = relationship("JournalEntry", back_populates="account")


class JournalEntry(Base):
    """One leg of a transaction: an account, an amount, and a direction.

    A transaction has two or more of these and the two sides must balance.
    This is the only place that says which account a transaction touched, so
    a compound entry -- a card payment split across an expense account and a
    receivable, say -- is simply a transaction with three legs.
    """
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), index=True)
    debit = Column(Float, default=0)
    credit = Column(Float, default=0)
    memo = Column(String, nullable=True)  # per-leg note, e.g. "own share" / "advance for A"
    sort_order = Column(Integer, nullable=True)
    
    account = relationship("Account", back_populates="entries")
    transaction = relationship("Transaction", back_populates="journal_entries")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    date = Column(Date)
    description = Column(String)
    amount = Column(Float)
    currency = Column(String, default='JPY')
    batch_id = Column(Integer, ForeignKey("transaction_batches.id"), nullable=True)
    # NULL means entered by hand or posted before provenance was recorded.
    recurring_transaction_id = Column(
        Integer,
        ForeignKey("recurring_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    
    client = relationship("Client", back_populates="transactions")
    batch = relationship("TransactionBatch", back_populates="transactions")
    recurring_transaction = relationship("RecurringTransaction", foreign_keys=[recurring_transaction_id])
    # No from_account_id / to_account_id columns: the legs are the accounts.
    # Both are still accepted as input and still reported, derived by
    # services.journal_legs.primary_accounts from the leg on each side.
    journal_entries = relationship("JournalEntry", back_populates="transaction")


class TransactionProposal(Base):
    __tablename__ = "transaction_proposals"
    __table_args__ = (
        UniqueConstraint("client_id", "idempotency_key", name="_client_transaction_proposal_idempotency_uc"),
    )

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    origin = Column(String, nullable=False)
    origin_ref = Column(JSON, nullable=False, default=dict)
    date = Column(Date, nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="JPY")
    legs = Column(JSON, nullable=False)
    # The cause may be deleted; SET NULL preserves the record of the proposal.
    trigger_transaction_id = Column(
        Integer,
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String, nullable=False, default="pending", index=True)
    # The result may be deleted; SET NULL preserves the record of the proposal.
    posted_transaction_id = Column(
        Integer,
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key = Column(String, nullable=False)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
