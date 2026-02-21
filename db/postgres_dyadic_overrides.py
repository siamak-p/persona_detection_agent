
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

import asyncpg

logger = logging.getLogger(__name__)


VALID_RELATIONSHIP_CLASSES = frozenset([
    "spouse",
    "family",
    "boss",
    "subordinate",
    "colleague",
    "friend",
    "stranger",
])

SYMMETRIC_RELATIONSHIPS = frozenset([
    "spouse", "family", "colleague", "friend", "stranger"
])

ASYMMETRIC_RELATIONSHIP_INVERSE = {
    "boss": "subordinate",
    "subordinate": "boss",
}


@dataclass
class ToneMetrics:
    avg_formality: float = 0.5
    avg_humor: float = 0.3
    profanity_rate: float = 0.0
    directness: float = 0.5
    optimistic_rate: float = 0.5
    pessimistic_rate: float = 0.5
    submissive_rate: float = 0.5
    dominance: float = 0.5
    emotional_dependence_rate: float = 0.5
    style_summary: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "avg_formality": self.avg_formality,
            "avg_humor": self.avg_humor,
            "profanity_rate": self.profanity_rate,
            "directness": self.directness,
            "optimistic_rate": self.optimistic_rate,
            "pessimistic_rate": self.pessimistic_rate,
            "submissive_rate": self.submissive_rate,
            "dominance": self.dominance,
            "emotional_dependence_rate": self.emotional_dependence_rate,
            "style_summary": self.style_summary,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToneMetrics":
        return cls(
            avg_formality=float(data.get("avg_formality", 0.5)),
            avg_humor=float(data.get("avg_humor", 0.3)),
            profanity_rate=float(data.get("profanity_rate", 0.0)),
            directness=float(data.get("directness", 0.5)),
            optimistic_rate=float(data.get("optimistic_rate", 0.5)),
            pessimistic_rate=float(data.get("pessimistic_rate", 0.5)),
            submissive_rate=float(data.get("submissive_rate", 0.5)),
            dominance=float(data.get("dominance", 0.5)),
            emotional_dependence_rate=float(data.get("emotional_dependence_rate", 0.5)),
            style_summary=data.get("style_summary"),
        )


@dataclass
class DyadicRecord:
    id: Optional[int] = None
    source_user_id: str = ""
    target_user_id: str = ""
    relationship_class: Optional[str] = None
    total_message_count: int = 0
    metrics: ToneMetrics = field(default_factory=ToneMetrics)
    created_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None


