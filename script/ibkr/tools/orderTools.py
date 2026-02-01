from datetime import datetime, timezone
from typing import Any, Dict
import uuid
from ib_async import LimitOrder, MarketOrder, Stock, StopOrder
from ibkr.toolArgs import CancelOrderArgs, ModifyOrderArgs, PlaceBracketOrderArgs, PlaceOcoOrderArgs, PlaceOrderArgs
from ibkr.toolRegistry import register_tool
from ibkr.ibTools import IBTools

@register_tool("place_order", description="Place a stock order via Interactive Brokers TWS API.", args_model=PlaceOrderArgs)
async def place_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PlaceOrderArgs(**args)

    ibTools = IBTools.get_instance()
    
    contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)

    async with ibTools.ib_sem:
        if a.order_type == "MKT":
            order = MarketOrder(a.side, a.qty)
        else:
            order = LimitOrder(a.side, a.qty, a.limit_price)
        
        if ibTools.dry_run:
            return {"status": "DRY_RUN", "symbol": a.symbol, "side": a.side, "qty": a.qty, "type": a.order_type}
        
        trade = ibTools.ib.placeOrder(contract, order)
        
        return {"status": "SUBMITTED", "orderId": trade.order.orderId}

@register_tool("preview_order", description="Preview a stock order via Interactive Brokers TWS API.", args_model=PlaceOrderArgs)
async def preview_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PlaceOrderArgs(**args)
    
    contract = Stock(a.symbol, "SMART", "USD", primaryExchange="NASDAQ")

    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        if a.order_type == "MKT":
            order = MarketOrder(a.side, a.qty)
        else:
            if a.limit_price is None:
                raise ValueError("limit_price required for LMT")
            order = LimitOrder(a.side, a.qty, a.limit_price)
        
        order.tif = "DAY"
        
        estimate = await ibTools.ib.whatIfOrderAsync(contract, order)

        print(estimate)

        return {
            "symbol": a.symbol,
            "side": a.side,
            "qty": a.qty,
            "type": a.order_type,
            "status": getattr(estimate, "status", None),
            "commission": getattr(estimate, "commission", None),
            "minCommission": getattr(estimate, "minCommission", None),
            "maxCommission": getattr(estimate, "maxCommission", None),
            "initMarginChange": getattr(estimate, "initMarginChange", None),
            "maintMarginChange": getattr(estimate, "maintMarginChange", None),
            "equityWithLoanChange": getattr(estimate, "equityWithLoanChange", None),
            "warningText": getattr(estimate, "warningText", None),
            "commissionCurrency": getattr(estimate, "commissionCurrency", None),
            "completedStatus": getattr(estimate, "completedStatus", None),
        }

@register_tool("cancel_order", description="Cancel an existing order via Interactive Brokers TWS API.", args_model=CancelOrderArgs)
async def cancel_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = CancelOrderArgs(**args)

    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        trade = next((t for t in ibTools.ib.trades() if t.order.orderId == a.order_id), None)

        if trade is None:
            return {
                "status": "NOT_FOUND",
                "orderId": a.order_id,
                "asOf": datetime.now(timezone.utc).isoformat(),
            }
        
        if trade.orderStatus.status in ("Filled", "Cancelled"):
            return {
                "status": "NO_ACTION",
                "orderId": a.order_id,
                "orderStatus": trade.orderStatus.status,
                "asOf": datetime.now(timezone.utc).isoformat(),
            }
        
        ibTools.ib.cancelOrder(trade.order)

        return {
            "status": "CANCEL_REQUESTED",
            "orderId": a.order_id,
            "currentStatus": trade.orderStatus.status,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }

