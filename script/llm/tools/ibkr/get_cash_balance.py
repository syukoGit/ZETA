from typing import Any, Dict

from config import config
from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


@register_tool("get_cash_balance", description="Retrieve cash balance information from Interactive Brokers.")
async def get_cash_balance(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    ibkr = config().ibkr
    reserve_currency = ibkr.cash_reserve_currency.strip().upper() or "BASE"
    excluded_currencies = {c.strip().upper() for c in ibkr.excluded_cash_currencies if c.strip()}
    min_cash_reserve = max(0.0, ibkr.min_cash_reserve)

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