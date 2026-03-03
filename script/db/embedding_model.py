from typing import Optional

from sentence_transformers import SentenceTransformer

from config import config
from logger import get_logger

logger = get_logger(__name__)

class EmbeddingModel:
    _instance: Optional[SentenceTransformer] = None

    @classmethod
    def get_instance(cls) -> SentenceTransformer:
        if cls._instance is None:
            embedding_model_name = config().embedding_model
            logger.info(f"Loading embedding model: {embedding_model_name}...") 

            cls._instance = SentenceTransformer(embedding_model_name)
            logger.info(f"Embedding model loaded (dim={cls._instance.get_sentence_embedding_dimension()}).")

        return cls._instance
    
    @classmethod
    def embed_passage(cls, text: str):
        return cls.get_instance().encode(
            f"passage: {text}",
            normalize_embeddings=True,
            show_progress_bar=False
        ).tolist()

    @classmethod
    def embed_query(cls, text: str):
        return cls.get_instance().encode(
            f"query: {text}",
            normalize_embeddings=True,
            show_progress_bar=False
        ).tolist()
    