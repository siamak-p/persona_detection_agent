"""Unit tests for summarizer/core_fact_extractor.py — data classes & helpers."""

from __future__ import annotations

import pytest

from summarizer.core_fact_extractor import (
    FactPriority,
    FactCategory,
    CATEGORY_TO_PRIORITY,
    ExtractedFact,
    ExtractionResult,
    merge_facts,
    facts_to_text,
)


# ──────────── Enums ──────────────────────────────────────────────


class TestEnums:
    def test_fact_priority_values(self):
        assert FactPriority.HIGH == "high"
        assert FactPriority.MEDIUM == "medium"
        assert FactPriority.LOW == "low"

    def test_fact_category_values(self):
        assert FactCategory.IDENTITY == "identity"
        assert FactCategory.LOCATION == "location"
        assert FactCategory.OCCUPATION == "occupation"
        assert FactCategory.FAMILY == "family"
        assert FactCategory.PREFERENCE == "preference"
        assert FactCategory.MOOD == "mood"

    def test_all_categories_have_priority_mapping(self):
        for cat in FactCategory:
            assert cat in CATEGORY_TO_PRIORITY, f"{cat} missing from CATEGORY_TO_PRIORITY"


class TestCategoryPriorityMapping:
    def test_identity_is_high(self):
        assert CATEGORY_TO_PRIORITY[FactCategory.IDENTITY] == FactPriority.HIGH

    def test_location_is_high(self):
        assert CATEGORY_TO_PRIORITY[FactCategory.LOCATION] == FactPriority.HIGH

    def test_preference_is_medium(self):
        assert CATEGORY_TO_PRIORITY[FactCategory.PREFERENCE] == FactPriority.MEDIUM

    def test_mood_is_low(self):
        assert CATEGORY_TO_PRIORITY[FactCategory.MOOD] == FactPriority.LOW

    def test_event_is_low(self):
        assert CATEGORY_TO_PRIORITY[FactCategory.EVENT] == FactPriority.LOW


# ──────────── ExtractedFact ──────────────────────────────────────


class TestExtractedFact:
    def test_creation(self):
        f = ExtractedFact(
            category="identity",
            priority="high",
            subject="owner",
            key="name",
            value="سیامک",
        )
        assert f.category == "identity"
        assert f.confidence == 0.9  # default
        assert f.source_user == ""  # default

    def test_to_dict(self):
        f = ExtractedFact(
            category="location",
            priority="high",
            subject="owner",
            key="city",
            value="Tehran",
            confidence=0.95,
            source_user="u1",
        )
        d = f.to_dict()
        assert d["category"] == "location"
        assert d["priority"] == "high"
        assert d["subject"] == "owner"
        assert d["key"] == "city"
        assert d["value"] == "Tehran"
        assert d["confidence"] == 0.95
        assert d["source_user"] == "u1"


# ──────────── ExtractionResult ───────────────────────────────────


class TestExtractionResult:
    def _make_fact(self, key, priority):
        return ExtractedFact(
            category="identity",
            priority=priority,
            subject="owner",
            key=key,
            value="test",
        )

    def test_all_facts_combines_all(self):
        r = ExtractionResult(
            high_priority=[self._make_fact("a", "high")],
            medium_priority=[self._make_fact("b", "medium")],
            low_priority=[self._make_fact("c", "low"), self._make_fact("d", "low")],
        )
        assert len(r.all_facts) == 4

    def test_all_facts_empty(self):
        r = ExtractionResult()
        assert r.all_facts == []

    def test_to_dict(self):
        f = self._make_fact("name", "high")
        r = ExtractionResult(
            high_priority=[f],
            clean_summary="Owner is named test",
        )
        d = r.to_dict()
        assert len(d["high_priority"]) == 1
        assert d["clean_summary"] == "Owner is named test"
        assert d["medium_priority"] == []
        assert d["low_priority"] == []


# ──────────── merge_facts ────────────────────────────────────────


class TestMergeFacts:
    def _fact(self, category, subject, key, value, confidence=0.9):
        return ExtractedFact(
            category=category,
            priority="high",
            subject=subject,
            key=key,
            value=value,
            confidence=confidence,
        )

    def test_merge_no_overlap(self):
        existing = [self._fact("identity", "owner", "name", "Ali")]
        new = [self._fact("location", "owner", "city", "Tehran")]
        result = merge_facts(existing, new)
        assert len(result) == 2

    def test_merge_with_overlap_updates(self):
        existing = [self._fact("identity", "owner", "name", "Ali", confidence=0.8)]
        new = [self._fact("identity", "owner", "name", "سیامک", confidence=0.95)]
        result = merge_facts(existing, new)
        assert len(result) == 1
        assert result[0].value == "سیامک"
        assert result[0].confidence == 0.95

    def test_merge_lower_confidence_does_not_override(self):
        existing = [self._fact("identity", "owner", "name", "سیامک", confidence=0.95)]
        new = [self._fact("identity", "owner", "name", "Ali", confidence=0.5)]
        result = merge_facts(existing, new)
        assert len(result) == 1
        # Lower confidence does NOT replace (>= check means equal replaces)
        assert result[0].value == "سیامک"

    def test_merge_empty_existing(self):
        new = [self._fact("identity", "owner", "name", "Ali")]
        result = merge_facts([], new)
        assert len(result) == 1
        assert result[0].value == "Ali"

    def test_merge_empty_new(self):
        existing = [self._fact("identity", "owner", "name", "Ali")]
        result = merge_facts(existing, [])
        assert len(result) == 1

    def test_merge_both_empty(self):
        result = merge_facts([], [])
        assert result == []


# ──────────── facts_to_text ──────────────────────────────────────


class TestFactsToText:
    def _fact(self, key, value, priority="high"):
        return ExtractedFact(
            category="identity",
            priority=priority,
            subject="owner",
            key=key,
            value=value,
        )

    def test_empty_list(self):
        assert facts_to_text([]) == ""

    def test_single_fact(self):
        result = facts_to_text([self._fact("name", "Ali")])
        assert result == "name: Ali"

    def test_multiple_facts_joined(self):
        facts = [self._fact("name", "Ali"), self._fact("city", "Tehran")]
        result = facts_to_text(facts)
        assert " | " in result
        assert "name: Ali" in result
        assert "city: Tehran" in result

    def test_with_priority(self):
        facts = [self._fact("name", "Ali", "high")]
        result = facts_to_text(facts, include_priority=True)
        assert "[HIGH]" in result
        assert "name: Ali" in result

    def test_without_priority(self):
        facts = [self._fact("name", "Ali", "high")]
        result = facts_to_text(facts, include_priority=False)
        assert "[HIGH]" not in result
