
from __future__ import annotations

import logging
import time
from typing import Callable, Optional
from functools import wraps

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Info,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    multiprocess,
    REGISTRY,
)
from fastapi import FastAPI, Request, Response
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ApplicationMetrics:
    
    def __init__(self, registry: CollectorRegistry = REGISTRY):
        self.registry = registry
        
        self.http_requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status_code"],
            registry=registry,
        )
        
        self.http_request_duration_seconds = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            registry=registry,
        )
        
        self.http_requests_in_progress = Gauge(
            "http_requests_in_progress",
            "Number of HTTP requests in progress",
            ["method", "endpoint"],
            registry=registry,
        )
        
        self.llm_requests_total = Counter(
            "llm_requests_total",
            "Total LLM API requests",
            ["agent", "model", "status"],
            registry=registry,
        )
        
        self.llm_tokens_total = Counter(
            "llm_tokens_total",
            "Total tokens used in LLM requests",
            ["agent", "model", "token_type"],
            registry=registry,
        )
        
        self.llm_request_duration_seconds = Histogram(
            "llm_request_duration_seconds",
            "LLM request duration in seconds",
            ["agent", "model"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
            registry=registry,
        )
        
        self.llm_cost_usd = Counter(
            "llm_cost_usd_total",
            "Total cost of LLM requests in USD",
            ["agent", "model"],
            registry=registry,
        )
        
        self.chat_requests_total = Counter(
            "chat_requests_total",
            "Total chat requests",
            ["mode", "language", "status"],
            registry=registry,
        )
        
        self.chat_blocked_total = Counter(
            "chat_blocked_total",
            "Total blocked chat requests (guardrails)",
            ["mode", "reason"],
            registry=registry,
        )
        
        self.chat_response_length = Histogram(
            "chat_response_length_chars",
            "Length of chat responses in characters",
            ["mode"],
            buckets=[10, 25, 50, 100, 200, 500, 1000, 2000],
            registry=registry,
        )
        
        self.memory_operations_total = Counter(
            "memory_operations_total",
            "Total memory operations",
            ["operation", "status"],
            registry=registry,
        )
        
        self.memory_retrieval_duration_seconds = Histogram(
            "memory_retrieval_duration_seconds",
            "Duration of memory retrieval operations",
            ["operation"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
            registry=registry,
        )
        
        self.memory_items_retrieved = Histogram(
            "memory_items_retrieved",
            "Number of memory items retrieved per query",
            buckets=[0, 1, 2, 5, 10, 20, 50, 100],
            registry=registry,
        )
        
        self.scheduler_runs_total = Counter(
            "scheduler_runs_total",
            "Total scheduler runs",
            ["scheduler", "status"],
            registry=registry,
        )
        
        self.scheduler_items_processed = Counter(
            "scheduler_items_processed_total",
            "Total items processed by schedulers",
            ["scheduler"],
            registry=registry,
        )
        
        self.scheduler_last_run_timestamp = Gauge(
            "scheduler_last_run_timestamp",
            "Timestamp of last scheduler run",
            ["scheduler"],
            registry=registry,
        )
        
        self.scheduler_duration_seconds = Histogram(
            "scheduler_duration_seconds",
            "Duration of scheduler runs",
            ["scheduler"],
            buckets=[1, 5, 10, 30, 60, 120, 300, 600],
            registry=registry,
        )
        
        self.db_queries_total = Counter(
            "db_queries_total",
            "Total database queries",
            ["database", "operation"],
            registry=registry,
        )
        
        self.db_query_duration_seconds = Histogram(
            "db_query_duration_seconds",
            "Database query duration in seconds",
            ["database", "operation"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            registry=registry,
        )
        
        self.db_connections_active = Gauge(
            "db_connections_active",
            "Number of active database connections",
            ["database"],
            registry=registry,
        )
        
        self.db_errors_total = Counter(
            "db_errors_total",
            "Total database errors",
            ["database", "error_type"],
            registry=registry,
        )
        
        self.agent_calls_total = Counter(
            "agent_calls_total",
            "Total agent calls",
            ["agent", "operation", "status"],
            registry=registry,
        )
        
        self.agent_duration_seconds = Histogram(
            "agent_duration_seconds",
            "Agent operation duration in seconds",
            ["agent", "operation"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
            registry=registry,
        )
        
        self.app_info = Info(
            "app",
            "Application information",
            registry=registry,
        )


metrics = ApplicationMetrics()


class PrometheusMiddleware(BaseHTTPMiddleware):
    
    def __init__(self, app, metrics: ApplicationMetrics):
        super().__init__(app)
        self.metrics = metrics
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        method = request.method
        path = self._normalize_path(request.url.path)
        
        if path == "/metrics":
            return await call_next(request)
        
        self.metrics.http_requests_in_progress.labels(
            method=method, endpoint=path
        ).inc()
        
        start_time = time.perf_counter()
        status_code = 500
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start_time
            
            self.metrics.http_requests_total.labels(
                method=method, endpoint=path, status_code=status_code
            ).inc()
            
            self.metrics.http_request_duration_seconds.labels(
                method=method, endpoint=path
            ).observe(duration)
            
            self.metrics.http_requests_in_progress.labels(
                method=method, endpoint=path
            ).dec()
    
    @staticmethod
    def _normalize_path(path: str) -> str:
        path = path.rstrip("/") or "/"
        
        import re
        path = re.sub(
            r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "/{uuid}",
            path,
            flags=re.IGNORECASE,
        )
        path = re.sub(r"/\d+", "/{id}", path)
        
        return path


def setup_prometheus_metrics(
    app: FastAPI,
    app_name: str = "joowme-agent",
    app_version: str = "1.0.0",
) -> ApplicationMetrics:
    import os
    
    metrics.app_info.info({
        "name": app_name,
        "version": app_version,
        "environment": os.getenv("APP_ENV", "development"),
    })
    
    app.add_middleware(PrometheusMiddleware, metrics=metrics)
    
    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        return Response(
            content=generate_latest(REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )
    
    logger.info("prometheus_metrics:setup:complete ✓")
    return metrics


def track_llm_call(
    agent: str,
    model: str,
):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                metrics.llm_requests_total.labels(
                    agent=agent, model=model, status=status
                ).inc()
                metrics.llm_request_duration_seconds.labels(
                    agent=agent, model=model
                ).observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            status = "success"
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                metrics.llm_requests_total.labels(
                    agent=agent, model=model, status=status
                ).inc()
                metrics.llm_request_duration_seconds.labels(
                    agent=agent, model=model
                ).observe(duration)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def track_db_query(database: str, operation: str):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                metrics.db_errors_total.labels(
                    database=database,
                    error_type=type(e).__name__,
                ).inc()
                raise
            finally:
                duration = time.perf_counter() - start_time
                metrics.db_queries_total.labels(
                    database=database, operation=operation
                ).inc()
                metrics.db_query_duration_seconds.labels(
                    database=database, operation=operation
                ).observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                metrics.db_errors_total.labels(
                    database=database,
                    error_type=type(e).__name__,
                ).inc()
                raise
            finally:
                duration = time.perf_counter() - start_time
                metrics.db_queries_total.labels(
                    database=database, operation=operation
                ).inc()
                metrics.db_query_duration_seconds.labels(
                    database=database, operation=operation
                ).observe(duration)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def track_agent_operation(agent: str, operation: str):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                metrics.agent_calls_total.labels(
                    agent=agent, operation=operation, status=status
                ).inc()
                metrics.agent_duration_seconds.labels(
                    agent=agent, operation=operation
                ).observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            status = "success"
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                metrics.agent_calls_total.labels(
                    agent=agent, operation=operation, status=status
                ).inc()
                metrics.agent_duration_seconds.labels(
                    agent=agent, operation=operation
                ).observe(duration)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def record_llm_usage(
    agent: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: Optional[float] = None,
):
    metrics.llm_tokens_total.labels(
        agent=agent, model=model, token_type="prompt"
    ).inc(prompt_tokens)
    
    metrics.llm_tokens_total.labels(
        agent=agent, model=model, token_type="completion"
    ).inc(completion_tokens)
    
    if cost_usd is not None:
        metrics.llm_cost_usd.labels(agent=agent, model=model).inc(cost_usd)


def record_scheduler_run(
    scheduler: str,
    status: str,
    items_processed: int,
    duration_seconds: float,
):
    import time
    
    metrics.scheduler_runs_total.labels(
        scheduler=scheduler, status=status
    ).inc()
    
    metrics.scheduler_items_processed.labels(scheduler=scheduler).inc(items_processed)
    
    metrics.scheduler_last_run_timestamp.labels(scheduler=scheduler).set(time.time())
    
    metrics.scheduler_duration_seconds.labels(scheduler=scheduler).observe(duration_seconds)