class DyadicOverrides:

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
    
    async def close(self) -> None:
        pass
    
    async def _require_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def upsert(
        self,
        source_user_id: str,
        target_user_id: str,
        metrics: ToneMetrics,
        relationship_class: Optional[str] = None,
        message_count: int = 0,
    ) -> int:
        pool = await self._require_pool()
        
        if relationship_class and relationship_class not in VALID_RELATIONSHIP_CLASSES:
            logger.warning(
                f"dyadic:upsert:invalid_class:{relationship_class}, using None"
            )
            relationship_class = None
        
        async with pool.acquire() as conn:
            rec_id = await conn.fetchval(
                """
                INSERT INTO dyadic_overrides
                    (source_user_id, target_user_id, relationship_class,
                     total_message_count, avg_formality, avg_humor,
                     profanity_rate, directness, optimistic_rate,
                     pessimistic_rate, submissive_rate, dominance,
                     emotional_dependence_rate, style_summary)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (source_user_id, target_user_id) DO UPDATE
                    SET relationship_class = COALESCE(EXCLUDED.relationship_class, dyadic_overrides.relationship_class),
                        total_message_count = EXCLUDED.total_message_count,
                        avg_formality = EXCLUDED.avg_formality,
                        avg_humor = EXCLUDED.avg_humor,
                        profanity_rate = EXCLUDED.profanity_rate,
                        directness = EXCLUDED.directness,
                        optimistic_rate = EXCLUDED.optimistic_rate,
                        pessimistic_rate = EXCLUDED.pessimistic_rate,
                        submissive_rate = EXCLUDED.submissive_rate,
                        dominance = EXCLUDED.dominance,
                        emotional_dependence_rate = EXCLUDED.emotional_dependence_rate,
                        style_summary = EXCLUDED.style_summary,
                        last_updated_at = NOW()
                RETURNING id
                """,
                source_user_id,
                target_user_id,
                relationship_class,
                message_count,
                metrics.avg_formality,
                metrics.avg_humor,
                metrics.profanity_rate,
                metrics.directness,
                metrics.optimistic_rate,
                metrics.pessimistic_rate,
                metrics.submissive_rate,
                metrics.dominance,
                metrics.emotional_dependence_rate,
                metrics.style_summary,
            )
        
        logger.info(
            f"dyadic:upsert:success:{source_user_id}→{target_user_id}",
            extra={"rec_id": rec_id, "class": relationship_class}
        )
        return int(rec_id)

    async def upsert_pair(
        self,
        user_a_id: str,
        user_b_id: str,
        user_a_metrics: ToneMetrics,
        user_b_metrics: ToneMetrics,
        relationship_class: str,
        message_count: int = 0,
    ) -> tuple[int, int]:
        if relationship_class in SYMMETRIC_RELATIONSHIPS:
            class_a_to_b = relationship_class
            class_b_to_a = relationship_class
        elif relationship_class in ASYMMETRIC_RELATIONSHIP_INVERSE:
            class_a_to_b = relationship_class
            class_b_to_a = ASYMMETRIC_RELATIONSHIP_INVERSE[relationship_class]
        else:
            logger.warning(f"dyadic:upsert_pair:unknown_class:{relationship_class}")
            class_a_to_b = relationship_class
            class_b_to_a = relationship_class
        
        id_a = await self.upsert(
            source_user_id=user_a_id,
            target_user_id=user_b_id,
            metrics=user_a_metrics,
            relationship_class=class_a_to_b,
            message_count=message_count,
        )
        
        id_b = await self.upsert(
            source_user_id=user_b_id,
            target_user_id=user_a_id,
            metrics=user_b_metrics,
            relationship_class=class_b_to_a,
            message_count=message_count,
        )
        
        logger.info(
            f"dyadic:upsert_pair:success:{user_a_id}↔{user_b_id}",
            extra={
                "class_a_to_b": class_a_to_b,
                "class_b_to_a": class_b_to_a,
            }
        )
        
        return (id_a, id_b)

    async def get(
        self,
        source_user_id: str,
        target_user_id: str,
    ) -> Optional[DyadicRecord]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM dyadic_overrides
                WHERE source_user_id = $1 AND target_user_id = $2
                """,
                source_user_id,
                target_user_id,
            )
        
        if not row:
            return None
        
        return DyadicRecord(
            id=row["id"],
            source_user_id=row["source_user_id"],
            target_user_id=row["target_user_id"],
            relationship_class=row["relationship_class"],
            total_message_count=row["total_message_count"],
            metrics=ToneMetrics(
                avg_formality=row["avg_formality"] or 0.5,
                avg_humor=row["avg_humor"] or 0.3,
                profanity_rate=row["profanity_rate"] or 0.0,
                directness=row["directness"] or 0.5,
                optimistic_rate=row["optimistic_rate"] or 0.5,
                pessimistic_rate=row["pessimistic_rate"] or 0.5,
                submissive_rate=row["submissive_rate"] or 0.5,
                dominance=row["dominance"] or 0.5,
                emotional_dependence_rate=row["emotional_dependence_rate"] or 0.5,
                style_summary=row["style_summary"],
            ),
            created_at=row["created_at"],
            last_updated_at=row["last_updated_at"],
        )

    async def get_all_for_user(self, source_user_id: str) -> List[DyadicRecord]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM dyadic_overrides
                WHERE source_user_id = $1
                ORDER BY last_updated_at DESC
                """,
                source_user_id,
            )
        
        return [
            DyadicRecord(
                id=row["id"],
                source_user_id=row["source_user_id"],
                target_user_id=row["target_user_id"],
                relationship_class=row["relationship_class"],
                total_message_count=row["total_message_count"],
                metrics=ToneMetrics(
                    avg_formality=row["avg_formality"] or 0.5,
                    avg_humor=row["avg_humor"] or 0.3,
                    profanity_rate=row["profanity_rate"] or 0.0,
                    directness=row["directness"] or 0.5,
                    optimistic_rate=row["optimistic_rate"] or 0.5,
                    pessimistic_rate=row["pessimistic_rate"] or 0.5,
                    submissive_rate=row["submissive_rate"] or 0.5,
                    dominance=row["dominance"] or 0.5,
                    emotional_dependence_rate=row["emotional_dependence_rate"] or 0.5,
                    style_summary=row["style_summary"],
                ),
                created_at=row["created_at"],
                last_updated_at=row["last_updated_at"],
            )
            for row in rows
        ]

    async def delete(self, source_user_id: str, target_user_id: str) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM dyadic_overrides
                WHERE source_user_id = $1 AND target_user_id = $2
                """,
                source_user_id,
                target_user_id,
            )
        
        return "DELETE 1" in result

    async def exists(self, source_user_id: str, target_user_id: str) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM dyadic_overrides
                WHERE source_user_id = $1 AND target_user_id = $2
                """,
                source_user_id,
                target_user_id,
            )
        
        return (count or 0) > 0

    async def update_relationship_class(
        self,
        source_user_id: str,
        target_user_id: str,
        relationship_class: str,
    ) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE dyadic_overrides
                SET relationship_class = $3, last_updated_at = NOW()
                WHERE source_user_id = $1 AND target_user_id = $2
                """,
                source_user_id,
                target_user_id,
                relationship_class,
            )
        
        updated = "UPDATE 1" in result
        
        if updated:
            logger.info(
                f"dyadic:update_class:{source_user_id}->{target_user_id}={relationship_class}"
            )
        
        return updated
