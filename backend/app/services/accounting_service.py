"""Backwards-compatible facade over ledger_service and reporting_service.

The original accounting_service mixed two independent concerns. It was split
in P6-001; this module re-exports both halves so existing imports keep
resolving. Prefer importing from ledger_service or reporting_service directly.
"""
from __future__ import annotations

from .ledger_service import (  # noqa: F401
    DEBIT_NORMAL_TYPES,
    DEFAULT_ACCOUNTS,
    calculate_account_journal_balance,
    ensure_default_accounts,
    get_or_create_account,
    post_transaction_journal,
    process_transaction,
    revert_transaction,
    update_transaction,
)
from .reporting_service import (  # noqa: F401
    get_account_flows_for_range,
    get_account_transactions_for_range,
    get_balance_sheet,
    get_profit_loss,
    get_profit_loss_for_range,
    get_profit_loss_rollup,
    get_profit_loss_rollup_for_range,
    get_variance_analysis,
    get_variance_analysis_for_range,
)
