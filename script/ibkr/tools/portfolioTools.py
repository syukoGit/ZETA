from typing import Any, Dict
from ibkr.ibTools import IBTools
from ibkr.toolRegistry import register_tool

@register_tool("get_positions", description="Return current IB positions.")
async def get_positions(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        pos: list[Dict[str, Any]] = [
            {"symbol": p.contract.symbol, "position": p.position, "avgCost": p.avgCost}
            for p in ibTools.ib.positions()
        ]
    return {"positions": pos}

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

@register_tool("get_pnl", description="Get the profit and loss (PnL) for the positions.")
async def get_pnl(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
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