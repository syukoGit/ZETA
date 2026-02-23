import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID
from xai_sdk import Client
from xai_sdk.chat import tool, system, user, assistant, tool_result
from xai_sdk.tools import web_search, x_search, get_tool_call_type
from xai_sdk.proto.v6.chat_pb2 import ToolCall
from logger import get_logger
from llm.llm_provider import LLM, LLMFactory
from llm.tools.base import get_tools

logger = get_logger(__name__)


class _ExtendedEncoder(json.JSONEncoder):
    """JSON encoder that handles UUID and datetime objects."""
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class GrokProvider(LLM):
    _client = None

    def __init__(self, config: dict):
        super().__init__(config)
        self.client = Client(api_key=os.getenv("LLM_API_KEY"))

    @property
    def name(self) -> str:
        return "grok"
    
    def new_chat(self, previous_response_id: str | None = None):
        logger.debug("Creating new chat (model=%s, previous_id=%s)", self.model, previous_response_id)
        self._chat = self.client.chat.create(
            model=self.model,
            tools=get_grok_tool(),
            store_messages=True,
            previous_response_id=previous_response_id,
        )
    
    def add_message(self, content: str, role: str):
        if role == "system":
            self._chat.append(system(content))
        elif role == "user":
            self._chat.append(user(content))
        elif role == "assistant":
            self._chat.append(assistant(content))
        elif role == "tool_result":
            self._chat.append(tool_result(content))
        else:
            raise ValueError(f"Unsupported message role: {role}")
    
    def get_response(self) -> tuple[str, list, str]:
        tool_calls: list = []
        last_response = None
        for response, chunk in self._chat.stream():
            last_response = response
            if chunk.tool_calls:
                tool_calls.extend(chunk.tool_calls)
        
        if last_response is None:
            logger.warning("LLM stream returned no response chunk.")
            return "", tool_calls, ""
        
        response_content = last_response.content if last_response.content else ""
        response_id = response.id

        logger.debug("LLM response (id=%s): %s tool_calls, content length=%d", response_id, len(tool_calls), len(response_content))
        return response_content, tool_calls, response_id

    def is_client_side_tool(self, tool_call: Any) -> bool:
        if not isinstance(tool_call, ToolCall):
            return False
        tool_call_type = get_tool_call_type(tool_call)
        return tool_call_type == "client_side_tool"
    
    async def execute_client_side_tool(self, tool_call: Any, message_id: UUID) -> str:
        try:
            if not isinstance(tool_call, ToolCall):
                raise ValueError("Invalid tool call type.")

            name, args = self.get_tool_calls_info(tool_call)          
            logger.debug("Dispatching tool: %s", name)

            tool = get_tools()[name]
            validated = tool.args_model(**args).model_dump()
            validated["message_id"] = str(message_id)
            result = await tool.handler(validated)

            result_json = json.dumps(result, cls=_ExtendedEncoder)
            return result_json
        except Exception as e:
            logger.error("Tool execution error: %s", e)
            return f"Error: {str(e)}"
    
    def get_tool_calls_info(self, tool_call: Any) -> tuple[str, dict]:
        if not isinstance(tool_call, ToolCall):
            raise ValueError("Invalid tool call type.")
        
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
        return name, args

def get_grok_tool():
    return [
        x_search(enable_image_understanding=True, enable_video_understanding=True),
        web_search(enable_image_understanding=True),
        *[
            tool(
                name=k,
                description=v.description,
                parameters=v.args_model.model_json_schema()
            )
            for k, v in get_tools().items()
        ]
    ]

LLMFactory.register_provider("grok", GrokProvider)