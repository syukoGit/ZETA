from abc import ABC, abstractmethod
import importlib
from typing import Any, Literal
from uuid import UUID
from logger import get_logger

logger = get_logger(__name__)

type ChatMode = Literal["run", "review"]

class LLM(ABC):
    _chat_run = None
    _chat_review = None

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.model = config.get("model")
    
    @property
    def name(self) -> str:
        raise NotImplementedError

    def close_chats(self):
        if self._chat_run:
            self._chat_run = None
        if self._chat_review:
            self._chat_review = None

    @abstractmethod
    def add_message(self, chat_type: ChatMode, content: str, role: str):
        pass

    @abstractmethod
    def get_response(self, chat_type: ChatMode) -> tuple[Any, list]:
        pass

    @abstractmethod
    def is_client_side_tool(self, tool_call: Any) -> bool:
        pass

    @abstractmethod
    async def execute_client_side_tool(self, tool_call: Any, message_id: UUID) -> dict:
        pass

    @abstractmethod
    def get_tool_calls_info(self, tool_call: Any) -> tuple[str, dict]:
        pass


class LLMFactory:
    _providers: dict[str, type[LLM]] = {}

    @classmethod
    def register_provider(cls, name: str, provider: type[LLM]) -> None:
        cls._providers[name] = provider
    
    @classmethod
    def get_provider(cls, llm_config: Any | None) -> LLM:
        if llm_config is None:
            raise ValueError("Missing LLM configuration.")
        
        provider_name = llm_config.get("provider")
        if not provider_name:
            raise ValueError("Missing LLM provider in configuration.")
        
        if provider_name not in cls._providers:
            cls._load_provider_module(provider_name)
        
        provider_class = cls._providers.get(provider_name)
        if not provider_class:
            raise ValueError(f"LLM provider '{provider_name}' is not registered.")
        
        return provider_class(llm_config)
    
    @classmethod
    def _load_provider_module(cls, provider_name: str):
        try:
            importlib.import_module(
                f"llm.providers.{provider_name}_provider"
            )
        except ImportError as e:
            logger.error(f"Failed to load LLM provider module for '{provider_name}': {e}")
            pass