@register_tool("modify_order", description="Modify an existing order via Interactive Brokers TWS API.", args_model=ModifyOrderArgs)
async def modify_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = ModifyOrderArgs(**args)

    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        trade = next((t for t in ibTools.ib.trades() if t.order.orderId == a.order_id), None)

        if trade is None:
            return {
                "status": "NOT_FOUND",
                "orderId": a.order_id,
                "asOf": datetime.now(timezone.utc).isoformat(),
            }
        
        if trade.orderStatus.status in ("Filled", "Cancelled"):
            return {
                "status": "NO_ACTION",
                "orderId": a.order_id,
                "orderStatus": trade.orderStatus.status,
                "asOf": datetime.now(timezone.utc).isoformat(),
            }
        
        if a.new_limit_price is not None:
            trade.order.lmtPrice = a.new_limit_price
        if a.new_qty is not None:
            trade.order.totalQuantity = a.new_qty
        if a.time_in_force is not None:
            trade.order.tif = a.time_in_force
        
        ibTools.ib.placeOrder(trade.contract, trade.order)

        return {
            "status": "MODIFY_REQUESTED",
            "orderId": a.order_id,
            "currentStatus": trade.orderStatus.status,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }

@register_tool("place_bracket_order", description="Place a bracket order via Interactive Brokers TWS API.", args_model=PlaceBracketOrderArgs)
async def place_bracket_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PlaceBracketOrderArgs(**args)

    ibTools = IBTools.get_instance()

    contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)

    async with ibTools.ib_sem:
        await ibTools.ib.qualifyContractsAsync(contract)

        oca_group = f"OCA-{uuid.uuid4().hex[:10]}"

        # Parent order
        if a.entry_type == "MKT":
            parent = MarketOrder(a.side, a.qty)
        else:
            parent = LimitOrder(a.side, a.qty, a.entry_limit_price)
        
        parent.tif = a.tif
        parent.transmit = False

        # Take Profit order
        tp = LimitOrder(
            "SELL" if a.side == "BUY" else "BUY",
            a.qty,
            a.take_profit_price,
        )

        tp.parentId = parent.orderId
        tp.ocaGroup = oca_group
        tp.ocaType = 1
        tp.transmit = False

        # Stop Loss order
        sl = StopOrder(
            "SELL" if a.side == "BUY" else "BUY",
            a.qty,
            a.stop_loss_price,
        )
        sl.parentId = parent.orderId
        sl.ocaGroup = oca_group
        sl.ocaType = 1
        sl.transmit = True

        if ibTools.dry_run:
            return {
                "status": "DRY_RUN",
                "symbol": a.symbol,
                "qty": a.qty,
                "entry": a.entry_type,
                "tp": a.take_profit_price,
                "sl": a.stop_loss_price,
            }
        
        parent_trade = ibTools.ib.placeOrder(contract, parent)
        ibTools.ib.placeOrder(contract, tp)
        ibTools.ib.placeOrder(contract, sl)

        return {
            "status": "SUBMITTED",
            "symbol": a.symbol,
            "side": a.side,
            "qty": a.qty,
            "ocaGroup": oca_group,
            "parentOrderId": parent_trade.order.orderId,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }

@register_tool("place_oco_order", description="Place an OCO (One-Cancels-the-Other) order via Interactive Brokers TWS API.", args_model=PlaceOcoOrderArgs)
async def place_oco_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PlaceOcoOrderArgs(**args)

    ibTools = IBTools.get_instance()

    contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)

    async with ibTools.ib_sem:
        await ibTools.ib.qualifyContractsAsync(contract)

        oca_group = f"OCA-{uuid.uuid4().hex[:10]}"

        # Take Profit order
        tp = LimitOrder(
            a.side,
            a.qty,
            a.take_profit_price,
        )
        tp.tif = a.tif
        tp.ocaGroup = oca_group
        tp.ocaType = 1
        tp.transmit = False

        # Stop Loss order
        sl = StopOrder(
            a.side,
            a.qty,
            a.stop_loss_price,
        )
        sl.tif = a.tif
        sl.ocaGroup = oca_group
        sl.ocaType = 1
        sl.transmit = True

        tp_trade = ibTools.ib.placeOrder(contract, tp)
        sl_trade = ibTools.ib.placeOrder(contract, sl)

        return {
            "status": "SUBMITTED",
            "symbol": a.symbol,
            "side": a.side,
            "qty": a.qty,
            "ocaGroup": oca_group,
            "takeProfitOrderId": tp_trade.order.orderId,
            "stopLossOrderId": sl_trade.order.orderId,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }

