from __future__ import annotations

import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Callable
import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import Settings

logger = logging.getLogger(__name__)


MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "Create schema_migrations table", """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """),
    
    (2, "Create chat_events table", """
        CREATE TABLE IF NOT EXISTS chat_events (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            pair_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            author_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'human',
            text TEXT NOT NULL,
            token_count INT NOT NULL DEFAULT 0,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted BOOLEAN NOT NULL DEFAULT FALSE
        );
        
        CREATE INDEX IF NOT EXISTS idx_events_pair_ts
            ON chat_events(tenant_id, pair_id, conversation_id, deleted, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_events_deleted
            ON chat_events(tenant_id, pair_id, conversation_id, deleted);
    """),
    
    (4, "Create passive_observation table", """
        CREATE TABLE IF NOT EXISTS passive_observation (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            message TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'fa',
            timestamp_iso TEXT NOT NULL,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted TEXT NOT NULL DEFAULT 'false',
            UNIQUE (conversation_id, message_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_passive_user_ts
            ON passive_observation(user_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_passive_conversation
            ON passive_observation(conversation_id, ts DESC);
    """),
    
    (5, "Create passive_last_message table", """
        CREATE TABLE IF NOT EXISTS passive_last_message (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL UNIQUE,
            last_message_id TEXT NOT NULL,
            last_message TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """),
    
    (6, "Create relationship_cluster_personas table (original)", """
        CREATE TABLE IF NOT EXISTS relationship_cluster_personas (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            cluster_name TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            avg_formality REAL,
            avg_humor REAL,
            emoji_rate REAL,
            profanity_rate REAL,
            directness REAL,
            style_summary TEXT,
            last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, cluster_name)
        );
        
        CREATE INDEX IF NOT EXISTS idx_rel_cluster_user 
            ON relationship_cluster_personas (user_id);
    """),
    
    (7, "Create dyadic_overrides table (original)", """
        CREATE TABLE IF NOT EXISTS dyadic_overrides (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            to_user_id TEXT NOT NULL,
            direction SMALLINT NOT NULL DEFAULT 0,
            message_count INTEGER NOT NULL DEFAULT 0,
            avg_formality REAL,
            avg_humor REAL,
            emoji_rate REAL,
            profanity_rate REAL,
            directness REAL,
            style_summary TEXT,
            last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, to_user_id, direction)
        );
        
        CREATE INDEX IF NOT EXISTS idx_dyadic_user_other 
            ON dyadic_overrides (user_id, to_user_id);
        CREATE INDEX IF NOT EXISTS idx_dyadic_other_user 
            ON dyadic_overrides (to_user_id);
    """),
    
    (8, "Create summarization_retry_queue table (original)", """
        CREATE TABLE IF NOT EXISTS summarization_retry_queue (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            pair_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            attempt_count INT NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMPTZ NOT NULL,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_retry_queue_next_retry
            ON summarization_retry_queue(tenant_id, next_retry_at)
            WHERE attempt_count < 10;
    """),
    
    (9, "Enable Row Level Security", """
        ALTER TABLE chat_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE summarization_retry_queue ENABLE ROW LEVEL SECURITY;
        
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_policy_chat_events'
            ) THEN
                CREATE POLICY tenant_isolation_policy_chat_events
                ON chat_events
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END$$;
        
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_policy_retry_queue'
            ) THEN
                CREATE POLICY tenant_isolation_policy_retry_queue
                ON summarization_retry_queue
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END$$;
    """),
    
    
    (10, "Upgrade relationship_cluster_personas with new fields", """
        -- اضافه کردن ستون members به صورت jsonb
        -- فرمت: [{"user_id": "user_4", "confidence": 0.3}, ...]
        ALTER TABLE relationship_cluster_personas 
        ADD COLUMN IF NOT EXISTS members JSONB DEFAULT '[]'::jsonb;
        
        -- تغییر نام message_count به total_message_count
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'relationship_cluster_personas' 
                       AND column_name = 'message_count') THEN
                ALTER TABLE relationship_cluster_personas 
                RENAME COLUMN message_count TO total_message_count;
            END IF;
        END$$;
        
        -- اضافه کردن ستون‌های جدید متریک
        ALTER TABLE relationship_cluster_personas 
        ADD COLUMN IF NOT EXISTS optimistic_rate REAL DEFAULT 0.5;
        
        ALTER TABLE relationship_cluster_personas 
        ADD COLUMN IF NOT EXISTS pessimistic_rate REAL DEFAULT 0.5;
        
        ALTER TABLE relationship_cluster_personas 
        ADD COLUMN IF NOT EXISTS submissive_rate REAL DEFAULT 0.5;
        
        ALTER TABLE relationship_cluster_personas 
        ADD COLUMN IF NOT EXISTS dominance REAL DEFAULT 0.5;
        
        ALTER TABLE relationship_cluster_personas 
        ADD COLUMN IF NOT EXISTS emotional_dependence_rate REAL DEFAULT 0.5;
        
        ALTER TABLE relationship_cluster_personas 
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
        
        -- تنظیم مقادیر پیش‌فرض برای ستون‌های قدیمی
        ALTER TABLE relationship_cluster_personas 
        ALTER COLUMN avg_formality SET DEFAULT 0.5;
        
        ALTER TABLE relationship_cluster_personas 
        ALTER COLUMN avg_humor SET DEFAULT 0.3;
        
        ALTER TABLE relationship_cluster_personas 
        ALTER COLUMN profanity_rate SET DEFAULT 0.0;
        
        ALTER TABLE relationship_cluster_personas 
        ALTER COLUMN directness SET DEFAULT 0.5;
        
        -- ایندکس جدید
        CREATE INDEX IF NOT EXISTS idx_rel_cluster_name 
            ON relationship_cluster_personas (user_id, cluster_name);
    """),
    
    (11, "Upgrade dyadic_overrides with new schema", """
        -- تغییر نام ستون‌ها
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'dyadic_overrides' 
                       AND column_name = 'user_id') 
               AND NOT EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'dyadic_overrides' 
                       AND column_name = 'source_user_id') THEN
                ALTER TABLE dyadic_overrides 
                RENAME COLUMN user_id TO source_user_id;
            END IF;
        END$$;
        
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'dyadic_overrides' 
                       AND column_name = 'to_user_id') 
               AND NOT EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'dyadic_overrides' 
                       AND column_name = 'target_user_id') THEN
                ALTER TABLE dyadic_overrides 
                RENAME COLUMN to_user_id TO target_user_id;
            END IF;
        END$$;
        
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'dyadic_overrides' 
                       AND column_name = 'message_count') THEN
                ALTER TABLE dyadic_overrides 
                RENAME COLUMN message_count TO total_message_count;
            END IF;
        END$$;
        
        -- اضافه کردن ستون‌های جدید
        ALTER TABLE dyadic_overrides 
        ADD COLUMN IF NOT EXISTS relationship_class TEXT;
        
        ALTER TABLE dyadic_overrides 
        ADD COLUMN IF NOT EXISTS optimistic_rate REAL DEFAULT 0.5;
        
        ALTER TABLE dyadic_overrides 
        ADD COLUMN IF NOT EXISTS pessimistic_rate REAL DEFAULT 0.5;
        
        ALTER TABLE dyadic_overrides 
        ADD COLUMN IF NOT EXISTS submissive_rate REAL DEFAULT 0.5;
        
        ALTER TABLE dyadic_overrides 
        ADD COLUMN IF NOT EXISTS dominance REAL DEFAULT 0.5;
        
        ALTER TABLE dyadic_overrides 
        ADD COLUMN IF NOT EXISTS emotional_dependence_rate REAL DEFAULT 0.5;
        
        ALTER TABLE dyadic_overrides 
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
        
        -- حذف ستون direction (دیگر استفاده نمی‌شود)
        ALTER TABLE dyadic_overrides 
        DROP COLUMN IF EXISTS direction;
        
        -- به‌روزرسانی unique constraint
        DO $$
        BEGIN
            -- حذف constraint قدیمی اگر وجود دارد
            IF EXISTS (SELECT 1 FROM pg_constraint 
                       WHERE conname = 'dyadic_overrides_user_id_to_user_id_direction_key') THEN
                ALTER TABLE dyadic_overrides 
                DROP CONSTRAINT dyadic_overrides_user_id_to_user_id_direction_key;
            END IF;
        END$$;
        
        -- ایجاد constraint جدید (اگر وجود ندارد)
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint 
                           WHERE conname = 'dyadic_overrides_source_user_id_target_user_id_key') THEN
                ALTER TABLE dyadic_overrides 
                ADD CONSTRAINT dyadic_overrides_source_user_id_target_user_id_key 
                UNIQUE (source_user_id, target_user_id);
            END IF;
        END$$;
        
        -- به‌روزرسانی ایندکس‌ها
        DROP INDEX IF EXISTS idx_dyadic_user_other;
        DROP INDEX IF EXISTS idx_dyadic_other_user;
        
        CREATE INDEX IF NOT EXISTS idx_dyadic_source_target 
            ON dyadic_overrides (source_user_id, target_user_id);
        CREATE INDEX IF NOT EXISTS idx_dyadic_target 
            ON dyadic_overrides (target_user_id);
    """),
    
    (12, "Add user_a and user_b to summarization_retry_queue", """
        ALTER TABLE summarization_retry_queue 
        ADD COLUMN IF NOT EXISTS user_a TEXT NOT NULL DEFAULT '';
        
        ALTER TABLE summarization_retry_queue 
        ADD COLUMN IF NOT EXISTS user_b TEXT NOT NULL DEFAULT '';
    """),
    
    (13, "Create passive_archive table", """
        CREATE TABLE IF NOT EXISTS passive_archive (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            to_user_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            message TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'fa',
            timestamp_iso TEXT NOT NULL,
            archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (conversation_id, message_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_passive_archive_pair 
            ON passive_archive (user_id, to_user_id);
        CREATE INDEX IF NOT EXISTS idx_passive_archive_conv 
            ON passive_archive (conversation_id);
    """),
    
    (14, "Create passive_pair_counter table", """
        CREATE TABLE IF NOT EXISTS passive_pair_counter (
            id BIGSERIAL PRIMARY KEY,
            user_a TEXT NOT NULL,
            user_b TEXT NOT NULL,
            pair_id TEXT NOT NULL,
            total_archived_count INTEGER NOT NULL DEFAULT 0,
            last_dyadic_calc_at_count INTEGER NOT NULL DEFAULT 0,
            last_relationship_class TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (pair_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_pair_counter_users 
            ON passive_pair_counter (user_a, user_b);
    """),
    
    (15, "Create relationship_feedback_questions table", """
        CREATE TABLE IF NOT EXISTS relationship_feedback_questions (
            id BIGSERIAL PRIMARY KEY,
            asking_user_id TEXT NOT NULL,
            about_user_id TEXT NOT NULL,
            pair_id TEXT NOT NULL,
            conversation_summary TEXT NOT NULL,
            sample_messages TEXT[],
            status TEXT NOT NULL DEFAULT 'pending',
            question_text TEXT NOT NULL,
            answer_relationship_class TEXT,
            answer_text TEXT,
            answered_at TIMESTAMPTZ,
            sent_count INTEGER NOT NULL DEFAULT 1,
            last_sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            next_retry_at TIMESTAMPTZ,
            never_ask_again BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (asking_user_id, about_user_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_feedback_asking_user 
            ON relationship_feedback_questions (asking_user_id, status);
        CREATE INDEX IF NOT EXISTS idx_feedback_status_retry 
            ON relationship_feedback_questions (status, next_retry_at)
            WHERE status = 'pending';
        CREATE INDEX IF NOT EXISTS idx_feedback_pair 
            ON relationship_feedback_questions (pair_id);
    """),
    
    (17, "Create confirmed_relationships table", """
        CREATE TABLE IF NOT EXISTS confirmed_relationships (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            related_user_id TEXT NOT NULL,
            relationship_class TEXT NOT NULL,
            confirmed_by TEXT NOT NULL,
            confirmed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_locked BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE (user_id, related_user_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_confirmed_rel_user 
            ON confirmed_relationships (user_id);
        CREATE INDEX IF NOT EXISTS idx_confirmed_rel_pair 
            ON confirmed_relationships (user_id, related_user_id);
    """),
    
    (18, "Add to_user_id to passive_observation", """
        ALTER TABLE passive_observation 
        ADD COLUMN IF NOT EXISTS to_user_id TEXT DEFAULT '';
    """),
    
    (19, "Create tone_retry_queue table", """
        CREATE TABLE IF NOT EXISTS tone_retry_queue (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            conversation_id TEXT NOT NULL,
            user_a TEXT NOT NULL,
            user_b TEXT NOT NULL,
            message_ids BIGINT[] NOT NULL DEFAULT '{}',
            attempt_count INT NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMPTZ NOT NULL,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_tone_retry_queue_next_retry
            ON tone_retry_queue(tenant_id, next_retry_at)
            WHERE attempt_count < 3;
            
        CREATE INDEX IF NOT EXISTS idx_tone_retry_queue_conv
            ON tone_retry_queue(tenant_id, conversation_id);
    """),
    
    (20, "Create tone_failed table", """
        CREATE TABLE IF NOT EXISTS tone_failed (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            conversation_id TEXT NOT NULL,
            user_a TEXT NOT NULL,
            user_b TEXT NOT NULL,
            message_ids BIGINT[] NOT NULL DEFAULT '{}',
            attempt_count INT NOT NULL DEFAULT 3,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_tone_failed_conv
            ON tone_failed(tenant_id, conversation_id);
            
        CREATE INDEX IF NOT EXISTS idx_tone_failed_created
            ON tone_failed(tenant_id, created_at DESC);
    """),
    
    (21, "Create summarization_failed table", """
        CREATE TABLE IF NOT EXISTS summarization_failed (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            pair_id TEXT NOT NULL,
            user_a TEXT NOT NULL,
            user_b TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            attempt_count INT NOT NULL DEFAULT 3,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_summary_failed_pair
            ON summarization_failed(tenant_id, pair_id);
            
        CREATE INDEX IF NOT EXISTS idx_summary_failed_created
            ON summarization_failed(tenant_id, created_at DESC);
    """),
    
    (22, "Create creator_chat_events table", """
        CREATE TABLE IF NOT EXISTS creator_chat_events (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'human',  -- 'human' | 'ai'
            text TEXT NOT NULL,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        -- ایندکس برای دسترسی سریع به پیام‌های هر کاربر
        CREATE INDEX IF NOT EXISTS idx_creator_chat_user_ts
            ON creator_chat_events(user_id, ts DESC);
            
        -- ایندکس برای حذف پیام‌های قدیمی
        CREATE INDEX IF NOT EXISTS idx_creator_chat_ts
            ON creator_chat_events(ts);
    """),
    
    (23, "Add message_id to chat_events", """
        -- اضافه کردن ستون message_id
        ALTER TABLE chat_events 
        ADD COLUMN IF NOT EXISTS message_id TEXT;
        
        -- ایندکس برای جلوگیری از درج تکراری
        CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_events_message_id
            ON chat_events(tenant_id, pair_id, conversation_id, message_id)
            WHERE message_id IS NOT NULL;
    """),
    
    (24, "Change members column to jsonb with confidence", """
        -- حذف default قدیمی
        ALTER TABLE relationship_cluster_personas 
        ALTER COLUMN members DROP DEFAULT;
        
        -- تبدیل به jsonb (با مقدار خالی برای داده‌های موجود)
        ALTER TABLE relationship_cluster_personas 
        ALTER COLUMN members TYPE jsonb USING '[]'::jsonb;
        
        -- تنظیم default جدید
        ALTER TABLE relationship_cluster_personas 
        ALTER COLUMN members SET DEFAULT '[]'::jsonb;
    """),
    
    (25, "Create passive_summarization_retry_queue table", """
        CREATE TABLE IF NOT EXISTS passive_summarization_retry_queue (
            id BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
            conversation_id VARCHAR(255) NOT NULL,
            pair_id VARCHAR(32) NOT NULL,
            user_a VARCHAR(255) NOT NULL,
            user_b VARCHAR(255) NOT NULL,
            message_ids BIGINT[] NOT NULL DEFAULT '{}',
            attempt_count INT NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMPTZ NOT NULL,
            last_error TEXT DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_passive_summ_retry_tenant_next 
            ON passive_summarization_retry_queue(tenant_id, next_retry_at);
        
        CREATE INDEX IF NOT EXISTS idx_passive_summ_retry_pair 
            ON passive_summarization_retry_queue(pair_id);
    """),
    
    (26, "Create passive_summarization_failed table", """
        CREATE TABLE IF NOT EXISTS passive_summarization_failed (
            id BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
            conversation_id VARCHAR(255) NOT NULL,
            pair_id VARCHAR(32) NOT NULL,
            user_a VARCHAR(255) NOT NULL,
            user_b VARCHAR(255) NOT NULL,
            message_ids BIGINT[] NOT NULL DEFAULT '{}',
            attempt_count INT NOT NULL DEFAULT 0,
            last_error TEXT DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL,
            failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_passive_summ_failed_tenant 
            ON passive_summarization_failed(tenant_id);
        
        CREATE INDEX IF NOT EXISTS idx_passive_summ_failed_pair 
            ON passive_summarization_failed(pair_id);
    """),
    
    (27, "Add deleted column to passive_archive", """
        -- اضافه کردن ستون deleted با مقدار پیش‌فرض FALSE
        ALTER TABLE passive_archive 
        ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT FALSE;
        
        -- ایندکس برای فیلتر کردن پیام‌های غیر حذف شده
        CREATE INDEX IF NOT EXISTS idx_passive_archive_deleted 
            ON passive_archive (user_id, to_user_id, deleted)
            WHERE deleted = FALSE;
        
        -- ایندکس ترکیبی برای کوئری‌های خلاصه‌سازی
        CREATE INDEX IF NOT EXISTS idx_passive_archive_pair_deleted 
            ON passive_archive (user_id, to_user_id, deleted, timestamp_iso DESC);
    """),
    
    (28, "Create future_requests table", """
        CREATE TABLE IF NOT EXISTS future_requests (
            id SERIAL PRIMARY KEY,
            sender_id VARCHAR(255) NOT NULL,
            recipient_id VARCHAR(255) NOT NULL,
            original_message TEXT NOT NULL,
            detected_plan TEXT NOT NULL,
            detected_datetime VARCHAR(255),
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            creator_response TEXT,
            responded_at TIMESTAMPTZ,
            delivered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_future_requests_recipient_status 
            ON future_requests(recipient_id, status);
        CREATE INDEX IF NOT EXISTS idx_future_requests_sender_status 
            ON future_requests(sender_id, status);
        CREATE INDEX IF NOT EXISTS idx_future_requests_status 
            ON future_requests(status);
    """),
    
    (29, "Add conversation_id to future_requests", """
        -- اضافه کردن ستون conversation_id
        ALTER TABLE future_requests 
        ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(255);
        
        -- ایندکس برای جستجو بر اساس conversation_id
        CREATE INDEX IF NOT EXISTS idx_future_requests_conversation_id 
            ON future_requests(conversation_id);
    """),
    
    (30, "Create financial_threads and financial_thread_messages tables", """
        -- جدول اصلی thread های مالی
        CREATE TABLE IF NOT EXISTS financial_threads (
            id SERIAL PRIMARY KEY,
            sender_id VARCHAR(255) NOT NULL,
            creator_id VARCHAR(255) NOT NULL,
            conversation_id VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'open',
            waiting_for VARCHAR(50) NOT NULL DEFAULT 'creator',
            topic_summary TEXT NOT NULL,
            last_sender_message TEXT,
            last_creator_response TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- جدول پیام‌های هر thread
        CREATE TABLE IF NOT EXISTS financial_thread_messages (
            id SERIAL PRIMARY KEY,
            thread_id INTEGER REFERENCES financial_threads(id) ON DELETE CASCADE,
            author_type VARCHAR(50) NOT NULL,
            message TEXT NOT NULL,
            delivered BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Index ها
        CREATE INDEX IF NOT EXISTS idx_fin_threads_sender_creator_status 
            ON financial_threads(sender_id, creator_id, status);
        CREATE INDEX IF NOT EXISTS idx_fin_threads_status_activity 
            ON financial_threads(status, last_activity_at);
        CREATE INDEX IF NOT EXISTS idx_fin_thread_msgs_thread_delivered 
            ON financial_thread_messages(thread_id, delivered);
    """),
    
    (32, "Add voice support columns to passive_observation", """
        -- اضافه کردن ستون نوع ورودی (متن یا ویس)
        ALTER TABLE passive_observation 
        ADD COLUMN IF NOT EXISTS input_type VARCHAR(16) DEFAULT 'text';
        
        -- اضافه کردن ستون URL فایل صوتی اصلی (برای آرشیو)
        ALTER TABLE passive_observation 
        ADD COLUMN IF NOT EXISTS voice_url TEXT DEFAULT NULL;
        
        -- ایندکس برای فیلتر پیام‌های صوتی
        CREATE INDEX IF NOT EXISTS idx_passive_obs_input_type 
            ON passive_observation(input_type);
    """),
    
    (33, "Add voice metadata to chat_events and creator_chat_events", """
        -- اضافه کردن ستون‌های voice به chat_events
        ALTER TABLE chat_events 
        ADD COLUMN IF NOT EXISTS input_type VARCHAR(16) DEFAULT 'text';
        
        ALTER TABLE chat_events 
        ADD COLUMN IF NOT EXISTS voice_url TEXT DEFAULT NULL;
        
        ALTER TABLE chat_events 
        ADD COLUMN IF NOT EXISTS voice_duration_seconds REAL DEFAULT NULL;
        
        -- اضافه کردن ستون‌های voice به creator_chat_events  
        ALTER TABLE creator_chat_events 
        ADD COLUMN IF NOT EXISTS input_type VARCHAR(16) DEFAULT 'text';
        
        ALTER TABLE creator_chat_events 
        ADD COLUMN IF NOT EXISTS voice_url TEXT DEFAULT NULL;
        
        ALTER TABLE creator_chat_events 
        ADD COLUMN IF NOT EXISTS voice_duration_seconds REAL DEFAULT NULL;
        
        -- ایندکس‌ها برای فیلتر پیام‌های صوتی
        CREATE INDEX IF NOT EXISTS idx_chat_events_input_type 
            ON chat_events(input_type);
            
        CREATE INDEX IF NOT EXISTS idx_creator_chat_input_type 
            ON creator_chat_events(input_type);
    """),
    
]


def get_connection(settings: Settings):
    return psycopg2.connect(settings.postgres_dsn)


def get_applied_versions(conn) -> set:
    cur = conn.cursor()
    try:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        return {row[0] for row in cur.fetchall()}
    except psycopg2.errors.UndefinedTable:
        conn.rollback()
        return set()
    finally:
        cur.close()


def apply_migration(conn, version: int, description: str, sql: str) -> bool:
    cur = conn.cursor()
    try:
        logger.info("Applying migration v%d: %s", version, description)
        
        cur.execute(sql)
        
        cur.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (%s, %s)",
            (version, description)
        )
        
        conn.commit()
        logger.info("Migration v%d applied successfully", version)
        return True
        
    except Exception as e:
        conn.rollback()
        logger.error("Migration v%d failed: %s", version, e, exc_info=True)
        return False
    finally:
        cur.close()


def run_migrations(settings: Settings) -> None:
    logger.info("Starting database migrations")
    logger.info("DSN: %s", settings.postgres_dsn.replace(settings.POSTGRES_PASSWORD, '***'))
    
    conn = get_connection(settings)
    conn.autocommit = False
    
    try:
        applied = get_applied_versions(conn)
        pending = [(v, d, s) for v, d, s in MIGRATIONS if v not in applied]
        
        if not pending:
            logger.info("Database is up to date. No migrations needed.")
            return
        
        logger.info("Found %d pending migration(s)", len(pending))
        for v, d, _ in pending:
            logger.debug("Pending: v%d - %s", v, d)
        
        success_count = 0
        for version, description, sql in pending:
            if apply_migration(conn, version, description, sql):
                success_count += 1
            else:
                logger.error("Migration stopped at v%d. Fix the error and retry.", version)
                break
        
        logger.info("Applied %d/%d migration(s)", success_count, len(pending))
        
    finally:
        conn.close()


