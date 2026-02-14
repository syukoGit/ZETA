from typing import Any, Dict

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


@register_tool("get_cash_balance", description="Retrieve cash balance information from Interactive Brokers.")
async def get_cash_balance(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        account_values = await ibTools.ib.accountSummaryAsync()
        cash_values: list[Dict[str, Any]] = [
            {
                "currency": av.currency,
                "value": float(av.value),
            }
            for av in account_values
            if av.tag == "CashBalance"
        ]
    return {"cash_balances": cash_values}