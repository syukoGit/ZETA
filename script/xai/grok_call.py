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

from db.repository import init_db, get_session, ConversationRepository

load_dotenv()

init_db()

async def run_call_grok(summary: str | None) -> str:
    client = Client(api_key=os.getenv('XAI_API_KEY'))

    with get_session() as session:
        repo = ConversationRepository(session)
        conversation = repo.create_conversation(
            provider="xai",
            model="grok-4-1-fast-reasoning",
        )
        conversation_id = conversation.conversation_id

        chat = client.chat.create(
            model="grok-4-1-fast-reasoning",
            tools=get_grok_tool(),
            tool_choice="auto",
            store_messages=True,
        )

        # Initialize the conversation with the start prompt
        chat.append(system(DEFAULT_START_PROMPT))
        repo.add_system_message(conversation_id, DEFAULT_START_PROMPT)

        summary_message = "SUMMARY_PREV: " + json.dumps(summary) if summary else "No summary provided."
        chat.append(user(summary_message))
        repo.add_user_message(conversation_id, summary_message)
        
        # Provides the current trading context to Grok
        ib_tools = IBTools.get_instance()
        positions = await ib_tools.get_positions({})
        cash_balance = await ib_tools.get_cash_balance({})
        open_trades = await ib_tools.get_open_trades({})

        snapshot_ib = {
            "positions": positions["positions"],
            "cash_balances": cash_balance["cash_balances"],
            "open_trades": open_trades["open_trades"],
        }

        snapshot_message = "SNAPSHOT_IB: " + json.dumps(snapshot_ib)
        chat.append(user(snapshot_message))
        repo.add_user_message(conversation_id, snapshot_message)

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

                # Sauvegarde la réponse de l'assistant
                if response.content:
                    repo.add_assistant_message(
                        conversation_id,
                        response.content,
                        payload={"response_id": response.id},
                    )

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
                    
                    # Sauvegarde l'appel de tool
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    tool_item = repo.add_tool_call(
                        conversation_id,
                        tc.function.name,
                        args,
                        tool_call_id=tc.id if hasattr(tc, 'id') else None,
                    )
                    
                    result = await run_client_side_tool(tc)
                    
                    # Sauvegarde le résultat du tool
                    is_error = result.startswith("Error:")
                    repo.add_tool_result(
                        conversation_id,
                        tc.function.name,
                        result,
                        parent_item_id=tool_item.item_id,
                        error=result if is_error else None,
                    )

                    chat.append(tool_result(result))
                
                max_loops += 1
        except Exception as e:
            print(f"Error during Grok interaction: {e}")
            # Sauvegarde l'erreur dans la conversation
            repo.add_item(
                conversation_id,
                kind="error",
                content=str(e),
                status="failed",
                error=str(e),
            )
        
        final_output = response.content if response.content else str(response.proto.outputs)
        
        # Termine la conversation
        repo.end_conversation(conversation_id)
        
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
