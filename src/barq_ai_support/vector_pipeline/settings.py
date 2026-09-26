from pydantic_settings import BaseSettings, SettingsConfigDict


class VectorPipelineSettings(BaseSettings):
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection_name: str = "barq_kb_chunks_v2"

    embedding_api_key: str
    embedding_base_url: str = "https://management.sprints.ai/litellm"
    embedding_model: str = "gemini/gemini-embedding-001"
    embedding_dim: int = 3072

    chunk_size: int = 1000
    chunk_overlap: int = 100

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = VectorPipelineSettings()