def show_status(settings: Settings) -> None:
    logger.info("Migration Status")
    
    conn = get_connection(settings)
    try:
        applied = get_applied_versions(conn)
        
        for version, description, _ in MIGRATIONS:
            status = "applied" if version in applied else "pending"
            logger.info("v%d [%s]: %s", version, status, description)
        
        logger.info("Total: %d/%d applied", len(applied), len(MIGRATIONS))
        
    finally:
        conn.close()


def reset_database(settings: Settings) -> None:
    logger.warning("WARNING: This will DROP ALL TABLES!")
    confirm = input("Type 'yes' to confirm: ")
    
    if confirm.lower() != 'yes':
        logger.info("Reset aborted by user")
        return
    
    conn = get_connection(settings)
    conn.autocommit = True
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        tables = [row[0] for row in cur.fetchall()]
        
        logger.info("Dropping %d tables...", len(tables))
        for table in tables:
            logger.info("DROP TABLE %s", table)
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        
        logger.info("All tables dropped successfully")
        
    finally:
        cur.close()
        conn.close()
    
    run_migrations(settings)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="Database Migration Tool")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--reset", action="store_true", help="Reset database (DANGEROUS!)")
    args = parser.parse_args()
    
    settings = Settings()
    
    if args.status:
        show_status(settings)
    elif args.reset:
        reset_database(settings)
    else:
        run_migrations(settings)


if __name__ == "__main__":
    main()
