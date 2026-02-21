
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class PassiveScheduler:

    def __init__(
        self,
        listener_agent: Any,
        passive_memory: Any,
        interval_seconds: int = 7200,
    ):
        self._listener = listener_agent
        self._passive = passive_memory
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            logger.warning("passive_scheduler:already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("passive_scheduler:started", extra={"interval": self._interval})

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("passive_scheduler:stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                
                if not self._running:
                    break
                    
                await self._process_passive_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("passive_scheduler:error", extra={"error": str(e)}, exc_info=True)

    async def _process_passive_batch(self) -> dict[str, Any]:
        logger.info("passive_scheduler:process_batch:start")
        
        stats = {
            "total": 0,
            "processed": 0,
            "errors": 0,
        }

        try:
            observations = await self._passive.get()

            if not observations:
                logger.info("passive_scheduler:no_observations")
                return stats

            stats["total"] = len(observations)
            logger.info(
                "passive_scheduler:processing",
                extra={"count": stats["total"]},
            )

            for obs in observations:
                try:
                    user_id = obs.get("user_id", "")
                    conversation_id = obs.get("conversation_id", "")
                    message_text = obs.get("message", "")
                    message_id = obs.get("message_id", "")
                    
                    if not user_id or not message_text:
                        logger.warning(
                            "passive_scheduler:skip_invalid_observation",
                            extra={"obs": obs},
                        )
                        continue
                    
                    await self._listener.process(
                        memory_owner_id=user_id,
                        partner_user_id=user_id,
                        conversation_id=conversation_id or "passive",
                        message={
                            "text": message_text,
                            "message_id": message_id,
                            "author_id": user_id,
                            "role": "human",
                        },
                        mode="passive",
                    )
                    stats["processed"] += 1
                    
                except Exception as e:
                    logger.error(
                        "passive_scheduler:process_single_error",
                        extra={"obs_id": obs.get("id"), "error": str(e)},
                        exc_info=True,
                    )
                    stats["errors"] += 1

            logger.info(
                "passive_scheduler:process_batch:done",
                extra=stats,
            )

            if stats["processed"] > 0:
                await self._passive.clear()
                logger.info("passive_scheduler:passive_cleared")
            
            return stats

        except Exception as e:
            logger.error(
                "passive_scheduler:process_batch:error", extra={"error": str(e)}, exc_info=True
            )
            stats["errors"] += 1
            return stats
