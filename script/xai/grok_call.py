import json
import os
from dotenv import load_dotenv
from xai_sdk import Client
from ibkr.ibTools import IBTools
from xai.start_prompt import DEFAULT_START_PROMPT
from xai.toolsModels import get_grok_tool, get_tools
from xai_sdk.chat import user, system, tool_result
from xai_sdk.tools import get_tool_call_type
from xai_sdk.proto.v6.chat_pb2 import ToolCall

load_dotenv()

async def run_call_grok(summary: str | None) -> str:
    client = Client(api_key=os.getenv('XAI_API_KEY'))

    chat = client.chat.create(
        model="grok-4-1-fast-reasoning",
        tools=get_grok_tool(),
        tool_choice="auto",
        store_messages=True,
    )

    # Initialize the conversation with the start prompt
    chat.append(system(DEFAULT_START_PROMPT))

    chat.append(user("SUMMARY_PREV: " + summary if summary else "No summary provided."))
    
    # Provides the current trading context to Grok
    ib_tools = IBTools.get_instance()
    positions = await ib_tools.get_positions({})
    cash_balance = await ib_tools.get_cash_balance({})
    orders = await ib_tools.get_orders({})

    snapshot_ib = {
        "positions": positions["positions"],
        "cash_balances": cash_balance["cash_balances"],
        "orders": orders["orders"],
    }

    chat.append(user("SNAPSHOT_IB: " + json.dumps(snapshot_ib)))

    try:
        max_loops = 0
        while max_loops < 10:
            client_side_calls: list[ToolCall] = []

            for response, chunk in chat.stream():
                for tc in chunk.tool_calls:
                    if get_tool_call_type(tc) == "client_side_tool":
                        client_side_calls.append(tc)
                    else:
                        print(f"\nServer side tool call: {tc.function.name} (arguments: {tc.function.arguments})")

            if not client_side_calls:
                break

            chat = client.chat.create(
                model="grok-4-1-fast-reasoning",
                tools=get_grok_tool(),
                store_messages=True,
                previous_response_id=response.id,
            )

            for tc in client_side_calls:
                print(f"\nClient side tool call: {tc.function.name} (arguments: {tc.function.arguments})")
                result = await run_client_side_tool(tc)

                chat.append(tool_result(result))
            
            max_loops += 1
    except Exception as e:
        print(f"Error during Grok interaction: {e}")
    
    final_output = response.content if response.content else str(response.proto.outputs)
    
    return final_output

async def run_client_side_tool(tool_call: ToolCall) -> str:
    try:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

        tool = get_tools()[name]
        validated = tool.args_model(**args).model_dump()
        result = await tool.handler(validated)

        result_json = json.dumps(result)
        return result_json
    except Exception as e:
        error_msg = f"Error: {e}"
        print(f"Error during tool call '{tool_call.function.name}': {e}")
        return error_msg
