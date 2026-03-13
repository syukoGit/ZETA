from typing import Any, Dict

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


@register_tool("get_positions", description="Return current IB positions.")
async def get_positions(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    async with ibTools.guarded():
        pos: list[Dict[str, Any]] = [
            {"symbol": p.contract.symbol, "position": p.position, "avgCost": p.avgCost}
            for p in ibTools.ib.positions()
        ]
    return {"positions": pos}
