import importlib
import os
import pkgutil
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict
from pydantic import BaseModel
from ibkr.toolArgs import NoArgs

@dataclass
class ToolSpec:
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

def _auto_import_tools():
    import_path = __name__.rsplit('.', 1)[0]  # ibkr.tools
    tools_dir = os.path.dirname(__file__)
    for _, module_name, is_pkg in pkgutil.iter_modules([tools_dir]):
        if not is_pkg and module_name != os.path.splitext(os.path.basename(__file__))[0]:
            importlib.import_module(f"{import_path}.{module_name}")

_auto_import_tools()

def get_tools() -> Dict[str, ToolSpec]:
    """Build the tools mapping from the registry, binding handlers to the
    current `IBTools` instance.
    """

    tools: Dict[str, ToolSpec] = {}
    for name, meta in TOOL_REGISTRY.items():
        # On stocke la factory elle-même dans handler, sans l'appeler
        tools[name] = ToolSpec(
            description=meta["description"],
            args_model = meta.get("args_model") or NoArgs,
            handler=meta["factory"]
        )
    return tools