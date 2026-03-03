from typing import Any, Dict

from config import get as config_get
from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


@register_tool("get_cash_balance", description="Retrieve cash balance information from Interactive Brokers.")
async def get_cash_balance(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    ibkr_cfg = config_get("ibkr", {}) or {}

    reserve_currency = str(ibkr_cfg.get("cash_reserve_currency", "BASE")).strip().upper() or "BASE"

    excluded_currencies_raw = ibkr_cfg.get("excluded_cash_currencies", []) or []
    if not isinstance(excluded_currencies_raw, list):
        excluded_currencies_raw = [excluded_currencies_raw]
        
    excluded_currencies = {
        str(currency).strip().upper()
        for currency in excluded_currencies_raw
        if str(currency).strip()
    }

    try:
        min_cash_reserve = float(ibkr_cfg.get("min_cash_reserve", 0) or 0)
    except (TypeError, ValueError):
        min_cash_reserve = 0.0
    min_cash_reserve = max(0.0, min_cash_reserve)

    async with ibTools.ib_sem:
        account_values = await ibTools.ib.accountSummaryAsync()
        cash_values: list[Dict[str, Any]] = []

        for av in account_values:
            if av.tag != "CashBalance":
                continue

            currency = str(av.currency).upper()
            if currency in excluded_currencies:
                continue

            try:
                value = float(av.value)
            except (TypeError, ValueError):
                continue

            if currency == reserve_currency:
                value = max(0.0, value - min_cash_reserve)

            cash_values.append(
                {
                    "currency": currency,
                    "value": value,
                }
            )
    return {"cash_balances": cash_values}