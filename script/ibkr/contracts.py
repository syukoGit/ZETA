from __future__ import annotations

from typing import Any, Dict, List, Literal, Tuple

from ib_async import IB, Contract
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import config as get_config
from logger import get_logger


logger = get_logger(__name__)

AUTO_DETECT_ORDER: List[str] = ["STK", "IND"]

# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


class _BaseContractArgs(BaseModel):
    """Common fields for all supported contract types (read-only market data)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., min_length=1, description="Ticker symbol")
    exchange: str = Field(
        "SMART",
        min_length=1,
        description="Exchange code",
    )
    currency: str = Field(
        "USD", min_length=1, description="Currency code (e.g. USD, EUR, JPY)"
    )

    def _base_kwargs(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "currency": self.currency,
        }

    def to_ib_contract(self) -> Contract:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Supported contract types
# ---------------------------------------------------------------------------


class StockContractArgs(_BaseContractArgs):
    """Stock or ETF (STK). exchange='SMART' lets IBKR choose the best venue."""

    sec_type: Literal["STK"] = "STK"

    def to_ib_contract(self) -> Contract:
        return Contract(secType="STK", **self._base_kwargs())


class IndexContractArgs(_BaseContractArgs):
    """Market index (IND) — e.g. SPX, VIX, NDX.
    SMART routing is NOT supported; the actual listing exchange must be provided."""

    sec_type: Literal["IND"] = "IND"
    exchange: str = Field(
        ...,
        min_length=1,
        description="Listing exchange for the index. 'SMART' is NOT valid.",
    )

    @model_validator(mode="before")
    @classmethod
    def resolve_smart_exchange(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        exchange = str(values.get("exchange", "")).strip().upper()
        if exchange == "SMART":
            symbol = str(values.get("symbol", "")).upper()

            exchange_hint = _get_indices_registry().get(symbol)
            if exchange_hint:
                values["exchange"] = exchange_hint
            else:
                raise ValueError(
                    "exchange='SMART' is not valid for IND contracts. "
                    "Provide the actual listing exchange (e.g. CBOE, NYSE, EUREX)."
                )
        else:
            values["exchange"] = exchange
        return values

    def to_ib_contract(self) -> Contract:
        return Contract(secType="IND", **self._base_kwargs())


# Registry mapping sec_type to the corresponding contract args class, used for parsing and auto-detection.
_REGISTRY: Dict[str, type[_BaseContractArgs]] = {
    "STK": StockContractArgs,
    "IND": IndexContractArgs,
}


# Public helpers
def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of d with all None-valued keys removed."""
    return {k: v for k, v in d.items() if v is not None}


def _get_indices_registry() -> Dict[str, str]:
    return {k.upper(): v.upper() for k, v in get_config().ind_registry.items()}


async def qualify_contract(ib: IB, data: Dict[str, Any]) -> Tuple[Contract, str]:
    data = {k: v for k, v in data.items() if k != "sec_type"}

    ib_failures: List[str] = []
    for guessed_type in AUTO_DETECT_ORDER:
        cls = _REGISTRY[guessed_type]
        try:
            contract_args = cls(**_strip_none({**data, "sec_type": guessed_type}))
        except Exception as e:
            logger.warning(
                "qualify_contract: auto-detect failed for sec_type=%s symbol=%s error=%s",
                guessed_type,
                data.get("symbol"),
                str(e),
            )
            continue

        logger.debug(
            "qualify_contract: auto-detect trying sec_type=%s symbol=%s",
            guessed_type,
            data.get("symbol"),
        )
        candidate = contract_args.to_ib_contract()
        qualified = await ib.qualifyContractsAsync(candidate)
        if qualified and qualified[0] is not None:
            q = qualified[0]
            return q, q.secType

        ib_failures.append(guessed_type)

    logger.error(
        "qualify_contract: auto-detection failed symbol=%s tried=%s ib_failures=%s",
        data.get("symbol"),
        AUTO_DETECT_ORDER,
        ib_failures,
    )

    raise ValueError(
        f"Could not qualify contract with auto-detection for symbol={data.get('symbol')}. "
        f"Tried: {AUTO_DETECT_ORDER}. IB rejected: {ib_failures}."
    )
