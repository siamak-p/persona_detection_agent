
from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List
import asyncio
from concurrent.futures import ThreadPoolExecutor

from prometheus_client import Gauge, Counter, Histogram, REGISTRY, CollectorRegistry

logger = logging.getLogger(__name__)


@dataclass
class SQLiteStats:
    file_size_bytes: int
    wal_size_bytes: int
    page_count: int
    page_size: int
    freelist_count: int
    table_count: int
    index_count: int
    tables: Dict[str, int]
    cache_hit_ratio: float
    schema_version: int


class SQLiteMetricsCollector:
    
    def __init__(
        self,
        db_path: str,
        db_name: str = "mem0_history",
        registry: CollectorRegistry = REGISTRY,
        collection_interval: int = 60,
    ):
        self.db_path = Path(db_path)
        self.db_name = db_name
        self.registry = registry
        self.collection_interval = collection_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        
        self._init_metrics()
    
    def _init_metrics(self):
        self.db_file_size = Gauge(
            "sqlite_file_size_bytes",
            "SQLite database file size in bytes",
            ["database"],
            registry=self.registry,
        )
        
        self.db_wal_size = Gauge(
            "sqlite_wal_size_bytes",
            "SQLite WAL file size in bytes",
            ["database"],
            registry=self.registry,
        )
        
        self.db_page_count = Gauge(
            "sqlite_page_count",
            "Number of pages in the database",
            ["database"],
            registry=self.registry,
        )
        
        self.db_page_size = Gauge(
            "sqlite_page_size_bytes",
            "Page size in bytes",
            ["database"],
            registry=self.registry,
        )
        
        self.db_freelist_count = Gauge(
            "sqlite_freelist_count",
            "Number of free pages",
            ["database"],
            registry=self.registry,
        )
        
        self.db_table_count = Gauge(
            "sqlite_table_count",
            "Number of tables in the database",
            ["database"],
            registry=self.registry,
        )
        
        self.db_index_count = Gauge(
            "sqlite_index_count",
            "Number of indexes in the database",
            ["database"],
            registry=self.registry,
        )
        
        self.db_table_rows = Gauge(
            "sqlite_table_row_count",
            "Number of rows in each table",
            ["database", "table"],
            registry=self.registry,
        )
        
        self.db_cache_hit_ratio = Gauge(
            "sqlite_cache_hit_ratio",
            "Cache hit ratio (0-1)",
            ["database"],
            registry=self.registry,
        )
        
        self.db_queries_total = Counter(
            "sqlite_queries_total",
            "Total SQLite queries",
            ["database", "operation"],
            registry=self.registry,
        )
        
        self.db_query_duration = Histogram(
            "sqlite_query_duration_seconds",
            "SQLite query duration in seconds",
            ["database", "operation"],
            buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
            registry=self.registry,
        )
        
        self.db_connections = Gauge(
            "sqlite_connections_active",
            "Number of active SQLite connections",
            ["database"],
            registry=self.registry,
        )
        
        self.db_schema_version = Gauge(
            "sqlite_schema_version",
            "SQLite schema version",
            ["database"],
            registry=self.registry,
        )
        
        self.db_last_collection = Gauge(
            "sqlite_last_collection_timestamp",
            "Timestamp of last metrics collection",
            ["database"],
            registry=self.registry,
        )
    
    def _get_stats_sync(self) -> Optional[SQLiteStats]:
        if not self.db_path.exists():
            logger.warning(f"sqlite_metrics:db_not_found: {self.db_path}")
            return None
        
        try:
            file_size = self.db_path.stat().st_size
            
            wal_path = self.db_path.with_suffix(self.db_path.suffix + "-wal")
            wal_size = wal_path.stat().st_size if wal_path.exists() else 0
            
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                cursor.execute("PRAGMA page_count")
                page_count = cursor.fetchone()[0]
                
                cursor.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]
                
                cursor.execute("PRAGMA freelist_count")
                freelist_count = cursor.fetchone()[0]
                
                cursor.execute("PRAGMA schema_version")
                schema_version = cursor.fetchone()[0]
                
                cursor.execute("PRAGMA cache_stats")
                cache_stats = cursor.fetchone()
                cache_hit_ratio = 0.0
                if cache_stats:
                    hit = cache_stats[0] if cache_stats[0] else 0
                    miss = cache_stats[1] if len(cache_stats) > 1 and cache_stats[1] else 0
                    total = hit + miss
                    cache_hit_ratio = hit / total if total > 0 else 0.0
                
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """)
                tables = [row[0] for row in cursor.fetchall()]
                
                cursor.execute("""
                    SELECT COUNT(*) FROM sqlite_master 
                    WHERE type='index' AND name NOT LIKE 'sqlite_%'
                """)
                index_count = cursor.fetchone()[0]
                
                table_rows = {}
                for table in tables:
                    try:
                        cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                        table_rows[table] = cursor.fetchone()[0]
                    except sqlite3.Error:
                        table_rows[table] = 0
                
                return SQLiteStats(
                    file_size_bytes=file_size,
                    wal_size_bytes=wal_size,
                    page_count=page_count,
                    page_size=page_size,
                    freelist_count=freelist_count,
                    table_count=len(tables),
                    index_count=index_count,
                    tables=table_rows,
                    cache_hit_ratio=cache_hit_ratio,
                    schema_version=schema_version,
                )
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"sqlite_metrics:collection_error: {e}", exc_info=True)
            return None
    
    async def collect_metrics(self) -> Optional[SQLiteStats]:
        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(self._executor, self._get_stats_sync)
        
        if stats is None:
            return None
        
        self.db_file_size.labels(database=self.db_name).set(stats.file_size_bytes)
        self.db_wal_size.labels(database=self.db_name).set(stats.wal_size_bytes)
        self.db_page_count.labels(database=self.db_name).set(stats.page_count)
        self.db_page_size.labels(database=self.db_name).set(stats.page_size)
        self.db_freelist_count.labels(database=self.db_name).set(stats.freelist_count)
        self.db_table_count.labels(database=self.db_name).set(stats.table_count)
        self.db_index_count.labels(database=self.db_name).set(stats.index_count)
        self.db_cache_hit_ratio.labels(database=self.db_name).set(stats.cache_hit_ratio)
        self.db_schema_version.labels(database=self.db_name).set(stats.schema_version)
        self.db_last_collection.labels(database=self.db_name).set(time.time())
        
        for table_name, row_count in stats.tables.items():
            self.db_table_rows.labels(
                database=self.db_name,
                table=table_name,
            ).set(row_count)
        
        logger.debug(
            "sqlite_metrics:collected",
            extra={
                "database": self.db_name,
                "file_size": stats.file_size_bytes,
                "tables": stats.table_count,
            },
        )
        
        return stats
    
    async def start_background_collection(self):
        if self._running:
            logger.warning("sqlite_metrics:already_running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._collection_loop())
        logger.info(f"sqlite_metrics:started (interval={self.collection_interval}s)")
    
    async def stop_background_collection(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._executor.shutdown(wait=False)
        logger.info("sqlite_metrics:stopped")
    
    async def _collection_loop(self):
        while self._running:
            try:
                await self.collect_metrics()
            except Exception as e:
                logger.error(f"sqlite_metrics:loop_error: {e}")
            
            await asyncio.sleep(self.collection_interval)


class ProfiledSQLiteConnection:
    
    def __init__(
        self,
        db_path: str,
        db_name: str = "sqlite",
        registry: CollectorRegistry = REGISTRY,
    ):
        self.db_path = db_path
        self.db_name = db_name
        self.registry = registry
        self._conn: Optional[sqlite3.Connection] = None
        
        try:
            self._queries_total = Counter(
                "sqlite_profiled_queries_total",
                "Total profiled SQLite queries",
                ["database", "operation"],
                registry=registry,
            )
        except ValueError:
            self._queries_total = REGISTRY._names_to_collectors.get(
                "sqlite_profiled_queries_total_total"
            )
        
        try:
            self._query_duration = Histogram(
                "sqlite_profiled_query_duration_seconds",
                "Profiled SQLite query duration",
                ["database", "operation"],
                buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1],
                registry=registry,
            )
        except ValueError:
            self._query_duration = REGISTRY._names_to_collectors.get(
                "sqlite_profiled_query_duration_seconds"
            )
    
    def __enter__(self):
        self._conn = sqlite3.connect(self.db_path)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def execute(self, sql: str, parameters=()) -> sqlite3.Cursor:
        if not self._conn:
            raise RuntimeError("Connection not opened. Use 'with' statement.")
        
        operation = self._classify_operation(sql)
        
        start = time.perf_counter()
        try:
            cursor = self._conn.execute(sql, parameters)
            return cursor
        finally:
            duration = time.perf_counter() - start
            if self._queries_total:
                self._queries_total.labels(
                    database=self.db_name,
                    operation=operation,
                ).inc()
            if self._query_duration:
                self._query_duration.labels(
                    database=self.db_name,
                    operation=operation,
                ).observe(duration)
    
    def executemany(self, sql: str, seq_of_parameters) -> sqlite3.Cursor:
        if not self._conn:
            raise RuntimeError("Connection not opened. Use 'with' statement.")
        
        operation = self._classify_operation(sql)
        
        start = time.perf_counter()
        try:
            cursor = self._conn.executemany(sql, seq_of_parameters)
            return cursor
        finally:
            duration = time.perf_counter() - start
            if self._queries_total:
                self._queries_total.labels(
                    database=self.db_name,
                    operation=operation,
                ).inc(len(list(seq_of_parameters)))
            if self._query_duration:
                self._query_duration.labels(
                    database=self.db_name,
                    operation=operation,
                ).observe(duration)
    
    def commit(self):
        if self._conn:
            self._conn.commit()
    
    def rollback(self):
        if self._conn:
            self._conn.rollback()
    
    @staticmethod
    def _classify_operation(sql: str) -> str:
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("SELECT"):
            return "select"
        elif sql_upper.startswith("INSERT"):
            return "insert"
        elif sql_upper.startswith("UPDATE"):
            return "update"
        elif sql_upper.startswith("DELETE"):
            return "delete"
        elif sql_upper.startswith("CREATE"):
            return "create"
        elif sql_upper.startswith("DROP"):
            return "drop"
        elif sql_upper.startswith("ALTER"):
            return "alter"
        elif sql_upper.startswith("PRAGMA"):
            return "pragma"
        else:
            return "other"


def create_sqlite_collector(
    db_path: str,
    db_name: str = "mem0_history",
    collection_interval: int = 60,
) -> SQLiteMetricsCollector:
    return SQLiteMetricsCollector(
        db_path=db_path,
        db_name=db_name,
        collection_interval=collection_interval,
    )
