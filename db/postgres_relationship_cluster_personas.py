
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

import asyncpg

from .postgres_dyadic_overrides import (
    ToneMetrics,
    VALID_RELATIONSHIP_CLASSES,
    SYMMETRIC_RELATIONSHIPS,
    ASYMMETRIC_RELATIONSHIP_INVERSE,
)

logger = logging.getLogger(__name__)


@dataclass
class MemberWithConfidence:
    user_id: str
    confidence: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {"user_id": self.user_id, "confidence": self.confidence}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemberWithConfidence":
        return cls(
            user_id=data.get("user_id", ""),
            confidence=data.get("confidence", 0.5),
        )


@dataclass
class RelationshipClusterRecord:
    id: Optional[int] = None
    user_id: str = ""
    cluster_name: str = ""
    members: List[MemberWithConfidence] = field(default_factory=list)
    total_message_count: int = 0
    metrics: ToneMetrics = field(default_factory=ToneMetrics)
    created_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    
    def get_member_ids(self) -> List[str]:
        return [m.user_id for m in self.members]
    
    def get_member_confidence(self, member_user_id: str) -> Optional[float]:
        for m in self.members:
            if m.user_id == member_user_id:
                return m.confidence
        return None


class RelationshipClusterPersonas:

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
    
    async def close(self) -> None:
        pass
    
    async def _require_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def upsert(
        self,
        user_id: str,
        cluster_name: str,
        metrics: ToneMetrics,
        members: Optional[List[MemberWithConfidence]] = None,
        message_count: int = 0,
    ) -> int:
        pool = await self._require_pool()
        
        if cluster_name not in VALID_RELATIONSHIP_CLASSES:
            raise ValueError(
                f"Invalid cluster_name: {cluster_name}. "
                f"Valid values: {VALID_RELATIONSHIP_CLASSES}"
            )
        
        safe_metrics = ToneMetrics(
            avg_formality=metrics.avg_formality,
            avg_humor=metrics.avg_humor,
            profanity_rate=0.0,
            directness=metrics.directness,
            optimistic_rate=metrics.optimistic_rate,
            pessimistic_rate=metrics.pessimistic_rate,
            submissive_rate=metrics.submissive_rate,
            dominance=metrics.dominance,
            emotional_dependence_rate=metrics.emotional_dependence_rate,
            style_summary=metrics.style_summary,
        )
        
        members_jsonb = json.dumps(
            [m.to_dict() for m in (members or [])],
            ensure_ascii=False,
        )
        
        async with pool.acquire() as conn:
            rec_id = await conn.fetchval(
                """
                INSERT INTO relationship_cluster_personas
                    (user_id, cluster_name, members, total_message_count,
                     avg_formality, avg_humor, profanity_rate, directness,
                     optimistic_rate, pessimistic_rate, submissive_rate,
                     dominance, emotional_dependence_rate, style_summary)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (user_id, cluster_name) DO UPDATE
                    SET members = EXCLUDED.members,
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
                user_id,
                cluster_name,
                members_jsonb,
                message_count,
                safe_metrics.avg_formality,
                safe_metrics.avg_humor,
                safe_metrics.profanity_rate,
                safe_metrics.directness,
                safe_metrics.optimistic_rate,
                safe_metrics.pessimistic_rate,
                safe_metrics.submissive_rate,
                safe_metrics.dominance,
                safe_metrics.emotional_dependence_rate,
                safe_metrics.style_summary,
            )
        
        logger.info(
            f"relationship_cluster:upsert:success:{user_id}:{cluster_name}",
            extra={"rec_id": rec_id, "members": [m.user_id for m in (members or [])]}
        )
        return int(rec_id)

    async def add_member_to_cluster(
        self,
        user_id: str,
        cluster_name: str,
        member_user_id: str,
        confidence: float = 0.5,
    ) -> bool:
        pool = await self._require_pool()
        
        new_member = {"user_id": member_user_id, "confidence": confidence}
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                other_clusters = await conn.fetch(
                    """
                    SELECT cluster_name, members
                    FROM relationship_cluster_personas
                    WHERE user_id = $1 AND cluster_name != $2
                    """,
                    user_id,
                    cluster_name,
                )
                for row in other_clusters:
                    members = row["members"] if isinstance(row["members"], list) else json.loads(row["members"] or "[]")
                    new_members = [m for m in members if m.get("user_id") != member_user_id]
                    if len(new_members) != len(members):
                        await conn.execute(
                            """
                            UPDATE relationship_cluster_personas
                            SET members = $3::jsonb, last_updated_at = NOW()
                            WHERE user_id = $1 AND cluster_name = $2
                            """,
                            user_id,
                            row["cluster_name"],
                            json.dumps(new_members, ensure_ascii=False),
                        )
                
                exists = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM relationship_cluster_personas
                    WHERE user_id = $1 AND cluster_name = $2
                    """,
                    user_id,
                    cluster_name,
                )
                
                if not exists:
                    await conn.execute(
                        """
                        INSERT INTO relationship_cluster_personas
                            (user_id, cluster_name, members)
                        VALUES ($1, $2, $3::jsonb)
                        """,
                        user_id,
                        cluster_name,
                        json.dumps([new_member], ensure_ascii=False),
                    )
                    return True
                
                current_members = await conn.fetchval(
                    """
                    SELECT members FROM relationship_cluster_personas
                    WHERE user_id = $1 AND cluster_name = $2
                    """,
                    user_id,
                    cluster_name,
                )
                
                if current_members:
                    members_list = json.loads(current_members) if isinstance(current_members, str) else current_members
                    for i, m in enumerate(members_list):
                        if m.get("user_id") == member_user_id:
                            members_list[i]["confidence"] = confidence
                            await conn.execute(
                                """
                                UPDATE relationship_cluster_personas
                                SET members = $3::jsonb, last_updated_at = NOW()
                                WHERE user_id = $1 AND cluster_name = $2
                                """,
                                user_id,
                                cluster_name,
                                json.dumps(members_list, ensure_ascii=False),
                            )
                            return True
                    
                    members_list.append(new_member)
                else:
                    members_list = [new_member]
                
                await conn.execute(
                    """
                    UPDATE relationship_cluster_personas
                    SET members = $3::jsonb, last_updated_at = NOW()
                    WHERE user_id = $1 AND cluster_name = $2
                    """,
                    user_id,
                    cluster_name,
                    json.dumps(members_list, ensure_ascii=False),
                )
                
                return True

    async def add_member_pair(
        self,
        user_a_id: str,
        user_b_id: str,
        relationship_class: str,
    ) -> tuple[bool, bool]:
        if relationship_class in SYMMETRIC_RELATIONSHIPS:
            cluster_for_a = relationship_class
            cluster_for_b = relationship_class
        elif relationship_class in ASYMMETRIC_RELATIONSHIP_INVERSE:
            cluster_for_a = ASYMMETRIC_RELATIONSHIP_INVERSE[relationship_class]
            cluster_for_b = relationship_class
        else:
            logger.warning(f"rel_cluster:add_member_pair:unknown_class:{relationship_class}")
            cluster_for_a = relationship_class
            cluster_for_b = relationship_class
        
        result_a = await self.add_member_to_cluster(
            user_id=user_a_id,
            cluster_name=cluster_for_a,
            member_user_id=user_b_id,
        )
        
        result_b = await self.add_member_to_cluster(
            user_id=user_b_id,
            cluster_name=cluster_for_b,
            member_user_id=user_a_id,
        )
        
        logger.info(
            f"rel_cluster:add_member_pair:{user_a_id}↔{user_b_id}",
            extra={
                "cluster_for_a": cluster_for_a,
                "cluster_for_b": cluster_for_b,
                "result_a": result_a,
                "result_b": result_b,
            }
        )
        
        return (result_a, result_b)

    async def get(
        self,
        user_id: str,
        cluster_name: str,
    ) -> Optional[RelationshipClusterRecord]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM relationship_cluster_personas
                WHERE user_id = $1 AND cluster_name = $2
                """,
                user_id,
                cluster_name,
            )
        
        if not row:
            return None
        
        members_data = row["members"] or []
        if isinstance(members_data, str):
            members_data = json.loads(members_data)
        members = [MemberWithConfidence.from_dict(m) for m in members_data]
        
        return RelationshipClusterRecord(
            id=row["id"],
            user_id=row["user_id"],
            cluster_name=row["cluster_name"],
            members=members,
            total_message_count=row["total_message_count"],
            metrics=ToneMetrics(
                avg_formality=row["avg_formality"] or 0.5,
                avg_humor=row["avg_humor"] or 0.3,
                profanity_rate=0.0,
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

    async def get_all_for_user(self, user_id: str) -> List[RelationshipClusterRecord]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM relationship_cluster_personas
                WHERE user_id = $1
                ORDER BY cluster_name
                """,
                user_id,
            )
        
        results = []
        for row in rows:
            members_data = row["members"] or []
            if isinstance(members_data, str):
                members_data = json.loads(members_data)
            members = [MemberWithConfidence.from_dict(m) for m in members_data]
            
            results.append(RelationshipClusterRecord(
                id=row["id"],
                user_id=row["user_id"],
                cluster_name=row["cluster_name"],
                members=members,
                total_message_count=row["total_message_count"],
                metrics=ToneMetrics(
                    avg_formality=row["avg_formality"] or 0.5,
                    avg_humor=row["avg_humor"] or 0.3,
                    profanity_rate=0.0,
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
            ))
        
        return results

    async def find_cluster_for_member(
        self,
        user_id: str,
        member_user_id: str,
    ) -> Optional[str]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT cluster_name FROM relationship_cluster_personas
                WHERE user_id = $1
                  AND members @> $2::jsonb
                """,
                user_id,
                json.dumps([{"user_id": member_user_id}]),
            )
        
        return row["cluster_name"] if row else None

    async def find_cluster_with_confidence(
        self,
        user_id: str,
        member_user_id: str,
    ) -> tuple[Optional[str], float]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT cluster_name, members
                FROM relationship_cluster_personas
                WHERE user_id = $1
                """,
                user_id,
            )
        
        for row in rows:
            cluster_name = row["cluster_name"]
            members = row["members"] if isinstance(row["members"], list) else json.loads(row["members"] or "[]")
            for m in members:
                if m.get("user_id") == member_user_id:
                    confidence = m.get("confidence", 0.5)
                    return (cluster_name, confidence)
        
        return (None, 0.0)

    async def delete_cluster(self, user_id: str, cluster_name: str) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM relationship_cluster_personas
                WHERE user_id = $1 AND cluster_name = $2
                """,
                user_id,
                cluster_name,
            )
        
        return "DELETE 1" in result

    async def remove_member_from_cluster(
        self,
        user_id: str,
        cluster_name: str,
        member_user_id: str,
    ) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            current_members = await conn.fetchval(
                """
                SELECT members FROM relationship_cluster_personas
                WHERE user_id = $1 AND cluster_name = $2
                """,
                user_id,
                cluster_name,
            )
            
            if not current_members:
                return False
            
            members_list = current_members if isinstance(current_members, list) else json.loads(current_members)
            new_members = [m for m in members_list if m.get("user_id") != member_user_id]
            
            result = await conn.execute(
                """
                UPDATE relationship_cluster_personas
                SET members = $3::jsonb, last_updated_at = NOW()
                WHERE user_id = $1 AND cluster_name = $2
                """,
                user_id,
                cluster_name,
                json.dumps(new_members, ensure_ascii=False),
            )
        
        return "UPDATE" in result

    async def move_member_to_cluster(
        self,
        user_id: str,
        member_user_id: str,
        from_cluster: str,
        to_cluster: str,
        confidence: float = 0.5,
    ) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                from_members = await conn.fetchval(
                    "SELECT members FROM relationship_cluster_personas WHERE user_id = $1 AND cluster_name = $2",
                    user_id, from_cluster,
                )
                if from_members:
                    from_list = from_members if isinstance(from_members, list) else json.loads(from_members)
                    new_from = [m for m in from_list if m.get("user_id") != member_user_id]
                    await conn.execute(
                        "UPDATE relationship_cluster_personas SET members = $3::jsonb, last_updated_at = NOW() WHERE user_id = $1 AND cluster_name = $2",
                        user_id, from_cluster, json.dumps(new_from, ensure_ascii=False),
                    )
                
                to_members = await conn.fetchval(
                    "SELECT members FROM relationship_cluster_personas WHERE user_id = $1 AND cluster_name = $2",
                    user_id, to_cluster,
                )
                
                new_member = {"user_id": member_user_id, "confidence": confidence}
                
                if to_members:
                    to_list = to_members if isinstance(to_members, list) else json.loads(to_members)
                    found = False
                    for m in to_list:
                        if m.get("user_id") == member_user_id:
                            m["confidence"] = confidence
                            found = True
                            break
                    if not found:
                        to_list.append(new_member)
                    await conn.execute(
                        "UPDATE relationship_cluster_personas SET members = $3::jsonb, last_updated_at = NOW() WHERE user_id = $1 AND cluster_name = $2",
                        user_id, to_cluster, json.dumps(to_list, ensure_ascii=False),
                    )
                else:
                    await conn.execute(
                        "INSERT INTO relationship_cluster_personas (user_id, cluster_name, members) VALUES ($1, $2, $3::jsonb)",
                        user_id, to_cluster, json.dumps([new_member], ensure_ascii=False),
                    )
        
        logger.info(
            f"rel_cluster:move_member:{user_id}:{member_user_id}:"
            f"{from_cluster}->{to_cluster} (confidence={confidence})"
        )
        return True

    async def update_relationship_for_pair(
        self,
        user_a_id: str,
        user_b_id: str,
        relationship_class: str,
        confidence: float = 0.5,
    ) -> tuple[bool, bool]:
        pool = await self._require_pool()
        
        if relationship_class in SYMMETRIC_RELATIONSHIPS:
            cluster_for_a = relationship_class
            cluster_for_b = relationship_class
        elif relationship_class in ASYMMETRIC_RELATIONSHIP_INVERSE:
            cluster_for_a = ASYMMETRIC_RELATIONSHIP_INVERSE[relationship_class]
            cluster_for_b = relationship_class
        else:
            logger.warning(f"rel_cluster:update_pair:unknown_class:{relationship_class}")
            cluster_for_a = relationship_class
            cluster_for_b = relationship_class
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows_a = await conn.fetch(
                    "SELECT cluster_name, members FROM relationship_cluster_personas WHERE user_id = $1 AND cluster_name != $2",
                    user_a_id, cluster_for_a,
                )
                for row in rows_a:
                    members = row["members"] if isinstance(row["members"], list) else json.loads(row["members"] or "[]")
                    new_members = [m for m in members if m.get("user_id") != user_b_id]
                    if len(new_members) != len(members):
                        await conn.execute(
                            "UPDATE relationship_cluster_personas SET members = $3::jsonb, last_updated_at = NOW() WHERE user_id = $1 AND cluster_name = $2",
                            user_a_id, row["cluster_name"], json.dumps(new_members, ensure_ascii=False),
                        )
                
                rows_b = await conn.fetch(
                    "SELECT cluster_name, members FROM relationship_cluster_personas WHERE user_id = $1 AND cluster_name != $2",
                    user_b_id, cluster_for_b,
                )
                for row in rows_b:
                    members = row["members"] if isinstance(row["members"], list) else json.loads(row["members"] or "[]")
                    new_members = [m for m in members if m.get("user_id") != user_a_id]
                    if len(new_members) != len(members):
                        await conn.execute(
                            "UPDATE relationship_cluster_personas SET members = $3::jsonb, last_updated_at = NOW() WHERE user_id = $1 AND cluster_name = $2",
                            user_b_id, row["cluster_name"], json.dumps(new_members, ensure_ascii=False),
                        )
                
                await self._upsert_member_in_transaction(
                    conn, user_a_id, cluster_for_a, user_b_id, confidence
                )
                
                await self._upsert_member_in_transaction(
                    conn, user_b_id, cluster_for_b, user_a_id, confidence
                )
        
        logger.info(
            f"rel_cluster:update_pair:{user_a_id}↔{user_b_id}:"
            f"rel={relationship_class}, confidence={confidence}, "
            f"A.{cluster_for_a}←B, B.{cluster_for_b}←A"
        )
        
        return (True, True)
    
    async def _upsert_member_in_transaction(
        self,
        conn: asyncpg.Connection,
        user_id: str,
        cluster_name: str,
        member_user_id: str,
        confidence: float,
    ) -> None:
        current = await conn.fetchval(
            "SELECT members FROM relationship_cluster_personas WHERE user_id = $1 AND cluster_name = $2",
            user_id, cluster_name,
        )
        
        new_member = {"user_id": member_user_id, "confidence": confidence}
        
        if current is not None:
            members = current if isinstance(current, list) else json.loads(current or "[]")
            found = False
            for m in members:
                if m.get("user_id") == member_user_id:
                    m["confidence"] = confidence
                    found = True
                    break
            if not found:
                members.append(new_member)
            await conn.execute(
                "UPDATE relationship_cluster_personas SET members = $3::jsonb, last_updated_at = NOW() WHERE user_id = $1 AND cluster_name = $2",
                user_id, cluster_name, json.dumps(members, ensure_ascii=False),
            )
        else:
            await conn.execute(
                "INSERT INTO relationship_cluster_personas (user_id, cluster_name, members) VALUES ($1, $2, $3::jsonb)",
                user_id, cluster_name, json.dumps([new_member], ensure_ascii=False),
            )

    async def get_users_with_cluster(self, cluster_name: str) -> List[str]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT user_id FROM relationship_cluster_personas
                WHERE cluster_name = $1
                """,
                cluster_name,
            )
        
        return [row["user_id"] for row in rows]

    async def get_cluster_members(
        self,
        user_id: str,
        cluster_name: str,
    ) -> List[str]:
        record = await self.get(user_id, cluster_name)
        if not record:
            return []
        return record.get_member_ids()
    
    async def get_cluster_members_with_confidence(
        self,
        user_id: str,
        cluster_name: str,
    ) -> List[MemberWithConfidence]:
        record = await self.get(user_id, cluster_name)
        if not record:
            return []
        return record.members
    
    async def get_member_confidence(
        self,
        user_id: str,
        member_user_id: str,
    ) -> Optional[float]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT cluster_name, members
                FROM relationship_cluster_personas
                WHERE user_id = $1
                """,
                user_id,
            )
        
        for row in rows:
            members = row["members"] if isinstance(row["members"], list) else json.loads(row["members"] or "[]")
            for m in members:
                if m.get("user_id") == member_user_id:
                    return m.get("confidence", 0.5)
        
        return None

    async def get_users_with_low_confidence_members(
        self,
        threshold: float = 0.6,
    ) -> List[str]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT user_id
                FROM relationship_cluster_personas,
                     jsonb_array_elements(members) AS member
                WHERE (member->>'confidence')::float < $1
                """,
                threshold,
            )
        
        return [row["user_id"] for row in rows]

    async def get_all_members_below_confidence(
        self,
        user_id: str,
        threshold: float = 0.6,
    ) -> List[Dict[str, Any]]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT cluster_name, members
                FROM relationship_cluster_personas
                WHERE user_id = $1
                """,
                user_id,
            )
        
        result = []
        for row in rows:
            cluster_name = row["cluster_name"]
            members = row["members"] if isinstance(row["members"], list) else json.loads(row["members"] or "[]")
            
            for m in members:
                confidence = m.get("confidence", 0.5)
                if confidence < threshold:
                    result.append({
                        "member_user_id": m.get("user_id"),
                        "cluster_name": cluster_name,
                        "confidence": confidence,
                    })
        
        return result
