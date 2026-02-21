
from __future__ import annotations

import logging
import os
from typing import Optional, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_tracer: Optional[Any] = None
_initialized: bool = False


def init_phoenix_tracing(
    service_name: str = "joowme-agent",
    phoenix_endpoint: str = "http://localhost:4317",
    enable_openai: bool = True,
    enable_openai_agents: bool = True,
) -> bool:
    global _tracer, _initialized
    
    if _initialized:
        logger.warning("Phoenix tracing already initialized")
        return True
    
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        
        logger.info(
            "phoenix_setup:init:starting",
            extra={"service_name": service_name, "endpoint": phoenix_endpoint},
        )
        
        resource = Resource.create({
            SERVICE_NAME: service_name,
            "service.version": "1.0.0",
            "deployment.environment": os.getenv("APP_ENV", "development"),
        })
        
        provider = TracerProvider(resource=resource)
        
        otlp_exporter = OTLPSpanExporter(
            endpoint=phoenix_endpoint,
            insecure=True,
        )
        
        processor = BatchSpanProcessor(
            otlp_exporter,
            max_queue_size=2048,
            max_export_batch_size=512,
            schedule_delay_millis=5000,
        )
        provider.add_span_processor(processor)
        
        trace.set_tracer_provider(provider)
        
        _tracer = trace.get_tracer(__name__)
        
        if enable_openai:
            try:
                from openinference.instrumentation.openai import OpenAIInstrumentor
                OpenAIInstrumentor().instrument()
                logger.info("phoenix_setup:init:openai_instrumented ✓")
            except ImportError as e:
                logger.warning(f"phoenix_setup:init:openai_instrumentation_failed: {e}")
            except Exception as e:
                logger.error(f"phoenix_setup:init:openai_instrumentation_error: {e}")
        
        if enable_openai_agents:
            try:
                from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
                OpenAIAgentsInstrumentor().instrument()
                logger.info("phoenix_setup:init:openai_agents_instrumented ✓")
            except ImportError as e:
                logger.warning(f"phoenix_setup:init:openai_agents_instrumentation_failed: {e}")
            except Exception as e:
                logger.error(f"phoenix_setup:init:openai_agents_instrumentation_error: {e}")
        
        _initialized = True
        logger.info("phoenix_setup:init:complete ✓")
        return True
        
    except ImportError as e:
        logger.error(f"phoenix_setup:init:import_error: {e}")
        logger.error("Please install: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-openai openinference-instrumentation-openai-agents")
        return False
    except Exception as e:
        logger.error(f"phoenix_setup:init:failed: {e}", exc_info=True)
        return False


def get_tracer():
    return _tracer


@contextmanager
def trace_span(
    name: str,
    attributes: Optional[dict] = None,
):
    if _tracer is None:
        yield None
        return
    
    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


def trace_llm_call(
    agent_name: str,
    operation: str,
    model: Optional[str] = None,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
):
    def decorator(func):
        import functools
        import asyncio
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            attributes = {
                "agent.name": agent_name,
                "agent.operation": operation,
            }
            if model:
                attributes["llm.model"] = model
            if user_id:
                attributes["user.id"] = user_id
            if conversation_id:
                attributes["conversation.id"] = conversation_id
            
            with trace_span(f"{agent_name}.{operation}", attributes) as span:
                try:
                    result = await func(*args, **kwargs)
                    if span:
                        span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    if span:
                        span.set_attribute("status", "error")
                        span.set_attribute("error.message", str(e))
                        span.record_exception(e)
                    raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            attributes = {
                "agent.name": agent_name,
                "agent.operation": operation,
            }
            if model:
                attributes["llm.model"] = model
            if user_id:
                attributes["user.id"] = user_id
            if conversation_id:
                attributes["conversation.id"] = conversation_id
            
            with trace_span(f"{agent_name}.{operation}", attributes) as span:
                try:
                    result = func(*args, **kwargs)
                    if span:
                        span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    if span:
                        span.set_attribute("status", "error")
                        span.set_attribute("error.message", str(e))
                        span.record_exception(e)
                    raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def add_span_attributes(**attributes):
    from opentelemetry import trace
    
    span = trace.get_current_span()
    if span:
        for key, value in attributes.items():
            span.set_attribute(key, value)


def record_llm_tokens(
    agent_name: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: Optional[int] = None,
    input_messages: Optional[list] = None,
    output_message: Optional[str] = None,
):
    global _tracer
    
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
    
    import json
    
    input_value = ""
    if input_messages:
        try:
            for msg in reversed(input_messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    input_value = str(msg.get("content", ""))[:2000]
                    break
        except Exception:
            pass
    
    output_value = output_message[:2000] if output_message else ""
    
    from opentelemetry import trace
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.set_attribute("llm.token_count.prompt", prompt_tokens)
        current_span.set_attribute("llm.token_count.completion", completion_tokens)
        current_span.set_attribute("llm.token_count.total", total_tokens)
        current_span.set_attribute("llm.model_name", model)
        current_span.set_attribute("agent.name", agent_name)
        if input_value:
            current_span.set_attribute("input.value", input_value)
        if output_value:
            current_span.set_attribute("output.value", output_value)
    
    if _tracer is not None:
        with _tracer.start_as_current_span(f"llm.{agent_name}") as span:
            span.set_attribute("openinference.span.kind", "LLM")
            span.set_attribute("llm.model_name", model)
            span.set_attribute("llm.token_count.prompt", prompt_tokens)
            span.set_attribute("llm.token_count.completion", completion_tokens)
            span.set_attribute("llm.token_count.total", total_tokens)
            span.set_attribute("llm.invocation_parameters", json.dumps({"model": model}))
            span.set_attribute("agent.name", agent_name)
            
            if input_value:
                span.set_attribute("input.value", input_value)
            if output_value:
                span.set_attribute("output.value", output_value)
            
            if input_messages:
                try:
                    messages_list = []
                    for msg in input_messages:
                        if isinstance(msg, dict):
                            messages_list.append({
                                "role": str(msg.get("role", "")),
                                "content": str(msg.get("content", ""))[:500],
                            })
                    span.set_attribute("llm.input_messages", json.dumps(messages_list, ensure_ascii=False))
                except Exception as e:
                    logger.warning(f"phoenix:record_tokens:serialize_error:{e}")
    
    logger.debug(
        "phoenix:record_tokens",
        extra={
            "agent": agent_name,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "has_input": bool(input_value),
            "has_output": bool(output_value),
        }
    )


def record_exception(exception: Exception, attributes: Optional[dict] = None):
    from opentelemetry import trace
    
    span = trace.get_current_span()
    if span:
        span.record_exception(exception)
        span.set_attribute("error", True)
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)


def shutdown_tracing():
    global _initialized, _tracer
    
    if not _initialized:
        return
    
    try:
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        if hasattr(provider, 'shutdown'):
            provider.shutdown()
        logger.info("phoenix_setup:shutdown:complete")
    except Exception as e:
        logger.error(f"phoenix_setup:shutdown:error: {e}")
    finally:
        _initialized = False
        _tracer = None
