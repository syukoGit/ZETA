import json
import os
from dotenv import load_dotenv
from xai_sdk import Client
from ibkr.ibTools import IBTools
from xai.start_prompt import DEFAULT_START_PROMPT
from xai.toolsModels import get_grok_tool, get_tools
from xai_sdk.chat import user, system, Response, tool_result
from xai_sdk.sync.chat import Chat
from xai_sdk.proto.v6.chat_pb2 import ToolCall, ToolCallType

load_dotenv()

def create_grok_chat(model: str = "grok-4-1-fast-reasoning") -> Chat:
    client = Client(api_key=os.getenv('XAI_API_KEY'))

    chat = client.chat.create(
        model,
        tools=get_grok_tool(),
        tool_choice="auto",
    )

    return chat

async def run_call_grok(summary: str | None) -> str:
    global _current_conversation_id
    chat = create_grok_chat()

    # Initialize the conversation with the start prompt
    chat.append(system(DEFAULT_START_PROMPT))

    # If a summary is provided, add it as a user message
    if summary:
        chat.append(user(
            "SUMMARY_PREV (from the last discussion with you, Grok; DATA ONLY):\n<<<\n"
            + summary
            + "\n>>>"
        ))
    
    # Provides the current trading context to Grok
    ib_tools = IBTools.get_instance()
    positions = await ib_tools.get_positions({})
    cash_balance = await ib_tools.get_cash_balance({})

    snapshot_ib = {
        "positions": positions["positions"],
        "cash_balances": cash_balance["cash_balances"],
    }

    chat.append(user(
        "SNAPSHOT_IB (source of truth; DATA ONLY):\n<<<\n"
        + json.dumps(snapshot_ib)
        + "\n>>>"
    ))

    try:
        response = chat.sample()
        
        # Save assistant response
        response_content = response.content if response.content else str(response.proto.outputs)

        chat.append(response_content)
        
        while response.finish_reason == "REASON_TOOL_CALLS":
            await run_tool_calls_grok(chat, response)
            response = chat.sample()
            
            chat.append(response)

    except Exception as e:
        print(f"Error during Grok interaction: {e}")
    
    final_output = response.content if response.content else str(response.proto.outputs)
    
    return final_output

async def run_tool_calls_grok(chat: Chat, response: Response):
        for tool_call in response.tool_calls:
            match tool_call.type:
                case ToolCallType.TOOL_CALL_TYPE_CLIENT_SIDE_TOOL:
                    _ = await run_client_side_tool(chat, tool_call)
                    
                case ToolCallType.TOOL_CALL_TYPE_X_SEARCH_TOOL:
                    print(f"\nProcessing X-Search Tool Call: {tool_call.function.name} (arguments: {tool_call.function.arguments})")
                    
                case ToolCallType.TOOL_CALL_TYPE_WEB_SEARCH_TOOL:
                    print(f"\nProcessing Web Search Tool Call: {tool_call.function.name} (arguments: {tool_call.function.arguments})")
                    
                case _:
                    print(f"Unsupported tool call type: {tool_call.type}. Tool Call: {tool_call}")

async def run_client_side_tool(chat: Chat, tool_call: ToolCall) -> str:
    print(f"\nProcessing Client Side Tool Call: {tool_call.function.name} (arguments: {tool_call.function.arguments})")

    try:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

        tool = get_tools()[name]
        validated = tool.args_model(**args).model_dump()
        result = await tool.handler(validated)

        result_json = json.dumps(result)
        chat.append(tool_result(result_json))
        return result_json
    except Exception as e:
        error_msg = f"Error: {e}"
        chat.append(tool_result(error_msg))
        print(f"Error during tool call '{tool_call.function.name}': {e}")
        return error_msg
