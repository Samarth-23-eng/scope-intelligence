"""Reproducible source reliability and claim verification."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from psycopg2.extras import Json

from db.postgres import get_connection
from intelligence.foundation import json_safe, parse_timestamp
from intelligence.graph import SOURCE_RELIABILITY


def confidence_union(values: Iterable[float]) -> float:
    remaining = 1.0
    for value in values:
        remaining *= 1.0 - min(max(float(value), 0.0), 0.99)
    return round(1.0 - remaining, 4)


class ClaimVerificationEngine:
    """Score claims from provenance, independence, recency, and disagreement."""

    def __init__(self, competitor_id: int):
        self.competitor_id = competitor_id

    @staticmethod
    def source_domain(url: str | None) -> str:
        host = (urlsplit(url or "").hostname or "unknown").casefold()
        return host.removeprefix("www.")[:500]

    @staticmethod
    def tier_for(reliability: float) -> str:
        if reliability >= 0.9:
            return "primary"
        if reliability >= 0.75:
            return "reliable"
        if reliability >= 0.58:
            return "contextual"
        return "low"

    @staticmethod
    def default_reliability(
        source_type: str,
        source_domain: str,
        competitor_domain: str | None,
    ) -> tuple[float, str]:
        normalized_type = (source_type or "unknown").casefold()
        normalized_competitor = (competitor_domain or "").casefold().removeprefix("www.")
        if normalized_competitor and (
            source_domain == normalized_competitor
            or source_domain.endswith(f".{normalized_competitor}")
        ):
            return 0.95, "Official company domain"
        if source_domain.endswith(".gov") or ".gov." in source_domain:
            return 0.96, "Government or public authority domain"
        score = SOURCE_RELIABILITY.get(
            normalized_type,
            SOURCE_RELIABILITY["unknown"],
        )
        return score, f"Default reliability for {normalized_type.replace('_', ' ')}"

    def _load(self) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], str | None]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT domain FROM competitors WHERE id = %s",
                    (self.competitor_id,),
                )
                competitor = cur.fetchone()
                if not competitor:
                    raise ValueError("Competitor not found")
                cur.execute(
                    """
                    SELECT *
                    FROM claims
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    """,
                    (self.competitor_id,),
                )
                claims = [dict(row) for row in cur.fetchall()]
                if not claims:
                    return [], {}, competitor["domain"]
                claim_ids = [row["id"] for row in claims]
                cur.execute(
                    """
                    SELECT link.claim_id, link.evidence_id, link.document_chunk_id,
                           link.stance, link.confidence, link.excerpt,
                           COALESCE(evidence.source_url, document.canonical_url) AS source_url,
                           COALESCE(
                               evidence.metadata->>'source_type',
                               document.source_type,
                               'unknown'
                           ) AS source_type,
                           COALESCE(
                               evidence.collected_at,
                               document.last_seen_at,
                               link.created_at
                           ) AS observed_at
                    FROM claim_evidence link
                    LEFT JOIN evidence ON evidence.id = link.evidence_id
                    LEFT JOIN document_chunks chunk
                      ON chunk.id = link.document_chunk_id
                    LEFT JOIN document_versions version
                      ON version.id = chunk.document_version_id
                    LEFT JOIN documents document
                      ON document.id = version.document_id
                    WHERE link.claim_id = ANY(%s)
                    ORDER BY link.claim_id, link.id
                    """,
                    (claim_ids,),
                )
                grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
                for row in cur.fetchall():
                    grouped[int(row["claim_id"])].append(dict(row))
        return claims, grouped, competitor["domain"]

    def _source_profiles(
        self,
        evidence_by_claim: dict[int, list[dict[str, Any]]],
        competitor_domain: str | None,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        observations: dict[tuple[str, str], dict[str, Any]] = {}
        for rows in evidence_by_claim.values():
            for row in rows:
                domain = self.source_domain(row.get("source_url"))
                source_type = str(row.get("source_type") or "unknown").casefold()[:100]
                key = (domain, source_type)
                observed = parse_timestamp(row.get("observed_at"))
                item = observations.setdefault(
                    key,
                    {"count": 0, "last_seen_at": observed},
                )
                item["count"] += 1
                if observed and (
                    not item["last_seen_at"] or observed > item["last_seen_at"]
                ):
                    item["last_seen_at"] = observed

        profiles: dict[tuple[str, str], dict[str, Any]] = {}
        with get_connection() as conn:
            with conn.cursor() as cur:
                for (domain, source_type), observation in observations.items():
                    reliability, basis = self.default_reliability(
                        source_type,
                        domain,
                        competitor_domain,
                    )
                    cur.execute(
                        """
                        INSERT INTO source_reliability_profiles (
                            competitor_id, source_domain, source_type,
                            reliability, tier, basis, evidence_count, last_seen_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (competitor_id, source_domain, source_type)
                        DO UPDATE SET
                            reliability = CASE
                                WHEN source_reliability_profiles.is_override
                                THEN source_reliability_profiles.reliability
                                ELSE EXCLUDED.reliability
                            END,
                            tier = CASE
                                WHEN source_reliability_profiles.is_override
                                THEN source_reliability_profiles.tier
                                ELSE EXCLUDED.tier
                            END,
                            basis = CASE
                                WHEN source_reliability_profiles.is_override
                                THEN source_reliability_profiles.basis
                                ELSE EXCLUDED.basis
                            END,
                            evidence_count = EXCLUDED.evidence_count,
                            last_seen_at = EXCLUDED.last_seen_at,
                            assessed_at = NOW()
                        RETURNING *
                        """,
                        (
                            self.competitor_id,
                            domain,
                            source_type,
                            reliability,
                            self.tier_for(reliability),
                            basis,
                            observation["count"],
                            observation["last_seen_at"],
                        ),
                    )
                    profiles[(domain, source_type)] = dict(cur.fetchone())
                conn.commit()
        return profiles

    @staticmethod
    def score_claim(
        claim: dict[str, Any],
        evidence: list[dict[str, Any]],
        source_profiles: dict[tuple[str, str], dict[str, Any]],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        metadata = claim.get("metadata") or {}
        model_confidence = float(
            metadata.get("model_confidence", claim.get("confidence") or 0.5)
        )
        supports: list[float] = []
        contradicts: list[float] = []
        support_domains: set[str] = set()
        source_scores: dict[tuple[str, str], float] = {}
        dates: list[datetime] = []

        for item in evidence:
            domain = ClaimVerificationEngine.source_domain(item.get("source_url"))
            source_type = str(item.get("source_type") or "unknown").casefold()[:100]
            profile = source_profiles.get((domain, source_type), {})
            reliability = float(profile.get("reliability", 0.55))
            score = float(item.get("confidence") or 0.5) * reliability
            source_scores[(domain, source_type)] = reliability
            observed = parse_timestamp(item.get("observed_at"))
            if observed:
                dates.append(observed)
            if item.get("stance") == "supports":
                supports.append(score)
                support_domains.add(domain)
            elif item.get("stance") == "contradicts":
                contradicts.append(score)

        corroboration = confidence_union(supports)
        contradiction = confidence_union(contradicts)
        diversity = len(support_domains)
        source_quality = (
            sum(source_scores.values()) / len(source_scores)
            if source_scores
            else 0.0
        )
        latest = max(dates) if dates else parse_timestamp(claim.get("created_at")) or current
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        age_days = max((current - latest).total_seconds() / 86400, 0)
        freshness = max(0.1, 0.5 ** (age_days / 180))
        combined = (
            model_confidence * 0.2
            + corroboration * 0.5
            + source_quality * 0.15
            + min(diversity, 3) * 0.035
            + freshness * 0.045
        )
        combined *= 1.0 - contradiction * 0.7
        final_confidence = round(min(max(combined, 0.0), 0.99), 4)

        flags: list[str] = []
        if not supports:
            flags.append("uncited")
        if supports and diversity < 2:
            flags.append("single_source")
        if source_scores and min(source_scores.values()) < 0.58:
            flags.append("low_reliability_source")
        if contradicts:
            flags.append("contradictory_evidence")
        if freshness < 0.35:
            flags.append("stale_evidence")
        if final_confidence < 0.5:
            flags.append("low_confidence")

        if contradiction >= 0.45:
            status = "disputed"
        elif freshness < 0.35:
            status = "stale"
        elif diversity >= 2 and final_confidence >= 0.78:
            status = "confirmed"
        elif supports and final_confidence >= 0.48:
            status = "supported"
        else:
            status = "proposed"

        if metadata.get("human_review_locked"):
            status = str(claim.get("status") or status)
            flags.append("human_reviewed")

        rationale = (
            f"{len(supports)} supporting citation(s) across {diversity} independent "
            f"domain(s), {len(contradicts)} contradiction(s), "
            f"{round(source_quality * 100)}% mean source quality, and "
            f"{round(freshness * 100)}% freshness."
        )
        return {
            "support_count": len(supports),
            "contradiction_count": len(contradicts),
            "independent_sources": diversity,
            "corroboration_score": round(corroboration, 4),
            "contradiction_score": round(contradiction, 4),
            "freshness_score": round(freshness, 4),
            "source_quality": round(source_quality, 4),
            "final_confidence": final_confidence,
            "status": status,
            "risk_flags": list(dict.fromkeys(flags)),
            "rationale": rationale,
            "metadata": {"model_confidence": model_confidence},
        }

    def verify_all(self) -> dict[str, Any]:
        claims, evidence_by_claim, competitor_domain = self._load()
        profiles = self._source_profiles(evidence_by_claim, competitor_domain)
        counts: dict[str, int] = defaultdict(int)
        with get_connection() as conn:
            with conn.cursor() as cur:
                for claim in claims:
                    score = self.score_claim(
                        claim,
                        evidence_by_claim.get(int(claim["id"]), []),
                        profiles,
                    )
                    counts[score["status"]] += 1
                    cur.execute(
                        """
                        INSERT INTO claim_verifications (
                            claim_id, competitor_id, support_count,
                            contradiction_count, independent_sources,
                            corroboration_score, contradiction_score,
                            freshness_score, source_quality, final_confidence,
                            status, risk_flags, rationale, metadata
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (claim_id) DO UPDATE SET
                            support_count = EXCLUDED.support_count,
                            contradiction_count = EXCLUDED.contradiction_count,
                            independent_sources = EXCLUDED.independent_sources,
                            corroboration_score = EXCLUDED.corroboration_score,
                            contradiction_score = EXCLUDED.contradiction_score,
                            freshness_score = EXCLUDED.freshness_score,
                            source_quality = EXCLUDED.source_quality,
                            final_confidence = EXCLUDED.final_confidence,
                            status = EXCLUDED.status,
                            risk_flags = EXCLUDED.risk_flags,
                            rationale = EXCLUDED.rationale,
                            metadata = EXCLUDED.metadata,
                            assessed_at = NOW()
                        """,
                        (
                            claim["id"],
                            self.competitor_id,
                            score["support_count"],
                            score["contradiction_count"],
                            score["independent_sources"],
                            score["corroboration_score"],
                            score["contradiction_score"],
                            score["freshness_score"],
                            score["source_quality"],
                            score["final_confidence"],
                            score["status"],
                            Json(score["risk_flags"]),
                            score["rationale"],
                            Json(score["metadata"]),
                        ),
                    )
                    original_metadata = claim.get("metadata") or {}
                    original_metadata.setdefault(
                        "model_confidence",
                        float(claim.get("confidence") or 0.5),
                    )
                    cur.execute(
                        """
                        UPDATE claims
                        SET confidence = %s, status = %s, metadata = %s
                        WHERE id = %s
                        """,
                        (
                            score["final_confidence"],
                            score["status"],
                            Json(json_safe(original_metadata)),
                            claim["id"],
                        ),
                    )
                conn.commit()
        return {
            "competitor_id": self.competitor_id,
            "claims_assessed": len(claims),
            "sources_assessed": len(profiles),
            "status_counts": dict(counts),
        }

    def overview(self) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT verification.*, claim.statement, claim.claim_type,
                           claim.created_at AS claim_created_at,
                           claim.metadata AS claim_metadata
                    FROM claim_verifications verification
                    JOIN claims claim ON claim.id = verification.claim_id
                    WHERE verification.competitor_id = %s
                    ORDER BY
                        CASE verification.status
                            WHEN 'disputed' THEN 0
                            WHEN 'proposed' THEN 1
                            WHEN 'stale' THEN 2
                            ELSE 3
                        END,
                        verification.final_confidence,
                        verification.assessed_at DESC
                    """,
                    (self.competitor_id,),
                )
                verifications = [dict(row) for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT *
                    FROM source_reliability_profiles
                    WHERE competitor_id = %s
                    ORDER BY reliability DESC, evidence_count DESC
                    """,
                    (self.competitor_id,),
                )
                sources = [dict(row) for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT review.*, claim.statement
                    FROM claim_reviews review
                    JOIN claims claim ON claim.id = review.claim_id
                    WHERE review.competitor_id = %s
                    ORDER BY review.created_at DESC
                    LIMIT 30
                    """,
                    (self.competitor_id,),
                )
                reviews = [dict(row) for row in cur.fetchall()]
        total = len(verifications)
        queue = [
            item
            for item in verifications
            if item["status"] in {"disputed", "proposed", "stale"}
            or item["independent_sources"] < 2
        ]
        return {
            "summary": {
                "total_claims": total,
                "confirmed": sum(item["status"] == "confirmed" for item in verifications),
                "supported": sum(item["status"] == "supported" for item in verifications),
                "needs_review": len(queue),
                "disputed": sum(item["status"] == "disputed" for item in verifications),
                "average_confidence": round(
                    sum(item["final_confidence"] for item in verifications) / total,
                    4,
                ) if total else 0.0,
                "source_count": len(sources),
            },
            "queue": queue,
            "verifications": verifications,
            "sources": sources,
            "reviews": reviews,
        }

    def review_claim(self, claim_id: int, decision: str, note: str | None) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, status, metadata
                    FROM claims
                    WHERE id = %s AND competitor_id = %s
                    FOR UPDATE
                    """,
                    (claim_id, self.competitor_id),
                )
                claim = cur.fetchone()
                if not claim:
                    raise ValueError("Claim not found")
                metadata = dict(claim.get("metadata") or {})
                metadata["human_review_locked"] = True
                metadata["human_review_note"] = (note or "")[:2000]
                cur.execute(
                    """
                    INSERT INTO claim_reviews (
                        claim_id, competitor_id, decision, previous_status, note
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        claim_id,
                        self.competitor_id,
                        decision,
                        claim["status"],
                        (note or "")[:5000] or None,
                    ),
                )
                review = dict(cur.fetchone())
                cur.execute(
                    """
                    UPDATE claims
                    SET status = %s, metadata = %s
                    WHERE id = %s
                    """,
                    (decision, Json(json_safe(metadata)), claim_id),
                )
                cur.execute(
                    """
                    UPDATE claim_verifications
                    SET status = %s,
                        risk_flags = risk_flags || '["human_reviewed"]'::jsonb,
                        assessed_at = NOW()
                    WHERE claim_id = %s
                    """,
                    (decision, claim_id),
                )
                conn.commit()
        return review

    def override_source(
        self,
        source_profile_id: int,
        reliability: float,
        basis: str,
    ) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE source_reliability_profiles
                    SET reliability = %s, tier = %s, basis = %s,
                        is_override = TRUE, assessed_at = NOW()
                    WHERE id = %s AND competitor_id = %s
                    RETURNING *
                    """,
                    (
                        reliability,
                        self.tier_for(reliability),
                        basis[:2000],
                        source_profile_id,
                        self.competitor_id,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError("Source profile not found")
                conn.commit()
        return dict(row)
