from abc import ABC, abstractmethod
import importlib
from typing import Any, Literal
from uuid import UUID
from logger import get_logger


class LLM(ABC):
    _chat = None

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.model = config.get("model")
    
    @property
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def new_chat(self, mode: Literal["run", "review"], previous_response_id: str | None = None):
        pass

    def close_chat(self):
        if self._chat:
            self._chat = None

    @abstractmethod
    def add_message(self, content: str, role: str):
        pass

    @abstractmethod
    def get_response(self) -> tuple[str, list, str]:
        pass

    @abstractmethod
    def is_client_side_tool(self, tool_call: Any) -> bool:
        pass

    @abstractmethod
    async def execute_client_side_tool(self, tool_call: Any, message_id: UUID) -> str:
        pass

    @abstractmethod
    def get_tool_calls_info(self, tool_call: Any) -> tuple[str, dict]:
        pass

logger = get_logger(__name__)

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