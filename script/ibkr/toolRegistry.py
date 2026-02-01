from typing import Any, Awaitable, Callable, Dict
from pydantic import BaseModel
from ibkr.tools.marketDataTools import *
from ibkr.tools.getTools import TOOL_REGISTRY


def register_tool(name: str, *, description: str, args_model: type[BaseModel] = None):
    """Decorator to register a tool factory.

    The decorated factory must accept a single argument `ib: IBTools` and
    return the actual handler callable (an async function accepting a dict).
    """
    def _decorator(factory: Callable[[], Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]]):
        TOOL_REGISTRY[name] = {
            "description": description,
            "args_model": args_model,
            "factory": factory,
        }
        return factory

    return _decorator