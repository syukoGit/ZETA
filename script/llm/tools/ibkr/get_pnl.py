from typing import Any, Dict

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


@register_tool(
    "get_pnl", description="Get the profit and loss (PnL) for the positions."
)
async def get_pnl(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    async with ibTools.guarded():
        portfolio = ibTools.ib.portfolio()
        pnl_values: list[Dict[str, Any]] = [
            {
                "currency": av.contract.currency,
                "symbol": av.contract.symbol,
                "position": av.position,
                "averageCost": float(av.averageCost),
                "marketValue": float(av.marketValue),
                "marketPrice": float(av.marketPrice),
                "unrealizedPnL": float(av.unrealizedPNL),
                "realizedPnL": float(av.realizedPNL),
            }
            for av in portfolio
        ]
    return {"pnl": pnl_values}
