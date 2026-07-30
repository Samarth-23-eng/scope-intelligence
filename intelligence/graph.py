from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from psycopg2.extras import Json

from db.postgres import get_connection
from intelligence.foundation import json_safe, parse_timestamp


LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "llp",
    "ltd",
    "plc",
    "pvt",
    "private",
    "technologies",
    "technology",
}

SOURCE_RELIABILITY = {
    "first_party_website": 0.95,
    "page_snapshot": 0.92,
    "github_release": 0.92,
    "github_profile": 0.9,
    "github_repository": 0.86,
    "company_filing": 0.96,
    "government": 0.96,
    "news_article": 0.78,
    "rss": 0.76,
    "job_posting": 0.74,
    "youtube_video": 0.72,
    "youtube_transcript": 0.72,
    "youtube_comments": 0.45,
    "social_post": 0.6,
    "unknown": 0.55,
}


@dataclass(frozen=True)
class EvidenceSignal:
    evidence_id: int | None
    stance: str
    source_type: str
    source_key: str
    confidence: float
    observed_at: datetime


class RelationshipIntelligenceEngine:
    """Fuse graph evidence into reproducible confidence and graph-level metrics."""

    def __init__(self, competitor_id: int, run_id: int | None = None):
        self.competitor_id = competitor_id
        self.run_id = run_id

    @staticmethod
    def normalize_entity_name(name: str) -> str:
        words = re.findall(r"[a-z0-9]+", (name or "").casefold())
        while words and words[-1] in LEGAL_SUFFIXES:
            words.pop()
        return "".join(words)

    @classmethod
    def aliases_for(cls, name: str) -> list[tuple[str, str, float]]:
        cleaned = re.sub(r"\s+", " ", (name or "").strip())
        if not cleaned:
            return []
        normalized = cls.normalize_entity_name(cleaned)
        aliases: list[tuple[str, str, float]] = []
        if normalized:
            aliases.append((cleaned, "canonical", 1.0))
            stripped_words = [
                word
                for word in re.findall(r"[A-Za-z0-9]+", cleaned)
                if word.casefold() not in LEGAL_SUFFIXES
            ]
            stripped = " ".join(stripped_words)
            if stripped and stripped.casefold() != cleaned.casefold():
                aliases.append((stripped, "legal_suffix_removed", 0.94))
            if len(stripped_words) >= 2:
                acronym = "".join(word[0] for word in stripped_words).upper()
                if 2 <= len(acronym) <= 10:
                    aliases.append((acronym, "acronym", 0.78))
        unique: dict[str, tuple[str, str, float]] = {}
        for alias, alias_type, confidence in aliases:
            key = re.sub(r"[^a-z0-9]+", "", alias.casefold())
            if key and key not in unique:
                unique[key] = (alias, alias_type, confidence)
        return list(unique.values())

    @staticmethod
    def source_identity(source_url: str, metadata: dict[str, Any]) -> tuple[str, str]:
        source_type = str(metadata.get("source_type") or "unknown").casefold()
        host = (urlsplit(source_url or "").hostname or "unknown").casefold()
        host = host.removeprefix("www.")
        return source_type, host

    @staticmethod
    def _confidence_union(values: Iterable[float]) -> float:
        remaining = 1.0
        for value in values:
            remaining *= 1.0 - min(max(value, 0.0), 0.99)
        return round(1.0 - remaining, 4)

    @classmethod
    def score_relationship(
        cls,
        model_weight: float,
        signals: list[EvidenceSignal],
        *,
        last_seen_at: datetime | str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        supports = [signal for signal in signals if signal.stance == "supports"]
        contradicts = [signal for signal in signals if signal.stance == "contradicts"]
        support_values = [
            signal.confidence
            * SOURCE_RELIABILITY.get(signal.source_type, SOURCE_RELIABILITY["unknown"])
            for signal in supports
        ]
        contradiction_values = [
            signal.confidence
            * SOURCE_RELIABILITY.get(signal.source_type, SOURCE_RELIABILITY["unknown"])
            for signal in contradicts
        ]
        corroboration = cls._confidence_union(support_values)
        contradiction_score = cls._confidence_union(contradiction_values)
        source_diversity = len({signal.source_key for signal in supports})

        dates = [signal.observed_at for signal in signals if signal.observed_at]
        fallback = (
            last_seen_at
            if isinstance(last_seen_at, datetime)
            else parse_timestamp(last_seen_at)
        )
        latest = max(dates) if dates else fallback or current
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        age_days = max((current - latest).total_seconds() / 86400, 0)
        freshness = round(max(0.15, 0.5 ** (age_days / 180)), 4)

        if supports:
            combined = (
                min(max(model_weight, 0.0), 1.0) * 0.35
                + corroboration * 0.55
                + min(source_diversity, 3) * 0.04
            )
        else:
            combined = min(max(model_weight, 0.0), 1.0) * 0.35
        combined *= 0.7 + freshness * 0.3
        combined *= 1.0 - contradiction_score * 0.65
        final_confidence = round(min(max(combined, 0.0), 0.99), 4)

        disputed = bool(contradicts and contradiction_score >= 0.45)
        if disputed and contradiction_score >= 0.7:
            risk_level = "critical"
        elif not supports or final_confidence < 0.5:
            risk_level = "high"
        elif source_diversity < 2 or final_confidence < 0.72:
            risk_level = "medium"
        else:
            risk_level = "low"
        status = "disputed" if disputed else ("stale" if freshness < 0.5 else "active")
        return {
            "weight": final_confidence,
            "corroboration_score": corroboration,
            "source_diversity": source_diversity,
            "freshness_score": freshness,
            "contradiction_count": len(contradicts),
            "contradiction_score": contradiction_score,
            "risk_level": risk_level,
            "status": status,
            "support_count": len(supports),
        }

    @staticmethod
    def graph_metrics(
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> dict[str, Any]:
        node_ids = {int(entity["id"]) for entity in entities}
        adjacency: dict[int, set[int]] = {node_id: set() for node_id in node_ids}
        weighted_degree: dict[int, float] = {node_id: 0.0 for node_id in node_ids}
        for relationship in relationships:
            source = int(relationship["source_entity_id"])
            target = int(relationship["target_entity_id"])
            if source not in node_ids or target not in node_ids:
                continue
            adjacency[source].add(target)
            adjacency[target].add(source)
            weight = float(relationship.get("weight") or 0)
            weighted_degree[source] += weight
            weighted_degree[target] += weight

        components: list[list[int]] = []
        remaining = set(node_ids)
        while remaining:
            start = next(iter(remaining))
            queue = deque([start])
            component: list[int] = []
            remaining.remove(start)
            while queue:
                node = queue.popleft()
                component.append(node)
                for neighbor in adjacency[node]:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        queue.append(neighbor)
            components.append(component)

        page_rank = {node_id: 1.0 / max(len(node_ids), 1) for node_id in node_ids}
        damping = 0.85
        for _ in range(25):
            next_rank = {
                node_id: (1.0 - damping) / max(len(node_ids), 1)
                for node_id in node_ids
            }
            dangling = sum(
                page_rank[node_id] for node_id in node_ids if not adjacency[node_id]
            )
            for node_id in node_ids:
                next_rank[node_id] += damping * dangling / max(len(node_ids), 1)
            for source in node_ids:
                if not adjacency[source]:
                    continue
                share = damping * page_rank[source] / len(adjacency[source])
                for target in adjacency[source]:
                    next_rank[target] += share
            page_rank = next_rank

        entity_by_id = {int(entity["id"]): entity for entity in entities}
        ranked = sorted(
            node_ids,
            key=lambda node_id: (
                page_rank.get(node_id, 0),
                weighted_degree.get(node_id, 0),
            ),
            reverse=True,
        )
        strategic_nodes = [
            {
                "entity_id": node_id,
                "name": entity_by_id[node_id]["name"],
                "entity_type": entity_by_id[node_id]["entity_type"],
                "degree": len(adjacency[node_id]),
                "weighted_degree": round(weighted_degree[node_id], 4),
                "page_rank": round(page_rank.get(node_id, 0), 6),
            }
            for node_id in ranked[:10]
        ]
        return {
            "component_count": len(components),
            "largest_component": max((len(component) for component in components), default=0),
            "isolated_entities": sum(1 for node_id in node_ids if not adjacency[node_id]),
            "strategic_nodes": strategic_nodes,
        }

    def analyze(self) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, domain FROM competitors WHERE id = %s",
                    (self.competitor_id,),
                )
                competitor = cur.fetchone()
                if not competitor:
                    raise ValueError("Competitor not found")
                cur.execute(
                    """
                    SELECT id, competitor_id, name, entity_type, metadata,
                           created_at, updated_at
                    FROM entities
                    WHERE competitor_id = %s
                    ORDER BY id
                    """,
                    (self.competitor_id,),
                )
                entities = cur.fetchall() or []
                cur.execute(
                    """
                    SELECT relationship.*
                    FROM relationships relationship
                    JOIN entities source ON source.id = relationship.source_entity_id
                    JOIN entities target ON target.id = relationship.target_entity_id
                    WHERE source.competitor_id = %s AND target.competitor_id = %s
                    ORDER BY relationship.id
                    """,
                    (self.competitor_id, self.competitor_id),
                )
                relationships = cur.fetchall() or []
                relationship_ids = [int(row["id"]) for row in relationships]
                evidence_by_relationship: dict[int, list[dict[str, Any]]] = defaultdict(list)
                if relationship_ids:
                    cur.execute(
                        """
                        SELECT relationship_evidence.relationship_id,
                               evidence.id AS evidence_id,
                               evidence.source_url,
                               evidence.confidence AS evidence_confidence,
                               relationship_evidence.confidence AS link_confidence,
                               evidence.metadata,
                               evidence.collected_at
                        FROM relationship_evidence
                        JOIN evidence ON evidence.id = relationship_evidence.evidence_id
                        WHERE relationship_evidence.relationship_id = ANY(%s)
                        ORDER BY evidence.collected_at DESC
                        """,
                        (relationship_ids,),
                    )
                    for row in cur.fetchall() or []:
                        evidence_by_relationship[int(row["relationship_id"])].append(row)

                alias_index: dict[str, set[int]] = defaultdict(set)
                alias_count = 0
                for entity in entities:
                    canonical_key = self.normalize_entity_name(entity["name"])
                    cur.execute(
                        "UPDATE entities SET canonical_key = %s WHERE id = %s",
                        (canonical_key[:500], entity["id"]),
                    )
                    for alias, alias_type, confidence in self.aliases_for(entity["name"]):
                        normalized_alias = re.sub(
                            r"[^a-z0-9]+",
                            "",
                            alias.casefold(),
                        )[:500]
                        if not normalized_alias:
                            continue
                        cur.execute(
                            """
                            INSERT INTO entity_aliases (
                                competitor_id, entity_id, alias, normalized_alias,
                                alias_type, confidence
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (competitor_id, entity_id, normalized_alias)
                            DO UPDATE SET
                                alias = EXCLUDED.alias,
                                alias_type = EXCLUDED.alias_type,
                                confidence = GREATEST(
                                    entity_aliases.confidence,
                                    EXCLUDED.confidence
                                )
                            """,
                            (
                                self.competitor_id,
                                entity["id"],
                                alias[:500],
                                normalized_alias,
                                alias_type,
                                confidence,
                            ),
                        )
                        alias_count += 1
                        if confidence >= 0.9:
                            alias_index[normalized_alias].add(int(entity["id"]))

                analyzed_relationships: list[dict[str, Any]] = []
                for relationship in relationships:
                    relationship_metadata = relationship.get("metadata") or {}
                    extraction_confidence = float(
                        relationship_metadata.get("extraction_confidence")
                        or relationship.get("weight")
                        or 0
                    )
                    signals: list[EvidenceSignal] = []
                    for evidence in evidence_by_relationship[int(relationship["id"])]:
                        metadata = evidence.get("metadata") or {}
                        source_type, source_key = self.source_identity(
                            evidence.get("source_url") or "",
                            metadata,
                        )
                        stance = str(metadata.get("stance") or "supports").casefold()
                        if stance not in {"supports", "contradicts", "context"}:
                            stance = "supports"
                        confidence = min(
                            float(evidence.get("evidence_confidence") or 0.5),
                            float(evidence.get("link_confidence") or 0.5),
                        )
                        observed_at = (
                            evidence.get("collected_at")
                            if isinstance(evidence.get("collected_at"), datetime)
                            else parse_timestamp(evidence.get("collected_at"))
                        ) or datetime.now(timezone.utc)
                        signal = EvidenceSignal(
                            evidence_id=int(evidence["evidence_id"]),
                            stance=stance,
                            source_type=source_type,
                            source_key=source_key,
                            confidence=confidence,
                            observed_at=observed_at,
                        )
                        signals.append(signal)
                        cur.execute(
                            """
                            INSERT INTO relationship_observations (
                                competitor_id, relationship_id, evidence_id, stance,
                                source_type, source_key, confidence, observed_at,
                                metadata
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (
                                self.competitor_id,
                                relationship["id"],
                                signal.evidence_id,
                                signal.stance,
                                signal.source_type[:100],
                                signal.source_key[:500],
                                signal.confidence,
                                signal.observed_at,
                                Json({"fusion_version": 1}),
                            ),
                        )

                    score = self.score_relationship(
                        extraction_confidence,
                        signals,
                        last_seen_at=relationship.get("last_seen_at"),
                    )
                    cur.execute(
                        """
                        UPDATE relationships
                        SET weight = %s,
                            corroboration_score = %s,
                            source_diversity = %s,
                            freshness_score = %s,
                            contradiction_count = %s,
                            risk_level = %s,
                            status = %s,
                            metadata = metadata || %s
                        WHERE id = %s
                        """,
                        (
                            score["weight"],
                            score["corroboration_score"],
                            score["source_diversity"],
                            score["freshness_score"],
                            score["contradiction_count"],
                            score["risk_level"],
                            score["status"],
                            Json(
                                {
                                    "fusion_version": 1,
                                    "extraction_confidence": extraction_confidence,
                                    "contradiction_score": score["contradiction_score"],
                                    "support_count": score["support_count"],
                                }
                            ),
                            relationship["id"],
                        ),
                    )
                    analyzed_relationships.append({**relationship, **score})

                metrics = self.graph_metrics(entities, analyzed_relationships)
                duplicate_candidates = [
                    {
                        "normalized_alias": alias,
                        "entity_ids": sorted(entity_ids),
                        "entity_names": [
                            entity["name"]
                            for entity in entities
                            if int(entity["id"]) in entity_ids
                        ],
                    }
                    for alias, entity_ids in alias_index.items()
                    if len(entity_ids) > 1
                ]
                weak_relationships = sum(
                    1
                    for relationship in analyzed_relationships
                    if relationship["risk_level"] in {"high", "critical"}
                    or relationship["source_diversity"] < 2
                    or relationship["corroboration_score"] < 0.65
                )
                disputed_relationships = sum(
                    1
                    for relationship in analyzed_relationships
                    if relationship["status"] == "disputed"
                )
                metrics.update(
                    {
                        "duplicate_candidates": duplicate_candidates[:25],
                        "risk_distribution": {
                            level: sum(
                                1
                                for relationship in analyzed_relationships
                                if relationship["risk_level"] == level
                            )
                            for level in ("low", "medium", "high", "critical")
                        },
                        "alias_count": alias_count,
                    }
                )
                cur.execute(
                    """
                    INSERT INTO graph_snapshots (
                        competitor_id, pipeline_run_id, entity_count,
                        relationship_count, component_count,
                        disputed_relationships, weak_relationships, metrics
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, created_at
                    """,
                    (
                        self.competitor_id,
                        self.run_id,
                        len(entities),
                        len(analyzed_relationships),
                        metrics["component_count"],
                        disputed_relationships,
                        weak_relationships,
                        Json(json_safe(metrics)),
                    ),
                )
                snapshot = cur.fetchone()
                snapshot_id = int(snapshot["id"])
                if entities:
                    cur.executemany(
                        """
                        INSERT INTO graph_snapshot_entities (
                            snapshot_id, entity_id, name, entity_type, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (snapshot_id, entity_id) DO NOTHING
                        """,
                        [
                            (
                                snapshot_id,
                                int(entity["id"]),
                                entity["name"],
                                entity["entity_type"],
                                Json(json_safe(entity.get("metadata") or {})),
                            )
                            for entity in entities
                        ],
                    )
                if analyzed_relationships:
                    cur.executemany(
                        """
                        INSERT INTO graph_snapshot_relationships (
                            snapshot_id, relationship_id,
                            source_entity_id, target_entity_id,
                            relationship_type, weight, status, risk_level,
                            evidence_count, source_diversity, freshness_score,
                            contradiction_count, first_seen_at, last_seen_at,
                            metadata
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (snapshot_id, relationship_id) DO NOTHING
                        """,
                        [
                            (
                                snapshot_id,
                                int(relationship["id"]),
                                int(relationship["source_entity_id"]),
                                int(relationship["target_entity_id"]),
                                relationship["relationship_type"],
                                float(relationship.get("weight") or 0),
                                relationship.get("status") or "active",
                                relationship.get("risk_level") or "unassessed",
                                int(relationship.get("evidence_count") or 0),
                                int(relationship.get("source_diversity") or 0),
                                float(relationship.get("freshness_score") or 0),
                                int(relationship.get("contradiction_count") or 0),
                                relationship.get("first_seen_at"),
                                relationship.get("last_seen_at"),
                                Json(json_safe(relationship.get("metadata") or {})),
                            )
                            for relationship in analyzed_relationships
                        ],
                    )
                conn.commit()

        return {
            "snapshot_id": snapshot_id,
            "competitor_id": self.competitor_id,
            "entity_count": len(entities),
            "relationship_count": len(analyzed_relationships),
            "component_count": metrics["component_count"],
            "disputed_relationships": disputed_relationships,
            "weak_relationships": weak_relationships,
            "metrics": metrics,
            "created_at": snapshot["created_at"].isoformat(),
        }

    def latest(self) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id AS snapshot_id, competitor_id, entity_count,
                           relationship_count, component_count,
                           disputed_relationships, weak_relationships,
                           metrics, created_at
                    FROM graph_snapshots
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (self.competitor_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        result = dict(row)
        result["created_at"] = result["created_at"].isoformat()
        return result
