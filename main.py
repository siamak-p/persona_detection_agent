
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.chat import router as chat_router
from api.routers.creator import router as creator_router
from api.routers.passive import router as passive_router
from api.routers.passive_last_message_id import router as passive_last_id_router
from api.routers.feedback import router as feedback_router
from api.routers.scheduler import router as scheduler_router
from api.routers.websocket_notifications import router as ws_router
from api.routers.voice_static import router as voice_router
from config.container import Container
from config.settings import Settings

from observability.phoenix_setup import init_phoenix_tracing, shutdown_tracing
from observability.metrics import setup_prometheus_metrics
from observability.sqlite_metrics import create_sqlite_collector

logger = logging.getLogger(__name__)

_settings = Settings()
if _settings.OPENAI_BASE_URL:
    os.environ["OPENAI_BASE_URL"] = _settings.OPENAI_BASE_URL
if _settings.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = _settings.OPENAI_API_KEY


_sqlite_collector = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sqlite_collector
    
    
    phoenix_endpoint = os.getenv("PHOENIX_ENDPOINT", "http://localhost:4317")
    tracing_enabled = init_phoenix_tracing(
        service_name="joowme-agent",
        phoenix_endpoint=phoenix_endpoint,
        enable_openai=True,
        enable_openai_agents=True,
    )
    if tracing_enabled:
        logger.info("application:startup:phoenix_tracing_enabled ✓")
    else:
        logger.warning("application:startup:phoenix_tracing_disabled (check Phoenix connection)")
    
    
    container = Container()
    container.wire(
        modules=[
            "api.routers.chat",
            "api.routers.creator",
            "api.routers.passive",
            "api.routers.passive_last_message_id",
            "api.routers.feedback",
        ]
    )

    settings = container.settings()

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper()),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    
    logger.info("=" * 70)
    logger.info("🤖 LLM Configuration:")
    logger.info("-" * 70)
    logger.info(f"  💬 COMPOSER (Chat):     {settings.COMPOSER_MODEL:<25} temp={settings.COMPOSER_TEMPERATURE}")
    logger.info(f"  🎨 CREATOR:             {settings.CREATOR_MODEL:<25} temp={settings.CREATOR_TEMPERATURE}")
    logger.info(f"  🛡️  GUARDRAIL:           {settings.GUARDRAIL_MODEL:<25} temp={settings.GUARDRAIL_TEMPERATURE}")
    logger.info(f"  📝 SUMMARIZER:          {settings.SUMMARIZER_MODEL:<25} temp={settings.SUMMARIZER_TEMPERATURE}")
    logger.info(f"  🔍 FACT_EXTRACTOR:      {settings.FACT_EXTRACTOR_MODEL:<25} temp={settings.FACT_EXTRACTOR_TEMPERATURE}")
    logger.info(f"  🎭 TONE_DETECTION:      {settings.TONE_MODEL:<25} temp={settings.TONE_TEMPERATURE}")
    logger.info(f"  🧠 MEM0:                {settings.MEM0_LLM_MODEL:<25} temp={settings.MEM0_LLM_TEMPERATURE}")
    logger.info(f"  🎤 VOICE_STT:           {settings.VOICE_STT_MODEL:<25} enabled={settings.VOICE_ENABLED}")
    logger.info("-" * 70)
    logger.info(f"  📦 EMBEDDING:           {settings.MEM0_EMBEDDING_MODEL}")
    logger.info("=" * 70)

    
    try:
        from pathlib import Path
        sqlite_db_path = Path(__file__).parent / "sqlite_data" / "mem0_history.db"
        if sqlite_db_path.exists():
            _sqlite_collector = create_sqlite_collector(
                db_path=str(sqlite_db_path),
                db_name="mem0_history",
                collection_interval=60,
            )
            await _sqlite_collector.start_background_collection()
            logger.info("application:startup:sqlite_metrics_started ✓")
        else:
            logger.info(f"application:startup:sqlite_db_not_found ({sqlite_db_path})")
    except Exception as e:
        logger.warning(f"application:startup:sqlite_metrics_failed: {e}")


    try:
        logger.info("application:startup:preloading_embedder")
        mem0_adapter = container.mem0_adapter()
        logger.info("application:startup:embedder_ready ✓")
    except Exception as e:
        logger.error(f"application:startup:preload_failed: {e}", exc_info=True)

    
    try:
        logger.info("application:startup:ensuring_financial_threads_tables")
        financial_threads_store = container.postgres_financial_threads()
        await financial_threads_store.ensure_table()
        logger.info("application:startup:financial_threads_tables_ready ✓")
    except Exception as e:
        logger.error(f"application:startup:financial_threads_tables_failed: {e}", exc_info=True)


    tone_scheduler = None
    feedback_scheduler = None
    retry_worker = None
    tone_retry_worker = None
    passive_summarization_scheduler = None
    passive_summarization_retry_worker = None
    
    try:
        tone_scheduler = container.tone_scheduler()
        await tone_scheduler.start()
        logger.info("application:startup:tone_scheduler_started ✓")
        
        tone_retry_worker = container.tone_retry_worker()
        await tone_retry_worker.start()
        logger.info("application:startup:tone_retry_worker_started ✓")
        
        feedback_scheduler = container.feedback_scheduler()
        await feedback_scheduler.start()
        logger.info("application:startup:feedback_scheduler_started ✓")
        
        retry_worker = container.retry_worker()
        await retry_worker.start()
        logger.info("application:startup:retry_worker_started ✓")
        
        passive_summarization_scheduler = container.passive_summarization_scheduler()
        await passive_summarization_scheduler.start()
        logger.info("application:startup:passive_summarization_scheduler_started ✓")
        
        passive_summarization_retry_worker = container.passive_summarization_retry_worker()
        await passive_summarization_retry_worker.start()
        logger.info("application:startup:passive_summarization_retry_worker_started ✓")
        
    except Exception as e:
        logger.error(f"application:startup:scheduler_failed: {e}", exc_info=True)

    logger.info("application:startup:complete (using mem0ai for memory)")

    yield

    
    logger.info("application:shutdown:start")
    
    if _sqlite_collector:
        try:
            await _sqlite_collector.stop_background_collection()
            logger.info("application:shutdown:sqlite_metrics_stopped")
        except Exception as e:
            logger.error(f"application:shutdown:sqlite_metrics_stop_failed: {e}")
    
    try:
        if tone_scheduler:
            await tone_scheduler.stop()
            logger.info("application:shutdown:tone_scheduler_stopped")
        if tone_retry_worker:
            await tone_retry_worker.stop()
            logger.info("application:shutdown:tone_retry_worker_stopped")
        if feedback_scheduler:
            await feedback_scheduler.stop()
            logger.info("application:shutdown:feedback_scheduler_stopped")
        if retry_worker:
            await retry_worker.stop()
            logger.info("application:shutdown:retry_worker_stopped")
        if passive_summarization_scheduler:
            await passive_summarization_scheduler.stop()
            logger.info("application:shutdown:passive_summarization_scheduler_stopped")
        if passive_summarization_retry_worker:
            await passive_summarization_retry_worker.stop()
            logger.info("application:shutdown:passive_summarization_retry_worker_stopped")
    except Exception as e:
        logger.error(f"application:shutdown:scheduler_stop_failed: {e}", exc_info=True)
    
    shutdown_tracing()
    logger.info("application:shutdown:tracing_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PetaProcTwin API",
        version="1.0.0",
        lifespan=lifespan,
    )

    setup_prometheus_metrics(
        app,
        app_name="joowme_agent",
    )
    logger.info("application:create_app:prometheus_metrics_enabled ✓")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router)
    app.include_router(creator_router)
    app.include_router(passive_router)
    app.include_router(passive_last_id_router)
    app.include_router(feedback_router)
    app.include_router(scheduler_router)
    app.include_router(ws_router)
    app.include_router(voice_router)

    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "message": "PetaProcTwin API is running",
            "observability": {
                "phoenix_ui": "http://localhost:6006",
                "grafana": "http://localhost:3001",
                "prometheus": "http://localhost:9091",
            },
            "endpoints": [
                "POST /api/v1/chat",
                "POST /api/v1/creator",
                "POST /api/v1/passive",
                "GET /api/v1/passive/last-msgId",
                "GET /api/v1/feedback/questions/{user_id}",
                "POST /api/v1/feedback/answer",
                "POST /api/v1/feedback/skip",
                "GET /voices/{conversation_id}/{filename}",
                "GET /metrics",
            ],
        }

    return app


app = create_app()
