
from __future__ import annotations

import sys
import logging
import sqlite3
from pathlib import Path
import psycopg2


sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import Settings
from db.qdrant import create_client as create_qdrant_client

logger = logging.getLogger(__name__)

def init_sqlite() -> None:
    logger.info("Initializing SQLite databases...")
    
    project_root = Path(__file__).parent.parent
    
    sqlite_dir = project_root / "sqlite_data"
    sqlite_dir.mkdir(exist_ok=True)
    logger.info("SQLite directory: %s", sqlite_dir)
    
    mem0_db = sqlite_dir / "mem0_history.db"
    logger.info("Creating mem0 history database: %s", mem0_db)
    conn = sqlite3.connect(str(mem0_db))
    conn.close()
    logger.info("mem0_history.db created successfully")
    

def init_qdrant(settings: Settings) -> None:
    logger.info("Initializing Qdrant...")
    
    client = create_qdrant_client(url=settings.QDRANT_URL)
    
    try:
        from qdrant_client.models import Distance, VectorParams
        
        embedding_dims = getattr(settings, 'MEM0_EMBEDDING_DIMS', 1024)
        
        collections_config = [
            {
                "name": "episodic_events",
                "description": "Episodic memory - time-bound events and experiences"
            },
            {
                "name": settings.MEM0_COLLECTION_NAME if hasattr(settings, 'MEM0_COLLECTION_NAME') else "mem0_memories",
                "description": "Mem0 unified memory - facts, events, and context"
            }
        ]
        
        for collection_config in collections_config:
            collection_name = collection_config["name"]
            
            try:
                existing = client.get_collection(collection_name)
                logger.info(
                    "Collection '%s' already exists (vectors: %d, size: %d)",
                    collection_name,
                    existing.points_count,
                    existing.config.params.vectors.size,
                )
            except Exception:
                logger.info(
                    "Creating collection '%s' (description: %s, vector_size: %d)",
                    collection_name,
                    collection_config['description'],
                    embedding_dims,
                )
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=embedding_dims,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Collection '%s' created successfully", collection_name)
        
        collections = client.get_collections()
        logger.info(
            "Qdrant initialized. Collections: %s",
            [c.name for c in collections.collections],
        )
        
    except ImportError:
        logger.warning("qdrant-client models not available, using stub client")
        logger.info("Qdrant stub initialized (no actual collections created)")

def init_postgres(settings: Settings) -> None:
    logger.info("Initializing PostgreSQL...")

    if psycopg2 is None:
        logger.warning("psycopg2 not installed. Skipping Postgres initialization.")
        logger.info("Run `pip install psycopg2-binary` and re-run this script if you need Postgres.")
        return

    from scripts.migrations import run_migrations
    run_migrations(settings)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    logger.info("=" * 60)
    logger.info("Joowme Agent Database Initialization")
    logger.info("=" * 60)
    
    logger.info("Loading settings from .env...")
    settings = Settings()
    logger.info("QDRANT_URL: %s", settings.QDRANT_URL)
    
    try:
        init_postgres(settings)
        
        init_sqlite()
        
        init_qdrant(settings)
        
        logger.info("=" * 60)
        logger.info("All databases initialized successfully!")
        logger.info("=" * 60)
        logger.info("Storage:")
        logger.info("  - Postgres: chat_events, passive_observation, passive_archive,")
        logger.info("              relationship_cluster_personas, dyadic_overrides,")
        logger.info("              passive_summarization_retry_queue, passive_summarization_failed,")
        logger.info("              future_requests, financial_threads, financial_thread_messages")
        logger.info("  - SQLite: ./sqlite_data/mem0_history.db (conversation history)")
        logger.info("  - Qdrant: memories and embeddings (Docker volume)")
        logger.info("Next steps:")
        logger.info("  1. Run the server: uvicorn main:app --reload")
        logger.info("  2. Test the API via streamlit or curl")
        
    except Exception as e:
        logger.error("Initialization failed: %s", e, exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
