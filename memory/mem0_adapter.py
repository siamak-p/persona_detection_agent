
from __future__ import annotations

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mem0 import Memory

from config.settings import Settings
from memory.attribute_schema import ATTRIBUTE_SCHEMA

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
EMBEDDING_MODEL_CACHE = PROJECT_ROOT / "embedding_model"
EMBEDDING_MODEL_CACHE.mkdir(exist_ok=True)

os.environ.setdefault("HF_HOME", str(EMBEDDING_MODEL_CACHE))
os.environ.setdefault("TRANSFORMERS_CACHE", str(EMBEDDING_MODEL_CACHE))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(EMBEDDING_MODEL_CACHE))
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def _check_model_exists(model_name: str) -> bool:
    possible_paths = [
        EMBEDDING_MODEL_CACHE / model_name.replace("/", "_"),
        EMBEDDING_MODEL_CACHE / f"sentence-transformers_{model_name.replace('/', '_')}",
        EMBEDDING_MODEL_CACHE / "models--" / model_name.replace("/", "--"),
        EMBEDDING_MODEL_CACHE / "models--BAAI--bge-m3",
        EMBEDDING_MODEL_CACHE / "models--BAAI--bge-m3" / "snapshots",
    ]
    
    for path in possible_paths:
        if path.exists():
            logger.info(f"mem0_adapter:model_found_locally: {path}")
            return True
    
    logger.warning(
        f"mem0_adapter:model_not_found_locally: {model_name}",
        extra={"searched_paths": [str(p) for p in possible_paths]}
    )
    return False


MODEL_EXISTS_LOCALLY = _check_model_exists("BAAI/bge-m3")

if MODEL_EXISTS_LOCALLY:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    logger.info("mem0_adapter:embedding_model:mode=offline (model found locally)")
else:
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    os.environ.pop("HF_DATASETS_OFFLINE", None)
    logger.warning(
        "mem0_adapter:embedding_model:mode=online (model not found, will attempt download)"
    )

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _normalize_digits(value: str) -> str:
    return (value or "").translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)


