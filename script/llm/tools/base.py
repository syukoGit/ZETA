from dataclasses import dataclass
import importlib
import os
import pkgutil
from typing import Any, Awaitable, Callable, Dict, Literal

from pydantic import BaseModel


class NoArgs(BaseModel):
    pass


@dataclass
class ToolSpec:
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    run: bool = True
    review: bool = True


# Tool registry
TOOL_REGISTRY: Dict[str, ToolSpec] = {}


def register_tool(
    name: str,
    *,
    description: str,
    args_model: type[BaseModel] = None,
    run: bool = True,
    review: bool = True,
):
    """Decorator to register a tool factory.

    The decorated factory must accept a single argument `ib: IBTools` and
    return the actual handler callable (an async function accepting a dict).
    """

    def _decorator(
        factory: Callable[[], Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]],
        run: bool = True,
        review: bool = True,
    ):
        TOOL_REGISTRY[name] = ToolSpec(
            description=description,
            args_model=args_model or NoArgs,
            handler=factory,
            run=run,
            review=review,
        )
        return factory

    return _decorator


def _auto_import_tools():
    import_path = __name__.rsplit(".", 1)[0]  # llm.tools
    tools_dir = os.path.dirname(__file__)
    base_module = os.path.splitext(os.path.basename(__file__))[0]
    for _, module_name, _ in pkgutil.walk_packages(
        [tools_dir], prefix=f"{import_path}."
    ):
        if module_name.endswith(f".{base_module}"):
            continue
        importlib.import_module(module_name)


_auto_import_tools()


def get_tools(
    mode: Literal["all", "run", "review"] = "all", disabled: list[str] | None = None
) -> Dict[str, ToolSpec]:
    disabled_set = set(disabled) if disabled else set()

    if mode == "all":
        filtered = TOOL_REGISTRY
    elif mode == "run":
        filtered = {name: spec for name, spec in TOOL_REGISTRY.items() if spec.run}
    elif mode == "review":
        filtered = {name: spec for name, spec in TOOL_REGISTRY.items() if spec.review}
    else:
        raise ValueError(
            f"Invalid mode '{mode}' for get_tools. Must be 'all', 'run', or 'review'."
        )

    if disabled_set:
        filtered = {
            name: spec for name, spec in filtered.items() if name not in disabled_set
        }

    return filtered
