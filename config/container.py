"""DI Container - production wiring with mem0ai + Postgres chat store (SoR)."""

import logging
from dependency_injector import containers, providers

from config.settings import Settings

logger = logging.getLogger(__name__)


class Container(containers.DeclarativeContainer):
    """Application DI container with mem0, Qdrant, and Postgres wiring."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "api.routers.chat",
            "api.routers.creator",
            "api.routers.passive",
            "api.routers.passive_last_message_id",
            "api.routers.feedback",
            "api.routers.scheduler",
        ]
    )

    # Settings
    settings = providers.Singleton(Settings)

    # Database clients
    qdrant_client = providers.Singleton(
        lambda s: __import__("db.qdrant", fromlist=["create_client"]).create_client(
            url=s.QDRANT_URL
        ),
        s=settings,
    )

    # Postgres chat store (System of Record)
    postgres_chat_store = providers.Singleton(
        lambda s: __import__(
            "db.postgres_chat_store", fromlist=["PostgresChatStore"]
        ).PostgresChatStore(
            dsn=s.postgres_url,
            tenant_id=s.TENANT_ID,
        ),
        s=settings,
    )

    # Postgres relationship cluster personas
    postgres_relationship_cluster_personas = providers.Singleton(
        lambda s: __import__(
            "db.postgres_relationship_cluster_personas", fromlist=["RelationshipClusterPersonas"]
        ).RelationshipClusterPersonas(
            dsn=s.postgres_url,
        ),
        s=settings,
    )

    # postgres dyadic overrides
    postgres_dyadic_overrides = providers.Singleton(
        lambda s:__import__(
            "db.postgres_dyadic_overrides", fromlist=["DyadicOverrides"]
        ).DyadicOverrides(
            dsn=s.postgres_url,
        ),
        s=settings,
    )
    # Passive storage
    passive_storage = providers.Singleton(
        lambda s: __import__(
            "db.passive_storage", fromlist=["PassiveStorage"]
        ).PassiveStorage(dsn=s.postgres_url),
        s=settings
    )

    # Creator Chat Store - keeps last 40 messages per user for Creator mode
    creator_chat_store = providers.Singleton(
        lambda s: __import__(
            "db.creator_chat_store", fromlist=["CreatorChatStore"]
        ).CreatorChatStore(dsn=s.postgres_url),
        s=settings,
    )

    # Future Requests Storage - for future planning requests
    postgres_future_requests = providers.Singleton(
        lambda s: __import__(
            "db.postgres_future_requests", fromlist=["PostgresFutureRequests"]
        ).PostgresFutureRequests(dsn=s.postgres_url),
        s=settings,
    )

    # Financial Threads Storage - for financial threads
    postgres_financial_threads = providers.Singleton(
        lambda s: __import__(
            "db.postgres_financial_threads", fromlist=["PostgresFinancialThreads"]
        ).PostgresFinancialThreads(dsn=s.postgres_url),
        s=settings,
    )

    passive_memory = providers.Factory(
        lambda storage: __import__(
            "memory.passive_memory", fromlist=["PassiveMemory"]
        ).PassiveMemory(storage=storage),
        storage=passive_storage,
    )

    # NOTE: passive_service is defined after voice_processor (see below)

    # Relationship Feedback Service
    relationship_feedback_service = providers.Singleton(
        lambda s: __import__(
            "service.relationship_feedback_service", fromlist=["RelationshipFeedbackService"]
        ).RelationshipFeedbackService(dsn=s.postgres_url, settings=s),
        s=settings,
    )

    # Passive storages handler
    passive_storages_handler = providers.Singleton(
        lambda rel_cluster, dyadic, passive:__import__(
            "tone_and_personality_traits_detection.utils", fromlist=["PassiveStoragesHandler"]
        ).PassiveStoragesHandler(
            relationhip_cluster=rel_cluster,
            dyadic=dyadic,
            passive_storage=passive
        ),
        rel_cluster = postgres_relationship_cluster_personas,
        dyadic = postgres_dyadic_overrides,
        passive = passive_storage
    )

    # OpenAI client - must be defined before agents that use it
    openai_client = providers.Singleton(
        lambda s: __import__("openai", fromlist=["AsyncOpenAI"]).AsyncOpenAI(
            api_key=s.OPENAI_API_KEY,
            base_url=s.OPENAI_BASE_URL if s.OPENAI_BASE_URL else None,
        ),
        s=settings,
    )

    # =========================================================================
    # Voice Processing Components
    # =========================================================================

    # Voice Speech-to-Text (OpenRouter audio model)
    voice_stt = providers.Singleton(
        lambda client, s: __import__(
            "service.voice", fromlist=["OpenAISpeechToText"]
        ).OpenAISpeechToText(client=client, model=s.VOICE_STT_MODEL),
        client=openai_client,
        s=settings,
    )

    # Voice Text-to-Speech (OpenAI TTS)
    voice_tts = providers.Singleton(
        lambda client, s: __import__(
            "service.voice", fromlist=["OpenAITextToSpeech"]
        ).OpenAITextToSpeech(
            client=client,
            model=s.VOICE_TTS_MODEL,
            default_voice=s.VOICE_TTS_VOICE,
        ),
        client=openai_client,
        s=settings,
    )

    # Voice Storage (Local filesystem)
    voice_storage = providers.Singleton(
        lambda s: __import__(
            "service.voice", fromlist=["LocalVoiceStorage"]
        ).LocalVoiceStorage(base_path=s.VOICE_STORAGE_PATH),
        s=settings,
    )

    # Voice Processor (main service)
    voice_processor = providers.Singleton(
        lambda stt, tts, storage, s: __import__(
            "service.voice", fromlist=["VoiceProcessor"]
        ).VoiceProcessor(
            stt=stt,
            tts=tts,
            storage=storage,
            max_duration=s.VOICE_MAX_DURATION_SECONDS,
            tts_enabled=s.VOICE_TTS_ENABLED,
        ) if s.VOICE_ENABLED else None,
        stt=voice_stt,
        tts=voice_tts,
        storage=voice_storage,
        s=settings,
    )

    # Passive Service - must be after voice_processor
    passive_service = providers.Factory(
        lambda pm, s, voice: __import__(
            "service.passive_service", fromlist=["PassiveService"]
        ).PassiveService(pm, settings=s, voice_processor=voice),
        pm=passive_memory,
        s=settings,
        voice=voice_processor,
    )

    # Tone Detection Agent
    tone_detection_agent = providers.Factory(
        lambda s, client, model_name: __import__(
            "tone_and_personality_traits_detection.tone_detection_agent", fromlist=["ToneDetectionAgent"]
        ).ToneDetectionAgent(
            settings=s,
            openai_client=client,
            model_name=model_name,
        ),
        s=settings,
        client=openai_client,
        model_name=getattr(settings(), "AGENTS_MODEL", "gpt-4o-mini")
    )

    # Passive Archive Storage
    passive_archive_storage = providers.Singleton(
        lambda s: __import__(
            "db.passive_archive_storage", fromlist=["PassiveArchiveStorage"]
        ).PassiveArchiveStorage(dsn=s.postgres_url),
        s=settings,
    )

    # Passive Pair Counter
    passive_pair_counter = providers.Singleton(
        lambda s: __import__(
            "db.passive_archive_storage", fromlist=["PassivePairCounter"]
        ).PassivePairCounter(dsn=s.postgres_url, settings=s),
        s=settings,
    )

    # Tone Retry Storage - for retry queue and failed table
    tone_retry_storage = providers.Singleton(
        lambda s: __import__(
            "db.tone_retry_storage", fromlist=["ToneRetryStorage"]
        ).ToneRetryStorage(
            dsn=s.postgres_url,
            tenant_id=s.TENANT_ID,
            max_attempts=getattr(s, "TONE_RETRY_MAX_ATTEMPTS", 3),
            retry_delays=[int(x) for x in getattr(s, "TONE_RETRY_DELAYS_SECONDS", "300,3600,14400").split(",")],
        ),
        s=settings,
    )

    # Tone Scheduler - hourly processing
    tone_scheduler = providers.Factory(
        lambda s, tone_agent, passive, archive, pair_counter, rel_cluster, dyadic, retry_storage: __import__(
            "scheduler.tone_scheduler", fromlist=["ToneScheduler"]
        ).ToneScheduler(
            settings=s,
            tone_agent=tone_agent,
            passive_storage=passive,
            archive_storage=archive,
            pair_counter=pair_counter,
            relationship_cluster=rel_cluster,
            dyadic_overrides=dyadic,
            retry_storage=retry_storage,
        ),
        s=settings,
        tone_agent=tone_detection_agent,
        passive=passive_storage,
        archive=passive_archive_storage,
        pair_counter=passive_pair_counter,
        rel_cluster=postgres_relationship_cluster_personas,
        dyadic=postgres_dyadic_overrides,
        retry_storage=tone_retry_storage,
    )

    # Tone Retry Worker - retries failed tone analysis jobs
    tone_retry_worker = providers.Factory(
        lambda s, retry_storage, archive, pair_counter, rel_cluster, tone_agent: __import__(
            "scheduler.tone_retry_worker", fromlist=["ToneRetryWorker"]
        ).ToneRetryWorker(
            settings=s,
            retry_storage=retry_storage,
            archive_storage=archive,
            pair_counter=pair_counter,
            relationship_cluster=rel_cluster,
            tone_agent=tone_agent,
        ),
        s=settings,
        retry_storage=tone_retry_storage,
        archive=passive_archive_storage,
        pair_counter=passive_pair_counter,
        rel_cluster=postgres_relationship_cluster_personas,
        tone_agent=tone_detection_agent,
    )

    # Mem0 Adapter - MUST be defined BEFORE components that depend on it
    mem0_adapter = providers.Singleton(
        lambda s: __import__("memory.mem0_adapter", fromlist=["Mem0Adapter"]).Mem0Adapter(
            settings=s
        ),
        s=settings,
    )

    # Summarizer Agent - MUST be defined BEFORE components that depend on it
    summarizer_agent = providers.Factory(
        lambda s, client: __import__(
            "summarizer.summarizer_agent", fromlist=["SummarizerAgent"]
        ).SummarizerAgent(
            settings=s,
            openai_client=client,
        ),
        s=settings,
        client=openai_client,
    )

    # Passive Summarization Storage - for retry queue and failed table
    passive_summarization_storage = providers.Singleton(
        lambda s: __import__(
            "db.passive_summarization_storage", fromlist=["PassiveSummarizationStorage"]
        ).PassiveSummarizationStorage(
            dsn=s.postgres_url,
            tenant_id=s.TENANT_ID,
            max_attempts=getattr(s, "PASSIVE_SUMMARIZATION_MAX_ATTEMPTS", 3),
            retry_delays=[int(x) for x in getattr(s, "PASSIVE_SUMMARIZATION_RETRY_DELAYS", "300,3600,14400").split(",")],
        ),
        s=settings,
    )

    # Passive Summarizer Agent - uses mem0 for storage (like chat summary)
    passive_summarizer_agent = providers.Factory(
        lambda s, summarizer, archive, mem0: __import__(
            "summarizer.passive_summarizer_agent", fromlist=["PassiveSummarizerAgent"]
        ).PassiveSummarizerAgent(
            settings=s,
            summarizer_agent=summarizer,
            archive_storage=archive,
            mem0_adapter=mem0,
            min_messages=getattr(s, "PASSIVE_SUMMARIZATION_MIN_MESSAGES", 40),
            min_tokens=getattr(s, "PASSIVE_SUMMARIZATION_MIN_TOKENS", 300),
            max_messages=getattr(s, "PASSIVE_SUMMARIZATION_MAX_MESSAGES", 100),
        ),
        s=settings,
        summarizer=summarizer_agent,
        archive=passive_archive_storage,
        mem0=mem0_adapter,
    )

    # Passive Summarization Scheduler
    passive_summarization_scheduler = providers.Factory(
        lambda s, summarizer_svc, pair_counter, archive, retry_storage: __import__(
            "scheduler.passive_summarization_scheduler", fromlist=["PassiveSummarizationScheduler"]
        ).PassiveSummarizationScheduler(
            settings=s,
            summarizer_service=summarizer_svc,
            pair_counter=pair_counter,
            archive_storage=archive,
            retry_storage=retry_storage,
        ),
        s=settings,
        summarizer_svc=passive_summarizer_agent,
        pair_counter=passive_pair_counter,
        archive=passive_archive_storage,
        retry_storage=passive_summarization_storage,
    )

    # Passive Summarization Retry Worker
    passive_summarization_retry_worker = providers.Factory(
        lambda s, summarizer_svc, retry_storage, archive: __import__(
            "scheduler.passive_summarization_scheduler", fromlist=["PassiveSummarizationRetryWorker"]
        ).PassiveSummarizationRetryWorker(
            settings=s,
            summarizer_service=summarizer_svc,
            retry_storage=retry_storage,
            archive_storage=archive,
        ),
        s=settings,
        summarizer_svc=passive_summarizer_agent,
        retry_storage=passive_summarization_storage,
        archive=passive_archive_storage,
    )

    # Guardrails Agent
    guardrails_agent = providers.Factory(
        lambda s, client: __import__(
            "guardrail.guardrails_agent", fromlist=["GuardrailsAgent"]
        ).GuardrailsAgent(
            settings=s,
            openai_client=client,
        ),
        s=settings,
        client=openai_client,
    )

    # Listener Agent – now also uses Postgres chat_store (no time trigger, count-based only)
    listener_agent = providers.Factory(
        lambda mem0, summarizer, s, store: __import__(
            "listener.listener", fromlist=["ListenerAgent"]
        ).ListenerAgent(
            mem0_adapter=mem0,
            summarizer_agent=summarizer,
            summarize_threshold=s.MESSAGE_COUNT_THRESHOLD,
            min_chars_for_summary=getattr(s, "SUMMARY_MIN_CHARS", 0),
            settings=s,
            chat_store=store,  
            summarize_every_n_messages=s.MESSAGE_COUNT_THRESHOLD,  
        ),
        mem0=mem0_adapter,
        summarizer=summarizer_agent,
        s=settings,
        store=postgres_chat_store,
    )

    # Orchestrator Agent – composes with profile + summary (mem0) + recent messages (Postgres) + tone
    orchestrator_agent = providers.Factory(
        lambda s, listener, guards, client, mem0, store, dyadic, rel_cluster, creator_store, future_req, passive_archive, financial_threads: __import__(
            "orchestrator.orchestrator_agent", fromlist=["OrchestratorAgent"]
        ).OrchestratorAgent(
            settings=s,
            listener_agent=listener,
            guardrails_agent=guards,
            openai_client=client,
            mem0_adapter=mem0,
            chat_store=store,
            dyadic_overrides=dyadic,
            relationship_cluster=rel_cluster,
            creator_chat_store=creator_store,
            future_requests_store=future_req,
            passive_archive=passive_archive,
            financial_threads_store=financial_threads,  # NEW: for financial thread management
        ),
        s=settings,
        listener=listener_agent,
        guards=guardrails_agent,
        client=openai_client,
        mem0=mem0_adapter,
        store=postgres_chat_store,
        dyadic=postgres_dyadic_overrides,
        rel_cluster=postgres_relationship_cluster_personas,
        creator_store=creator_chat_store,
        future_req=postgres_future_requests,
        passive_archive=passive_archive_storage,
        financial_threads=postgres_financial_threads,  # NEW
    )

    # Feedback Scheduler - sends relationship questions to users
    feedback_scheduler = providers.Factory(
        lambda feedback_svc, rel_cluster, archive, s: __import__(
            "scheduler.feedback_scheduler", fromlist=["FeedbackScheduler"]
        ).FeedbackScheduler(
            feedback_service=feedback_svc,
            relationship_cluster=rel_cluster,
            archive_storage=archive,
            settings=s,
        ),
        feedback_svc=relationship_feedback_service,
        rel_cluster=postgres_relationship_cluster_personas,
        archive=passive_archive_storage,
        s=settings,
    )

    # Retry Worker - retries failed summarization jobs
    retry_worker = providers.Factory(
        lambda store, listener, s: __import__(
            "scheduler.retry_worker", fromlist=["RetryWorker"]
        ).RetryWorker(
            chat_store=store,
            listener_agent=listener,
            interval_seconds=getattr(s, "SUMMARY_RETRY_WORKER_INTERVAL_SECONDS", 300),
            settings=s,
        ),
        store=postgres_chat_store,
        listener=listener_agent,
        s=settings,
    )

    # Services
    chat_service = providers.Factory(
        lambda orch, voice: __import__(
            "service.chat_service", fromlist=["ChatService"]
        ).ChatService(orch, voice_processor=voice),
        orch=orchestrator_agent,
        voice=voice_processor,
    )

    creator_service = providers.Factory(
        lambda orch, voice: __import__(
            "service.creator_service", fromlist=["CreatorService"]
        ).CreatorService(orch, voice_processor=voice),
        orch=orchestrator_agent,
        voice=voice_processor,
    )

    # --- Optional lifecycle helpers for app startup/shutdown ---
    async def start(self) -> None:
        """Initialize async resources (e.g., Postgres pool)."""
        logger.info("Container starting: initializing database connections...")
        await self.chat_store().connect()
        logger.info("Container started successfully")

    async def shutdown(self) -> None:
        """Close async resources."""
        logger.info("Container shutting down: closing database connections...")
        await self.chat_store().close()
        logger.info("Container shutdown complete")
