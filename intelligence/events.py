"""Fuse verified intelligence into a reproducible event timeline."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg2.extras import Json

from db.postgres import get_connection
from intelligence.foundation import json_safe, parse_timestamp
from intelligence.verification import confidence_union


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "in", "is", "its", "of", "on", "or", "that", "the", "their", "to",
    "was", "were", "will", "with",
}

MONTH_NAMES = (
    "january|february|march|april|may|june|july|august|"
    "september|october|november|december"
)
NON_EVENT_PATTERNS = (
    "no publicly verifiable",
    "no independently verified",
    "insufficient to make",
    "insufficient evidence",
    "evidence provides no",
)


@dataclass
class EventObservation:
    source_kind: str
    source_id: int
    event_type: str
    statement: str
    confidence: float
    verification_status: str
    impact_level: str
    occurred_at: datetime
    source_count: int
    evidence_id: int | None = None
    metadata: dict[str, Any] | None = None


class EventFusionEngine:
    """Cluster high-signal observations and calculate temporal correlations."""

    IMPACT_TYPES = {
        "acquisition": "critical",
        "merger": "critical",
        "funding": "high",
        "investment": "high",
        "leadership": "high",
        "partnership": "high",
        "product": "high",
        "risk": "high",
        "expansion": "high",
        "hiring": "medium",
        "technology": "medium",
        "business_move": "medium",
        "strategic_signal": "medium",
    }
    IMPACT_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    STATUS_RANK = {
        "proposed": 0,
        "stale": 1,
        "supported": 2,
        "confirmed": 3,
        "disputed": 4,
    }

    def __init__(self, competitor_id: int):
        self.competitor_id = competitor_id

    @staticmethod
    def tokens(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", (value or "").casefold())
            if len(token) > 2 and token not in STOP_WORDS
        }

    @classmethod
    def similarity(cls, left: str, right: str) -> float:
        a = cls.tokens(left)
        b = cls.tokens(right)
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    @classmethod
    def correlation_score(
        cls,
        left: str,
        right: str,
        *,
        same_type: bool,
        days_apart: int,
        ignored_tokens: set[str] | None = None,
    ) -> tuple[float, float]:
        ignored = ignored_tokens or set()
        a = cls.tokens(left) - ignored
        b = cls.tokens(right) - ignored
        if not a or not b:
            return 0.0, 0.0
        overlap = len(a & b) / len(a | b)
        temporal_proximity = max(0.0, 1 - (days_apart / 365))
        score = (
            overlap * 0.85
            + (0.1 if same_type else 0.0)
            + temporal_proximity * 0.05
        )
        return min(round(score, 4), 0.99), overlap

    @classmethod
    def normalize_type(cls, value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", (value or "event").casefold())
        aliases = {
            "product_launch": "product",
            "product_update": "product",
            "partnership_announcement": "partnership",
            "executive_change": "leadership",
            "job_growth": "hiring",
            "website": "business_move",
            "pricing": "product",
            "integration": "partnership",
        }
        return aliases.get(normalized, normalized)[:100]

    @classmethod
    def infer_type(cls, declared_type: str, statement: str) -> str:
        text = (statement or "").casefold()
        rules = (
            ("acquisition", r"\b(acquir(?:e|ed|es|ing)|acquisition)\b"),
            ("merger", r"\b(merger|merged|merge with)\b"),
            ("leadership", r"\b(appoint(?:ed|ment)|named .{0,30}\b(?:chief|ceo|cfo|cto|president))\b"),
            ("funding", r"\b(raised|funding round|series [a-f]|venture funding)\b"),
            ("partnership", r"\b(partner(?:ed|ship| program)|alliance|collaboration)\b"),
            ("product", r"\b(launch(?:ed|es)|release(?:d|s)|introduced|unveiled)\b"),
            ("expansion", r"\b(expand(?:ed|s|ing)|opened .{0,40}\b(?:office|hub|center|facility))\b"),
            ("hiring", r"\b(hiring|recruit(?:ing|ment)|headcount|job openings?)\b"),
            ("risk", r"\b(breach|lawsuit|investigation|sanction|outage|vulnerability)\b"),
            ("technology", r"\b(technology|cloud|artificial intelligence|machine learning)\b"),
        )
        for event_type, pattern in rules:
            if re.search(pattern, text):
                return event_type
        return cls.normalize_type(declared_type)

    @staticmethod
    def claim_date(
        statement: str,
        occurred_at: Any,
        created_at: Any,
    ) -> tuple[datetime, str]:
        explicit = parse_timestamp(occurred_at)
        if explicit:
            return explicit, "structured_date"

        text = statement or ""
        full_date = re.search(
            rf"\b({MONTH_NAMES})\s+(\d{{1,2}}),?\s+((?:19|20)\d{{2}})\b",
            text,
            flags=re.IGNORECASE,
        )
        if full_date:
            parsed = datetime.strptime(
                " ".join(full_date.groups()),
                "%B %d %Y",
            ).replace(tzinfo=timezone.utc)
            return parsed, "statement_date"

        month_year = re.search(
            rf"\b({MONTH_NAMES})\s+((?:19|20)\d{{2}})\b",
            text,
            flags=re.IGNORECASE,
        )
        if month_year:
            parsed = datetime.strptime(
                " ".join(month_year.groups()),
                "%B %Y",
            ).replace(day=15, tzinfo=timezone.utc)
            return parsed, "statement_month"

        year = re.search(r"\b((?:19|20)\d{2})\b", text)
        if year:
            return (
                datetime(int(year.group(1)), 7, 1, tzinfo=timezone.utc),
                "statement_year",
            )
        return (
            parse_timestamp(created_at) or datetime.now(timezone.utc),
            "first_seen",
        )

    @classmethod
    def impact_for(
        cls,
        event_type: str,
        *,
        significance: float = 0,
        severity: str | None = None,
    ) -> str:
        if severity == "critical" or significance >= 0.9:
            return "critical"
        if severity == "high" or significance >= 0.7:
            return "high"
        return cls.IMPACT_TYPES.get(cls.normalize_type(event_type), "medium")

    def _load_observations(self) -> list[EventObservation]:
        observations: list[EventObservation] = []
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM competitors WHERE id = %s",
                    (self.competitor_id,),
                )
                if not cur.fetchone():
                    raise ValueError("Competitor not found")
                cur.execute(
                    """
                    SELECT claim.id, claim.claim_type, claim.statement,
                           claim.occurred_at, claim.created_at,
                           verification.final_confidence,
                           verification.status AS verification_status,
                           verification.independent_sources
                    FROM claims claim
                    JOIN claim_verifications verification
                      ON verification.claim_id = claim.id
                    WHERE claim.competitor_id = %s
                    """,
                    (self.competitor_id,),
                )
                for row in cur.fetchall():
                    declared_type = self.normalize_type(row["claim_type"])
                    statement_lower = (row["statement"] or "").casefold()
                    if (
                        declared_type == "prediction"
                        or any(
                            pattern in statement_lower
                            for pattern in NON_EVENT_PATTERNS
                        )
                    ):
                        continue
                    occurred, date_basis = self.claim_date(
                        row["statement"],
                        row["occurred_at"],
                        row["created_at"],
                    )
                    event_type = self.infer_type(
                        declared_type,
                        row["statement"],
                    )
                    observations.append(
                        EventObservation(
                            source_kind="claim",
                            source_id=int(row["id"]),
                            event_type=event_type,
                            statement=row["statement"],
                            confidence=float(row["final_confidence"]),
                            verification_status=row["verification_status"],
                            impact_level=self.impact_for(event_type),
                            occurred_at=occurred,
                            source_count=int(row["independent_sources"]),
                            metadata={"date_basis": date_basis},
                        )
                    )

                cur.execute(
                    """
                    SELECT changes.id, changes.change_type, changes.summary,
                           changes.significance, changes.detected_at,
                           changes.evidence_id, evidence.confidence
                    FROM page_changes changes
                    JOIN evidence ON evidence.id = changes.evidence_id
                    WHERE changes.competitor_id = %s
                    """,
                    (self.competitor_id,),
                )
                for row in cur.fetchall():
                    event_type = self.normalize_type(row["change_type"])
                    confidence = min(
                        max(
                            float(row["significance"]) * 0.55
                            + float(row["confidence"]) * 0.45,
                            0.0,
                        ),
                        0.99,
                    )
                    observations.append(
                        EventObservation(
                            source_kind="page_change",
                            source_id=int(row["id"]),
                            event_type=event_type,
                            statement=row["summary"],
                            confidence=confidence,
                            verification_status="supported",
                            impact_level=self.impact_for(
                                event_type,
                                significance=float(row["significance"]),
                            ),
                            occurred_at=parse_timestamp(row["detected_at"])
                            or datetime.now(timezone.utc),
                            source_count=1,
                            evidence_id=int(row["evidence_id"]),
                            metadata={"significance": float(row["significance"])},
                        )
                    )

                cur.execute(
                    """
                    SELECT id, signal_type, description, severity, detected_at
                    FROM signals
                    WHERE competitor_id = %s AND claim_id IS NULL
                    """,
                    (self.competitor_id,),
                )
                for row in cur.fetchall():
                    event_type = self.normalize_type(row["signal_type"])
                    severity_confidence = {
                        "low": 0.45,
                        "medium": 0.6,
                        "high": 0.76,
                        "critical": 0.9,
                    }.get(row["severity"], 0.55)
                    observations.append(
                        EventObservation(
                            source_kind="signal",
                            source_id=int(row["id"]),
                            event_type=event_type,
                            statement=row["description"],
                            confidence=severity_confidence,
                            verification_status="proposed",
                            impact_level=self.impact_for(
                                event_type,
                                severity=row["severity"],
                            ),
                            occurred_at=parse_timestamp(row["detected_at"])
                            or datetime.now(timezone.utc),
                            source_count=0,
                            metadata={"severity": row["severity"]},
                        )
                    )
        return observations

    def cluster(
        self,
        observations: list[EventObservation],
    ) -> list[list[EventObservation]]:
        clusters: list[list[EventObservation]] = []
        ordered = sorted(
            observations,
            key=lambda item: (item.occurred_at, item.confidence),
            reverse=True,
        )
        for observation in ordered:
            matched: list[EventObservation] | None = None
            best_similarity = 0.0
            for candidate in clusters:
                representative = max(candidate, key=lambda item: item.confidence)
                if representative.event_type != observation.event_type:
                    continue
                days = abs(
                    (representative.occurred_at - observation.occurred_at).days
                )
                if days > 180:
                    continue
                score = self.similarity(
                    representative.statement,
                    observation.statement,
                )
                if score >= 0.42 and score > best_similarity:
                    matched = candidate
                    best_similarity = score
            if matched is None:
                clusters.append([observation])
            else:
                matched.append(observation)
        return clusters

    @staticmethod
    def _event_title(statement: str) -> str:
        cleaned = re.sub(r"\s+", " ", statement).strip()
        first_sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
        if len(first_sentence) <= 180:
            return first_sentence
        return first_sentence[:177].rstrip() + "..."

    def rebuild(self) -> dict[str, Any]:
        observations = self._load_observations()
        clusters = self.cluster(observations)
        now = datetime.now(timezone.utc)
        created_events: list[dict[str, Any]] = []

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM intelligence_events WHERE competitor_id = %s",
                    (self.competitor_id,),
                )
                for cluster in clusters:
                    representative = max(cluster, key=lambda item: item.confidence)
                    occurred_at = max(item.occurred_at for item in cluster)
                    first_seen = min(item.occurred_at for item in cluster)
                    impact = max(
                        (item.impact_level for item in cluster),
                        key=lambda value: self.IMPACT_RANK[value],
                    )
                    verification_status = max(
                        (item.verification_status for item in cluster),
                        key=lambda value: self.STATUS_RANK.get(value, 0),
                    )
                    if verification_status == "disputed":
                        status = "disputed"
                    elif verification_status == "stale":
                        status = "stale"
                    elif len(cluster) > 1:
                        status = "developing"
                    else:
                        status = "active"
                    confidence = confidence_union(
                        item.confidence for item in cluster
                    )
                    source_count = max(item.source_count for item in cluster)
                    statement_key = " ".join(
                        sorted(self.tokens(representative.statement))
                    )
                    event_key = hashlib.sha256(
                        (
                            f"{representative.event_type}|{statement_key}|"
                            f"{occurred_at.date().isoformat()}"
                        ).encode("utf-8")
                    ).hexdigest()
                    span_days = max(
                        (max(item.occurred_at for item in cluster)
                         - min(item.occurred_at for item in cluster)).days,
                        0,
                    )
                    metadata = {
                        "observation_count": len(cluster),
                        "source_kinds": sorted(
                            {item.source_kind for item in cluster}
                        ),
                        "date_basis": (
                            (representative.metadata or {}).get("date_basis")
                            or "observed_at"
                        ),
                        "span_days": span_days,
                        "momentum": (
                            "new"
                            if (now - occurred_at) <= timedelta(days=7)
                            else "developing" if len(cluster) > 1 else "established"
                        ),
                    }
                    cur.execute(
                        """
                        INSERT INTO intelligence_events (
                            competitor_id, event_key, event_type, title, summary,
                            impact_level, confidence, verification_status, status,
                            source_count, occurred_at, first_seen_at, last_seen_at,
                            metadata
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s
                        )
                        RETURNING id
                        """,
                        (
                            self.competitor_id,
                            event_key,
                            representative.event_type,
                            self._event_title(representative.statement),
                            representative.statement,
                            impact,
                            confidence,
                            verification_status,
                            status,
                            source_count,
                            occurred_at,
                            first_seen,
                            occurred_at,
                            Json(json_safe(metadata)),
                        ),
                    )
                    event_id = int(cur.fetchone()["id"])
                    for observation in cluster:
                        link_fields = {
                            "claim": ("claim_id", observation.source_id),
                            "page_change": ("page_change_id", observation.source_id),
                            "signal": ("signal_id", observation.source_id),
                        }
                        column, value = link_fields[observation.source_kind]
                        cur.execute(
                            f"""
                            INSERT INTO intelligence_event_links (
                                event_id, {column}, evidence_id, link_type,
                                contribution, metadata
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                event_id,
                                value,
                                observation.evidence_id,
                                observation.source_kind,
                                observation.confidence,
                                Json(json_safe(observation.metadata or {})),
                            ),
                        )
                    created_events.append(
                        {
                            "id": event_id,
                            "title": representative.statement,
                            "event_type": representative.event_type,
                            "occurred_at": occurred_at,
                        }
                    )

                token_frequency = Counter(
                    token
                    for event in created_events
                    for token in self.tokens(event["title"])
                )
                common_threshold = max(
                    3,
                    int(len(created_events) * 0.4) + 1,
                )
                ignored_tokens = {
                    token
                    for token, count in token_frequency.items()
                    if count >= common_threshold
                }
                candidates: list[dict[str, Any]] = []
                for index, left in enumerate(created_events):
                    for right in created_events[index + 1:]:
                        days = abs((left["occurred_at"] - right["occurred_at"]).days)
                        if days > 365:
                            continue
                        same_type = left["event_type"] == right["event_type"]
                        score, overlap = self.correlation_score(
                            left["title"],
                            right["title"],
                            same_type=same_type,
                            days_apart=days,
                            ignored_tokens=ignored_tokens,
                        )
                        minimum_overlap = 0.24 if same_type else 0.32
                        if overlap < minimum_overlap or score < 0.3:
                            continue
                        source_id, target_id = sorted((left["id"], right["id"]))
                        candidates.append(
                            {
                                "source_id": source_id,
                                "target_id": target_id,
                                "same_type": same_type,
                                "score": score,
                            }
                        )

                correlations = 0
                degree: dict[int, int] = defaultdict(int)
                for candidate in sorted(
                    candidates,
                    key=lambda item: item["score"],
                    reverse=True,
                ):
                    source_id = candidate["source_id"]
                    target_id = candidate["target_id"]
                    if degree[source_id] >= 4 or degree[target_id] >= 4:
                        continue
                    same_type = candidate["same_type"]
                    score = candidate["score"]
                    cur.execute(
                        """
                        INSERT INTO intelligence_event_correlations (
                            competitor_id, source_event_id, target_event_id,
                            correlation_type, score, rationale
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            self.competitor_id,
                            source_id,
                            target_id,
                            "same_theme" if same_type else "shared_entities",
                            score,
                            (
                                "Events share a type and distinctive concepts."
                                if same_type
                                else "Events contain distinctive overlapping concepts."
                            ),
                        ),
                    )
                    inserted = max(cur.rowcount, 0)
                    if inserted:
                        degree[source_id] += 1
                        degree[target_id] += 1
                        correlations += inserted
                conn.commit()
        return {
            "competitor_id": self.competitor_id,
            "observations": len(observations),
            "events": len(created_events),
            "correlations": correlations,
        }

    def overview(self, limit: int = 300) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM competitors WHERE id = %s",
                    (self.competitor_id,),
                )
                if not cur.fetchone():
                    raise ValueError("Competitor not found")
                cur.execute(
                    """
                    SELECT event.*,
                           COUNT(DISTINCT link.id) AS linked_observations,
                           COUNT(DISTINCT correlation.id) AS correlation_count
                    FROM intelligence_events event
                    LEFT JOIN intelligence_event_links link
                      ON link.event_id = event.id
                    LEFT JOIN intelligence_event_correlations correlation
                      ON correlation.source_event_id = event.id
                      OR correlation.target_event_id = event.id
                    WHERE event.competitor_id = %s
                    GROUP BY event.id
                    ORDER BY event.occurred_at DESC NULLS LAST, event.id DESC
                    LIMIT %s
                    """,
                    (self.competitor_id, min(max(limit, 1), 1000)),
                )
                events = [dict(row) for row in cur.fetchall()]
                event_ids = [row["id"] for row in events]
                correlations: list[dict[str, Any]] = []
                if event_ids:
                    cur.execute(
                        """
                        SELECT correlation.*,
                               source.title AS source_title,
                               target.title AS target_title
                        FROM intelligence_event_correlations correlation
                        JOIN intelligence_events source
                          ON source.id = correlation.source_event_id
                        JOIN intelligence_events target
                          ON target.id = correlation.target_event_id
                        WHERE correlation.competitor_id = %s
                          AND (
                            correlation.source_event_id = ANY(%s)
                            OR correlation.target_event_id = ANY(%s)
                          )
                        ORDER BY correlation.score DESC
                        """,
                        (self.competitor_id, event_ids, event_ids),
                    )
                    correlations = [dict(row) for row in cur.fetchall()]

        current = datetime.now(timezone.utc)
        recent = [
            event for event in events
            if parse_timestamp(event["occurred_at"])
            and parse_timestamp(event["occurred_at"]) >= current - timedelta(days=7)
        ]
        previous = [
            event for event in events
            if parse_timestamp(event["occurred_at"])
            and current - timedelta(days=14)
            <= parse_timestamp(event["occurred_at"])
            < current - timedelta(days=7)
        ]
        types = Counter(event["event_type"] for event in events)
        weekly = []
        for offset in range(7, -1, -1):
            start = current - timedelta(days=(offset + 1) * 7)
            end = current - timedelta(days=offset * 7)
            weekly.append(
                {
                    "start": start,
                    "end": end,
                    "events": sum(
                        1 for event in events
                        if parse_timestamp(event["occurred_at"])
                        and start <= parse_timestamp(event["occurred_at"]) < end
                    ),
                    "high_impact": sum(
                        1 for event in events
                        if parse_timestamp(event["occurred_at"])
                        and start <= parse_timestamp(event["occurred_at"]) < end
                        and event["impact_level"] in {"high", "critical"}
                    ),
                }
            )
        return {
            "summary": {
                "total_events": len(events),
                "recent_events": len(recent),
                "previous_period_events": len(previous),
                "high_impact": sum(
                    event["impact_level"] in {"high", "critical"}
                    for event in events
                ),
                "disputed": sum(event["status"] == "disputed" for event in events),
                "developing": sum(event["status"] == "developing" for event in events),
                "top_type": types.most_common(1)[0][0] if types else None,
            },
            "events": events,
            "correlations": correlations,
            "weekly_activity": weekly,
            "event_types": dict(types),
        }
