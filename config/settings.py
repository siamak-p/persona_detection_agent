"""Pydantic settings for environment configuration with async support."""


from __future__ import annotations
import logging
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sqlite_dir = PROJECT_ROOT / "sqlite_data"
sqlite_dir.mkdir(exist_ok=True)
history_db_file = sqlite_dir / "mem0_history.db"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database connections
    QDRANT_URL: str = "http://localhost:6333"

    # Postgres - must be configured in .env file
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432  # Standard PostgreSQL port
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DSN: str | None = None  # If set, overrides individual fields above
    TENANT_ID: str = "default"

    # Application
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Scheduler
    SCHEDULER_ENABLED: bool = True
    
    # General LLM Settings
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    
    # ────────────────────────────────────────────────────────────────────────────
    #     COMPOSER - Chat mode response generation
    # ────────────────────────────────────────────────────────────────────────────
    #     Requires: deep comprehension, natural response, no fabrication
    #     Recommendation: smarter model (gpt-4o or gpt-4.1) for better quality
    # ────────────────────────────────────────────────────────────────────────────
    COMPOSER_MODEL: str = "gpt-4.1"
    COMPOSER_TEMPERATURE: float = 0.6  # Lower = more factual, higher = more creative
    COMPOSER_MAX_TOKENS: int = 300
    COMPOSER_TOP_P: float | None = None  # None = not used
    
    # ────────────────────────────────────────────────────────────────────────────
    #     CREATOR - User information gathering in Creator Mode
    # ────────────────────────────────────────────────────────────────────────────
    #     Requires: creative questions, natural conversation
    #     Recommendation: higher temperature for question variety
    # ────────────────────────────────────────────────────────────────────────────
    CREATOR_MODEL: str = "gpt-4.1"
    CREATOR_TEMPERATURE: float = 0.7
    CREATOR_MAX_TOKENS: int = 100
    CREATOR_TOP_P: float | None = None
    
    # ────────────────────────────────────────────────────────────────────────────
    #     GUARDRAIL - Irrelevant message filtering
    # ────────────────────────────────────────────────────────────────────────────
    #     Requires: precise and deterministic decisions
    #     Recommendation: low temperature for consistency
    # ────────────────────────────────────────────────────────────────────────────
    GUARDRAIL_MODEL: str = "gpt-4o-mini"  # Fast and cheap is sufficient
    GUARDRAIL_TEMPERATURE: float = 0.1
    GUARDRAIL_MAX_TOKENS: int = 200
    GUARDRAIL_TOP_P: float | None = None
    
    # ────────────────────────────────────────────────────────────────────────────
    #     SUMMARIZER - Conversation summarization
    # ────────────────────────────────────────────────────────────────────────────
    #     Requires: precise information extraction, summarization
    #     Recommendation: low temperature for accuracy
    # ────────────────────────────────────────────────────────────────────────────
    SUMMARIZER_MODEL: str = "gpt-4.1"
    SUMMARIZER_TEMPERATURE: float = 0.2
    SUMMARIZER_MAX_TOKENS: int = 1200
    SUMMARIZER_TOP_P: float | None = None
    
    # ────────────────────────────────────────────────────────────────────────────
    #     CORE_FACT_EXTRACTOR - Fact extraction and prioritization from summaries
    # ────────────────────────────────────────────────────────────────────────────
    #     Requires: precise extraction, priority classification
    #     Recommendation: very low temperature for classification consistency
    # ────────────────────────────────────────────────────────────────────────────
    FACT_EXTRACTOR_MODEL: str = "gpt-4.1"
    FACT_EXTRACTOR_TEMPERATURE: float = 0.1
    FACT_EXTRACTOR_MAX_TOKENS: int = 2000
    FACT_EXTRACTOR_TOP_P: float | None = None
    
    # ────────────────────────────────────────────────────────────────────────────
    #     TONE DETECTION - Tone analysis and relationship type detection
    # ────────────────────────────────────────────────────────────────────────────
    #     Requires: precise sentiment and relationship analysis
    #     Recommendation: moderate temperature for nuanced analysis
    # ────────────────────────────────────────────────────────────────────────────
    TONE_MODEL: str = "gpt-4o-mini"
    TONE_TEMPERATURE: float = 0.3
    TONE_MAX_TOKENS: int = 1000
    TONE_TOP_P: float | None = None
    
    # ────────────────────────────────────────────────────────────────────────────
    #     MEM0 - Memory extraction and storage
    # ────────────────────────────────────────────────────────────────────────────
    #     Requires: precise fact extraction from text
    #     Recommendation: very low temperature for consistency
    # ────────────────────────────────────────────────────────────────────────────
    MEM0_LLM_MODEL: str = "openai/gpt-4o"  # mem0-specific format
    MEM0_LLM_TEMPERATURE: float = 0.1
    MEM0_LLM_MAX_TOKENS: int = 500
    MEM0_LLM_TOP_P: float = 0.7
    
    # Legacy (for backward compatibility)
    AGENTS_MODEL: str = "gpt-4.1"  # Deprecated: use specific *_MODEL instead
    AGENTS_TEMPERATURE: float = 0.2  # Deprecated

    # Memory
    MESSAGE_COUNT_THRESHOLD: int = 20

    # Mem0
    MEM0_COLLECTION_NAME: str = "mem0_memories"
    MEM0_EMBEDDING_MODEL: str = "BAAI/bge-m3"
    MEM0_EMBEDDING_DIMS: int = 1024
    MEM0_COLLECTION_PER_TENANT: bool = True

    # Summary
    SUMMARY_MAX_INPUT_CHARS: int = 12000
    SUMMARY_MAX_WORDS: int = 120

    # ╔════════════════════════════════════════════════════════════════════════════╗
    # ║                              SCHEDULERS                                    ║
    # ║  4 Schedulers in the system, all started in main.py:                       ║
    # ║                                                                            ║
    # ║  1. ToneScheduler      - Passive message tone analysis (every 1 hour)      ║
    # ║  2. ToneRetryWorker    - Failed tone analysis retries (every 5 min)        ║
    # ║  3. SummaryRetryWorker - Failed summarization retries (every 5 min)        ║
    # ║  4. FeedbackScheduler  - Relationship questions (every 8 hours)            ║
    # ╚════════════════════════════════════════════════════════════════════════════╝

    # Enable/disable all schedulers
    # SCHEDULER_ENABLED: bool = True  # (defined above)

    # ────────────────────────────────────────────────────────────────────────────
    #     ToneScheduler - Tone analysis from passive_observation messages
    # ────────────────────────────────────────────────────────────────────────────
    #     Input table: passive_observation
    #     Output table: passive_archive, relationship_cluster_personas
    #     On failure: moved to ToneRetryWorker
    # ────────────────────────────────────────────────────────────────────────────
    # Execution interval (seconds) - default: 3600 = 1 hour
    TONE_SCHEDULER_INTERVAL_SECONDS: int = 3600
    # Max conversations to process per run
    TONE_SCHEDULER_MAX_CONVERSATIONS: int = 1000
    # Conversations per batch (to prevent overload)
    TONE_SCHEDULER_BATCH_SIZE: int = 10

    # ────────────────────────────────────────────────────────────────────────────
    #     ToneRetryWorker - Retry failed tone analyses
    # ────────────────────────────────────────────────────────────────────────────
    #     Input table: tone_retry_queue
    #     Output table: passive_archive (success) or tone_failed (final failure)
    #     Retry schedule: 5 min → 1 hour → 4 hours
    # ────────────────────────────────────────────────────────────────────────────
    # Queue check interval (seconds) - default: 300 = 5 minutes
    TONE_RETRY_WORKER_INTERVAL_SECONDS: int = 300
    # Max retry attempts (after which moved to tone_failed)
    TONE_RETRY_MAX_ATTEMPTS: int = 3
    # Delay between attempts (seconds, comma-separated)
    # Attempt 1: after 300s (5 min)
    # Attempt 2: after 3600s (1 hour)
    # Attempt 3: after 14400s (4 hours)
    TONE_RETRY_DELAYS_SECONDS: str = "300,3600,14400"

    # ────────────────────────────────────────────────────────────────────────────
    #     SummaryRetryWorker (RetryWorker) - Retry failed summarizations
    # ────────────────────────────────────────────────────────────────────────────
    #     Input table: summarization_retry_queue
    #     Output table: mem0 memories (success) or summarization_failed (final failure)
    #     Note: messages are not deleted from chat_events until summarization succeeds
    #     Retry schedule: 5 min → 1 hour → 4 hours
    # ────────────────────────────────────────────────────────────────────────────
    # Queue check interval (seconds) - default: 300 = 5 minutes
    SUMMARY_RETRY_WORKER_INTERVAL_SECONDS: int = 300
    # Max retry attempts (after which moved to summarization_failed)
    SUMMARY_RETRY_MAX_ATTEMPTS: int = 3
    # Delay between attempts (seconds, comma-separated)
    # Attempt 1: after 300s (5 min)
    # Attempt 2: after 3600s (1 hour)
    # Attempt 3: after 14400s (4 hours)
    SUMMARY_RETRY_DELAYS_SECONDS: str = "300,3600,14400"

    # ────────────────────────────────────────────────────────────────────────────
    #     FeedbackScheduler - Send relationship questions to users
    # ────────────────────────────────────────────────────────────────────────────
    #     Input table: relationship_cluster_personas (strangers)
    #     Output table: relationship_questions
    #     Purpose: ask user about relationship type with strangers
    # ────────────────────────────────────────────────────────────────────────────
    # Execution interval (seconds) - default: 28800 = 8 hours = 3x per day
    FEEDBACK_SCHEDULER_INTERVAL_SECONDS: int = 28800
    # Max questions per time window
    FEEDBACK_MAX_QUESTIONS_PER_WINDOW: int = 3
    # Time window for question rate limiting (seconds)
    # Example: 86400 = 24h = 3 questions/day, 28800 = 8h = 3 questions/8h
    FEEDBACK_QUESTION_WINDOW_SECONDS: int = 86400
    # Seconds to wait before retrying unanswered question
    # Example: 172800 = 2 days, 86400 = 1 day
    FEEDBACK_RETRY_AFTER_SECONDS: int = 172800
    # Max retries per question
    FEEDBACK_MAX_RETRIES: int = 2
    # Min confidence threshold for asking questions
    # If relationship confidence is below this, ask the user
    FEEDBACK_MIN_CONFIDENCE_THRESHOLD: float = 0.6

    # ────────────────────────────────────────────────────────────────────────────
    #     PassiveSummarizationScheduler - Passive message summarization
    # ────────────────────────────────────────────────────────────────────────────
    #     Input table: passive_archive
    #     Output table: Qdrant (same collection with metadata)
    #     On failure: moved to passive_summarization_retry_queue
    #     After 3 failures: moved to passive_summarization_failed + raw messages deleted
    # ────────────────────────────────────────────────────────────────────────────
    # Execution interval (seconds) - default: 3600 = 1 hour
    PASSIVE_SUMMARIZATION_INTERVAL_SECONDS: int = 3600
    # Conversations to fetch per run (e.g. 50)
    PASSIVE_SUMMARIZATION_FETCH_LIMIT: int = 50
    # Conversations per concurrent batch (e.g. 10)
    PASSIVE_SUMMARIZATION_BATCH_SIZE: int = 10
    # Min messages to start summarization (or MIN_TOKENS - whichever first)
    PASSIVE_SUMMARIZATION_MIN_MESSAGES: int = 40
    # Min tokens to start summarization (or MIN_MESSAGES - whichever first)
    PASSIVE_SUMMARIZATION_MIN_TOKENS: int = 300
    # Max messages per summarization run
    PASSIVE_SUMMARIZATION_MAX_MESSAGES: int = 100
    # Max retry attempts (after which moved to failed)
    PASSIVE_SUMMARIZATION_MAX_ATTEMPTS: int = 3
    # Delay between attempts (seconds, comma-separated)
    # Attempt 1: after 300s (5 min)
    # Attempt 2: after 3600s (1 hour)
    # Attempt 3: after 14400s (4 hours)
    PASSIVE_SUMMARIZATION_RETRY_DELAYS: str = "300,3600,14400"
    # Retry queue check interval (seconds) - default: 300 = 5 min
    PASSIVE_SUMMARIZATION_RETRY_INTERVAL_SECONDS: int = 300

    # ╔════════════════════════════════════════════════════════════════════════════╗
    # ║                           TONE DETECTION (LLM)                             ║
    # ║  LLM-based tone analysis settings (used in ToneDetectionAgent)             ║
    # ╚════════════════════════════════════════════════════════════════════════════╝
    # Min confidence to accept classification
    TONE_MIN_CONFIDENCE_THRESHOLD: float = 0.6
    # If confidence is below this, classify as stranger
    TONE_FALLBACK_CONFIDENCE_THRESHOLD: float = 0.4
    # Min messages for reliable classification
    TONE_MIN_MESSAGES_FOR_RELIABLE_CLASS: int = 10
    # Max tokens for LLM context
    TONE_MAX_TOKENS_FOR_CONTEXT: int = 3000

    # ╔════════════════════════════════════════════════════════════════════════════╗
    # ║                              DYADIC OVERRIDES                              ║
    # ║  Pair-specific metric computation for two users                            ║
    # ╚════════════════════════════════════════════════════════════════════════════╝
    # Message count threshold for computing dyadic overrides
    # When archived messages between two users exceed this number,
    # pair-specific (dyadic) metrics are computed
    DYADIC_THRESHOLD: int = 500

    # ╔════════════════════════════════════════════════════════════════════════════╗
    # ║                              VOICE SETTINGS                                ║
    # ║  Voice processing settings (STT/TTS)                                       ║
    # ╚════════════════════════════════════════════════════════════════════════════╝
    # Enable/disable voice features
    VOICE_ENABLED: bool = True
    # Enable/disable TTS output - currently disabled as OpenRouter doesn't support it
    VOICE_TTS_ENABLED: bool = False
    # Max voice input duration (seconds) - default: 300 = 5 minutes
    VOICE_MAX_DURATION_SECONDS: int = 300
    # Voice file storage path
    VOICE_STORAGE_PATH: str = "./voice_data"
    # Default TTS voice (options: alloy, echo, fable, onyx, nova, shimmer)
    VOICE_TTS_VOICE: str = "alloy"
    # TTS model (tts-1 for speed, tts-1-hd for higher quality)
    VOICE_TTS_MODEL: str = "tts-1"
    # Speech speed (0.25 to 4.0)
    VOICE_TTS_SPEED: float = 1.0
    # STT model for speech-to-text (OpenRouter audio-capable models)
    VOICE_STT_MODEL: str = "gpt-4o-audio-preview"

    # 🔧 New-style Pydantic v2 config
    # No env_mapping needed - fields are automatically read from env vars with the same name
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def postgres_dsn(self) -> str:
        """psycopg2-style DSN string (space-separated), kept for backwards compatibility."""
        return (
            f"host={self.POSTGRES_HOST} "
            f"port={self.POSTGRES_PORT} "
            f"dbname={self.POSTGRES_DB} "
            f"user={self.POSTGRES_USER} "
            f"password={self.POSTGRES_PASSWORD}"
        )

    @property
    def postgres_url(self) -> str:
        """AsyncPG DSN.
        - If POSTGRES_DSN exists:
            * 'postgresql+asyncpg://' -> normalized to 'postgresql://'
            * 'postgresql://' stays the same
        - Else build from HOST/PORT/DB/USER/PASSWORD
        """
        dsn = (self.POSTGRES_DSN or "").strip()
        if dsn:
            if dsn.startswith("postgresql+asyncpg://"):
                return "postgresql://" + dsn.split("postgresql+asyncpg://", 1)[1]
            return dsn
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def mem0_config(self) -> dict:
        """Build a fresh mem0 config using resolved settings and custom prompts.

        Using a property prevents binding Field objects at class definition time.
        """
        # Import here to avoid import cycles at module import time
        try:
            from memory.attribute_schema import ATTRIBUTE_SCHEMA
            from memory.mem_custom_prompt import (
                build_update_memory_prompt_with_schema,
                build_fact_extraction_prompt_with_schema,
            )

            # Build prompts dynamically with schema
            CUSTOM_UPDATE_MEMORY_PROMPT = build_update_memory_prompt_with_schema(ATTRIBUTE_SCHEMA)
            CUSTOM_FACT_EXTRACTION_PROMPT = build_fact_extraction_prompt_with_schema(
                ATTRIBUTE_SCHEMA
            )
        except Exception as e:
            logger.warning("Failed to load custom memory prompts, using defaults: %s", e)
            CUSTOM_UPDATE_MEMORY_PROMPT = None
            CUSTOM_FACT_EXTRACTION_PROMPT = None
            ATTRIBUTE_SCHEMA = None
        
        # Check if model exists locally
        import os
        from pathlib import Path
        
        model_cache = Path(__file__).parent.parent / "embedding_model"
        model_exists = any([
            (model_cache / "models--BAAI--bge-m3").exists(),
            (model_cache / "sentence-transformers_BAAI_bge-m3").exists(),
            (model_cache / "BAAI_bge-m3").exists(),
        ])

        # Collection per-tenant isolation
        collection_name = self.MEM0_COLLECTION_NAME
        if self.MEM0_COLLECTION_PER_TENANT and self.TENANT_ID != "default":
            collection_name = f"{self.MEM0_COLLECTION_NAME}_{self.TENANT_ID}"

        cfg: dict = {
            "version": "v1.1",
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "url": self.QDRANT_URL,
                    "collection_name": collection_name,
                    "embedding_model_dims": self.MEM0_EMBEDDING_DIMS,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": self.MEM0_LLM_MODEL,
                    "temperature": self.MEM0_LLM_TEMPERATURE,
                    "max_tokens": self.MEM0_LLM_MAX_TOKENS,
                    "top_p": self.MEM0_LLM_TOP_P,
                    "openai_base_url": self.OPENAI_BASE_URL,
                    "api_key": self.OPENAI_API_KEY,
                },
            },
            "embedder": {
                "provider": "huggingface",
                "config": {
                    "model": self.MEM0_EMBEDDING_MODEL,
                    # Settings for full offline operation or download on demand
                    "model_kwargs": {
                        "local_files_only": model_exists,  # Only use local if model exists
                        "device": "cpu",  # Explicitly use CPU
                    },
                },
            },
            "history_db_path": str(history_db_file),
        }

        if CUSTOM_UPDATE_MEMORY_PROMPT:
            cfg["custom_update_memory_prompt"] = CUSTOM_UPDATE_MEMORY_PROMPT
        if CUSTOM_FACT_EXTRACTION_PROMPT:
            cfg["custom_fact_extraction_prompt"] = CUSTOM_FACT_EXTRACTION_PROMPT
        if ATTRIBUTE_SCHEMA:
            cfg["attribute_schema"] = ATTRIBUTE_SCHEMA

        return cfg
