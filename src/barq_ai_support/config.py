from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    servicenow_instance_url: str
    servicenow_username: str
    servicenow_password: str
    servicenow_knowledge_base_sys_id: str

    # Shared secret checked against the
    # "X-ServiceNow-Secret" header.
    servicenow_webhook_secret: str = ""

    # --- Gemini / Embedding settings (S2.2) ---
    gemini_api_key: str = ""

    # --- Qdrant / vector storage settings (S2.2) ---
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection_name: str = "barq_kb_chunks"

    # --- Retrieval settings (S2.3) ---
    retrieval_score_threshold: float = 0.75
    retrieval_top_k: int = 5
    
        # --- Celery / Redis settings (S3.6) ---
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- Tracing settings (S3.6) ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()