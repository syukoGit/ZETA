import json
import os
from typing import Any
from xai_sdk import Client
from xai_sdk.chat import tool, system, user, assistant, tool_result
from xai_sdk.tools import web_search, x_search, get_tool_call_type
from xai_sdk.proto.v6.chat_pb2 import ToolCall
from logger import get_logger
from llm.llm_provider import LLM, ChatMode, LLMFactory
from llm.tools.base import get_tools

logger = get_logger(__name__)

class GrokProvider(LLM):
    _client = None

    def __init__(self, config: dict):
        super().__init__(config)
        self.client = Client(api_key=os.getenv("LLM_API_KEY"))

        self._chat_run = self.client.chat.create(
            model=self.model,
            tools=get_grok_tool("run"),
            store_messages=True,
        )

        self._chat_review = self.client.chat.create(
            model=self.model,
            tools=get_grok_tool("review"),
            store_messages=True,
        )

    @property
    def name(self) -> str:
        return "grok"
    
    def add_message(self, chat_type, content, role):        
        if chat_type == "run":
            chat = self._chat_run
        elif chat_type == "review":
            chat = self._chat_review
        else:
            raise ValueError(f"Unsupported chat type for add_message: {chat_type}")

        if role == "system":
            chat.append(system(content))
        elif role == "user":
            chat.append(user(content))
        elif role == "assistant":
            chat.append(assistant(content))
        elif role == "tool_result":
            chat.append(tool_result(content))
        else:
            raise ValueError(f"Unsupported message role: {role}")
    
    def get_response(self, chat_type) -> tuple[Any, list]:
        if chat_type == "run":
            chat = self._chat_run
        elif chat_type == "review":
            chat = self._chat_review
        else:
            raise ValueError(f"Unsupported chat type for get_response: {chat_type}")
        
        response = chat.sample()
        
        tool_calls = response.tool_calls if hasattr(response, "tool_calls") else []

        logger.debug("LLM response: %s tool_calls, content length=%d", len(tool_calls), len(response.content))
        return response, tool_calls

    def is_client_side_tool(self, tool_call) -> bool:
        if not isinstance(tool_call, ToolCall):
            return False
        tool_call_type = get_tool_call_type(tool_call)
        return tool_call_type == "client_side_tool"
    
    async def execute_client_side_tool(self, tool_call, message_id) -> dict:
        try:
            if not isinstance(tool_call, ToolCall):
                raise ValueError("Invalid tool call type.")

            name, args = self.get_tool_calls_info(tool_call)          
            logger.debug("Dispatching tool: %s with args: %s", name, args)

            tool = get_tools()[name]
            validated = tool.args_model(**args).model_dump()
            validated["message_id"] = str(message_id)
            result = await tool.handler(validated)

            return result
        except Exception as e:
            logger.error("Tool execution error: %s", e)
            raise ValueError(f"Error: {str(e)}")
    
    def get_tool_calls_info(self, tool_call) -> tuple[str, dict]:
        if not isinstance(tool_call, ToolCall):
            raise ValueError("Invalid tool call type.")
        
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
        return name, args

def get_grok_tool(mode: ChatMode) -> list:
    return [
        x_search(enable_image_understanding=True, enable_video_understanding=True),
        web_search(enable_image_understanding=True),
        *[
            tool(
                name=k,
                description=v.description,
                parameters=v.args_model.model_json_schema()
            )
            for k, v in get_tools(mode).items()
        ]
    ]

LLMFactory.register_provider("grok", GrokProvider)