class Mem0Adapter:

    def __init__(self, settings: Settings) -> None:
        if settings.OPENAI_BASE_URL:
            os.environ["OPENAI_BASE_URL"] = settings.OPENAI_BASE_URL
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY or ""

        cfg = settings.mem0_config
        self._collection_name = (
            (cfg.get("vector_store") or {})
            .get("config", {})
            .get("collection_name", "mem0_memories")
        )

        logger.info(
            "mem0_adapter:init",
            extra={
                "qdrant": (cfg.get("vector_store") or {}).get("config", {}).get("url"),
                "collection": self._collection_name,
                "embedder": (cfg.get("embedder") or {}).get("config", {}).get("model"),
                "history_db": cfg.get("history_db_path"),
            },
        )
        self._memory = Memory.from_config(cfg)

        try:
            self._qdrant_client = self._memory.vector_store.client
            self._embedder = self._memory.embedding_model
            logger.info("mem0_adapter:qdrant_client_acquired")
        except Exception as e:
            logger.warning(f"mem0_adapter:qdrant_client_not_available: {e}")
            self._qdrant_client = None
            self._embedder = None

        self._preload_embedder()

    FIRST_PERSON_EN = re.compile(r"\b(i|i'm|i am|i’ve|i'd|my|me|mine)\b", re.IGNORECASE)
    SECOND_PERSON_EN = re.compile(r"\b(you|you're|you are|your|yours|u)\b", re.IGNORECASE)

    FIRST_PERSON_FA = re.compile(r"(?:^|\s)(من|منم|خودم|دارم|هستم)(?:\s|$)")
    SECOND_PERSON_FA = re.compile(r"(?:^|\s)(تو|شما|تؤ|توو|توئ|شمایی|شمایید)(?:\s|$)")

    @staticmethod
    def _has_first_person(text: str) -> bool:
        t = (text or "").strip()
        return bool(Mem0Adapter.FIRST_PERSON_EN.search(t) or Mem0Adapter.FIRST_PERSON_FA.search(t))

    @staticmethod
    def _has_second_person_reference(text: str) -> bool:
        t = (text or "").strip()
        return bool(
            Mem0Adapter.SECOND_PERSON_EN.search(t) or Mem0Adapter.SECOND_PERSON_FA.search(t)
        )

    @staticmethod
    def _mem0_messages_for_extraction(
        *,
        text: str,
        owner_user_id: str,
        partner_user_id: str,
        mode: str,
    ) -> list[dict]:
        is_creator = (mode == "creator") or (owner_user_id == partner_user_id)

        if is_creator:
            return [
                {
                    "role": "system",
                    "content": (
                        "EXTRACTION CONTEXT\n"
                        f"- MODE=creator\n- OWNER={owner_user_id}\n- SPEAKER=owner\n"
                        "Rules: extract only facts about the OWNER speaking in first person."
                    ),
                },
                {"role": "user", "content": text},
            ]

        return [
            {
                "role": "system",
                "content": (
                    "EXTRACTION CONTEXT\n"
                    f"- MODE=chat\n- OWNER={owner_user_id}\n- SPEAKER=partner ({partner_user_id})\n"
                    "Rules:\n"
                    "1) The following message was authored by the PARTNER, not the OWNER.\n"
                    "2) Ignore first-person claims ('I', 'I'm', 'من', 'هستم') about the partner.\n"
                    "3) Only extract facts about the OWNER if the partner explicitly refers to them "
                    "in second person ('you/تو/شما') or by the owner's name.\n"
                    "4) If no OWNER-directed facts exist, extract nothing."
                ),
            },
            {
                "role": "user",
                "content": f"[from partner {partner_user_id} → owner {owner_user_id}]\n{text}",
            },
        ]

    async def add_user_message(
        self,
        owner_user_id: str,
        partner_user_id: str,
        conversation_id: str,
        text: str,
        message_id: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        if not (text or "").strip():
            return {"success": False, "error": "empty"}

        mode = mode or "chat"
        author = "owner" if (mode == "creator" or owner_user_id == partner_user_id) else "partner"

        scope = "profile" if mode == "creator" else "pair"

        meta = {
            "to_user_id": partner_user_id,
            "conversation_id": conversation_id,
            "mode": mode,
            "message_id": message_id or "",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "scope": scope,
            "visibility": "private",
            "author": author,
        }

        if (
            mode == "chat"
            and author == "partner"
            and self._has_first_person(text)
            and not self._has_second_person_reference(text)
        ):
            meta.update(
                {
                    "type": "event",
                    "event_reason": "partner_first_person_no_second_person",
                }
            )
            return self._memory.add(
                messages=[
                    {
                        "role": "system",
                        "content": "[event-only] partner self-talk (skipping profile extraction)",
                    }
                ],
                user_id=owner_user_id,
                metadata=meta,
            )

        messages = self._mem0_messages_for_extraction(
            text=text,
            owner_user_id=owner_user_id,
            partner_user_id=partner_user_id,
            mode=mode,
        )


        return self._memory.add(
            messages=messages,
            user_id=owner_user_id,
            metadata=meta,
        )

    async def add_summary(
        self,
        owner_user_id: str,
        partner_user_id: str,
        conversation_id: str,
        summary: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not (summary or "").strip():
            return {"success": False, "error": "empty"}

        if not self._qdrant_client or not self._embedder:
            logger.error("mem0_adapter:add_summary:qdrant_not_available")
            return {"success": False, "error": "qdrant_not_available"}

        try:
            import hashlib

            summary_id = hashlib.md5(
                f"{owner_user_id}:{partner_user_id}:{conversation_id}".encode()
            ).hexdigest()

            embedding = self._embedder.embed(summary)
            if isinstance(embedding, list) and len(embedding) > 0:
                embedding_vector = embedding[0] if isinstance(embedding[0], list) else embedding
            else:
                embedding_vector = embedding

            payload = {
                "type": "summary",
                "user_id": owner_user_id,
                "to_user_id": partner_user_id,
                "conversation_id": conversation_id,
                "data": summary,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "scope": "pair",
                "visibility": "private",
                "hash": summary_id,
            }
            
            if extra_metadata:
                payload["extra"] = extra_metadata
                if "high_priority_facts" in extra_metadata:
                    payload["core_facts"] = (
                        extra_metadata.get("high_priority_facts", []) + 
                        extra_metadata.get("medium_priority_facts", [])
                    )

            from qdrant_client.models import PointStruct

            self._qdrant_client.upsert(
                collection_name=self._collection_name,
                points=[
                    PointStruct(
                        id=summary_id,
                        vector=embedding_vector,
                        payload=payload,
                    )
                ],
            )

            logger.info(
                "mem0_adapter:add_summary:direct_upsert_success",
                extra={
                    "owner": owner_user_id,
                    "partner": partner_user_id,
                    "conv": conversation_id,
                    "id": summary_id,
                    "has_core_facts": bool(extra_metadata and extra_metadata.get("high_priority_facts")),
                },
            )
            return {"success": True, "id": summary_id}

        except Exception as e:
            logger.error(
                "mem0_adapter:add_summary:failed",
                extra={"error": str(e)},
                exc_info=True,
            )
            return {"success": False, "error": str(e)}

    async def get_memories(
        self,
        owner_user_id: str,
        *,
        query: str | None = None,
        limit: int = 200,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            payload = {"user_id": owner_user_id, "limit": limit}
            raw = (
                self._memory.search(query=query, **payload)
                if query
                else self._memory.get_all(**payload)
            )
            results: list[dict[str, Any]] = (raw or {}).get("results", [])
            if metadata:
                filt: list[dict[str, Any]] = []
                for m in results:
                    md = (m.get("metadata") or {}) if isinstance(m, dict) else {}
                    if all(md.get(k) == v for k, v in metadata.items()):
                        filt.append(m)
                results = filt
            return results
        except Exception as e:
            logger.error(
                "mem0_adapter:get_memories:error",
                extra={"user": owner_user_id, "e": str(e)},
                exc_info=True,
            )
            return []

    async def get_creator_memories(
        self, owner_user_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return await self.get_memories(owner_user_id, limit=limit, metadata={"mode": "creator"})

    
    BASIC_IDENTITY_FIELDS = {
        "name", "age", "job_title", "current_location", "skills",
        "employer", "education_level", "major", "university",
    }
    
    BASIC_IDENTITY_KEYWORDS_FA = [
        "نام", "اسم", "سن", "سال", "شغل", "کار", "شهر", "محل زندگی",
        "مهارت", "شرکت", "تحصیلات", "رشته", "دانشگاه",
    ]
    BASIC_IDENTITY_KEYWORDS_EN = [
        "name", "age", "years old", "job", "work", "city", "live",
        "skill", "company", "education", "major", "university",
    ]

    async def get_basic_identity_facts(
        self, owner_user_id: str, limit: int = 20
    ) -> list[str]:
        all_memories = await self.get_creator_memories(owner_user_id, limit=limit)
        
        filtered_facts: list[str] = []
        for mem in all_memories:
            memory_text = mem.get("memory", "")
            if not memory_text:
                continue
            
            text_lower = memory_text.lower()
            is_basic_identity = False
            
            for keyword in self.BASIC_IDENTITY_KEYWORDS_FA:
                if keyword in memory_text:
                    is_basic_identity = True
                    break
            
            if not is_basic_identity:
                for keyword in self.BASIC_IDENTITY_KEYWORDS_EN:
                    if keyword in text_lower:
                        is_basic_identity = True
                        break
            
            if is_basic_identity:
                filtered_facts.append(memory_text)
        
        return filtered_facts

    async def get_all_facts_for_spouse(
        self, owner_user_id: str, limit: int = 50
    ) -> list[str]:
        all_memories = await self.get_creator_memories(owner_user_id, limit=limit)
        return [mem.get("memory", "") for mem in all_memories if mem.get("memory")]

    async def delete_memory(self, owner_user_id: str, memory_id: str) -> bool:
        try:
            self._memory.delete(memory_id=memory_id)
            logger.info(
                "mem0_adapter:delete_memory", extra={"owner": owner_user_id, "memory_id": memory_id}
            )
            return True
        except Exception as e:
            logger.error(
                "mem0_adapter:delete_memory:error",
                extra={"id": memory_id, "e": str(e)},
                exc_info=True,
            )
            return False

    async def delete_all_memories(self, owner_user_id: str) -> bool:
        try:
            self._memory.delete_all(user_id=owner_user_id)
            return True
        except Exception as e:
            logger.error(
                "mem0_adapter:delete_all:error",
                extra={"owner": owner_user_id, "e": str(e)},
                exc_info=True,
            )
            return False

    async def get_summary(
        self,
        owner_user_id: str,
        partner_user_id: str,
        conversation_id: str,
    ) -> str | None:
        if not self._qdrant_client:
            logger.error("mem0_adapter:get_summary:qdrant_not_available")
            return None

        try:
            import hashlib

            summary_id = hashlib.md5(
                f"{owner_user_id}:{partner_user_id}:{conversation_id}".encode()
            ).hexdigest()

            from qdrant_client.models import Filter, FieldCondition, MatchValue

            results = self._qdrant_client.retrieve(
                collection_name=self._collection_name,
                ids=[summary_id],
                with_payload=True,
            )

            if results and len(results) > 0:
                payload = results[0].payload
                summary_text = payload.get("data", "").strip()
                logger.info(
                    "mem0_adapter:get_summary:found",
                    extra={
                        "owner": owner_user_id,
                        "partner": partner_user_id,
                        "conv": conversation_id,
                    },
                )
                return summary_text if summary_text else None

            logger.info(
                "mem0_adapter:get_summary:not_found",
                extra={"owner": owner_user_id, "partner": partner_user_id, "conv": conversation_id},
            )
            return None

        except Exception as e:
            logger.error(
                "mem0_adapter:get_summary:failed",
                extra={"error": str(e)},
                exc_info=True,
            )
            return None

    async def get_conversation_context(
        self,
        *,
        owner_user_id: str,
        partner_user_id: str | None,
        conversation_id: str | None,
        query: str | None = None,
    ) -> dict[str, Any]:
        profile = await self._profile_snapshot(owner_user_id)

        if not profile and partner_user_id:
            profile = await self._profile_snapshot(partner_user_id)

        summary_text: str | None = None
        if partner_user_id and conversation_id:
            summary_text = await self.get_summary(owner_user_id, partner_user_id, conversation_id)

        return {
            "profile_facts": profile,
            "conversation_summary": summary_text,
            "query": query or "",
        }


    def _preload_embedder(self) -> None:
        if not self._embedder:
            logger.warning("mem0_adapter:preload:embedder_not_available")
            return

        try:
            logger.info("mem0_adapter:preload:starting", extra={"model_exists_locally": MODEL_EXISTS_LOCALLY})
            
            dummy_text = "test embedding preload"
            _ = self._embedder.embed(dummy_text)
            
            logger.info("mem0_adapter:preload:success ✓")
            
            if not MODEL_EXISTS_LOCALLY:
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                os.environ["HF_DATASETS_OFFLINE"] = "1"
                logger.info("mem0_adapter:preload:switched_to_offline_mode (model downloaded successfully)")
                
        except Exception as e:
            logger.error(
                "mem0_adapter:preload:failed",
                extra={"error": str(e), "model_exists_locally": MODEL_EXISTS_LOCALLY},
                exc_info=True,
            )
            if MODEL_EXISTS_LOCALLY:
                logger.error(
                    "mem0_adapter:preload:local_model_load_failed - check model cache integrity",
                    extra={"cache_path": str(EMBEDDING_MODEL_CACHE)}
                )

    async def _profile_snapshot(self, owner_user_id: str) -> list[str]:
        all_mems = await self.get_memories(owner_user_id, limit=1000)
        if not all_mems:
            return []

        facts: list[tuple[str, str, str]] = []
        attr_keys = set(ATTRIBUTE_SCHEMA.keys())
        item_alias_map = {
            (v.get("item_alias") or "").strip(): k for k, v in ATTRIBUTE_SCHEMA.items() if v.get("item_alias")
        }
        pattern = re.compile(r"^(?P<k>[^:]+):\s*(?P<v>.+)$")

        def _timestamp(m: dict) -> str:
            return m.get("updated_at") or m.get("created_at") or ""

        for m in all_mems:
            text = (m.get("memory") or "").strip()
            if not text:
                continue
            mt = pattern.match(text)
            if not mt:
                continue
            key = mt.group("k").strip()
            val = mt.group("v").strip()
            if key not in attr_keys:
                mapped = item_alias_map.get(key)
                if mapped:
                    key = mapped
                else:
                    continue
            facts.append((key, val, _timestamp(m)))

        facts.sort(key=lambda x: x[2], reverse=True)

        singles: dict[str, str] = {}
        multis: dict[str, list[str]] = {}
        single_keys = {k for k, v in ATTRIBUTE_SCHEMA.items() if v.get("cardinality") == "one"}
        multi_keys = {k for k, v in ATTRIBUTE_SCHEMA.items() if v.get("cardinality") == "many"}

        for k, v, _ in facts:
            if k in single_keys and k not in singles:
                if k == "age":
                    try:
                        v = str(max(0, min(120, int(_normalize_digits(v)))))
                    except Exception:
                        pass
                singles[k] = v
            elif k in multi_keys:
                arr = multis.setdefault(k, [])
                if v not in arr:
                    arr.append(v)

        ordered: list[str] = []
        for key in [
            "name",
            "age",
            "gender",
            "current_location",
            "job_title",
            "employer",
            "education_level",
            "highest_degree",
            "major",
            "university",
            "nationality",
            "native_language",
            "preferred_language",
            "timezone",
        ]:
            if key in singles:
                ordered.append(f"{key}: {singles[key]}")

        for key in sorted(multis.keys()):
            for val in multis[key][:10]:
                ordered.append(f"{key[:-1] if key.endswith('s') else key}: {val}")

        return ordered[:40]
