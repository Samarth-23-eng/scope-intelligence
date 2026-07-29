import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from psycopg2.extras import Json

from db.postgres import get_connection


@dataclass(frozen=True)
class ChangeAnalysis:
    meaningful: bool
    change_type: str
    summary: str
    before_excerpt: str
    after_excerpt: str
    similarity: float
    significance: float


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_saved: bool
    change_detected: bool
    change_type: str | None = None
    significance: float = 0.0


class PageChangeMonitor:
    """Persist immutable page snapshots and evidence-backed meaningful changes."""

    CATEGORY_KEYWORDS = {
        "pricing": {
            "price", "pricing", "plan", "plans", "monthly", "annually", "annual",
            "subscription", "free trial", "per month", "per user", "$", "₹", "€", "£",
        },
        "product": {
            "launch", "launched", "feature", "features", "product", "release",
            "available now", "beta", "roadmap",
        },
        "integration": {
            "integration", "integrations", "connects with", "plugin", "api",
            "marketplace", "partner",
        },
        "leadership": {
            "chief executive", "ceo", "chief technology", "cto", "chief product",
            "appointed", "leadership", "executive", "founder",
        },
        "hiring": {
            "career", "careers", "job", "jobs", "hiring", "vacancy", "open role",
            "join our team",
        },
    }

    def __init__(self, competitor_id: int, competitor_name: str):
        self.competitor_id = competitor_id
        self.competitor_name = competitor_name

    @staticmethod
    def normalize_content(content: str) -> str:
        text = unicodedata.normalize("NFKC", content or "")
        text = text.replace("\u00a0", " ")
        text = re.sub(
            r"\b(?:last\s+updated|updated\s+on)\s*:?\s*"
            r"(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
            r"dec(?:ember)?)\s+\d{1,2},?\s+\d{4})",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|utc|gmt)?\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"(?:©|copyright)\s*\d{4}", "copyright", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def analyze_change(cls, previous: str, current: str, source_url: str) -> ChangeAnalysis:
        previous_words = previous.split()
        current_words = current.split()
        matcher = SequenceMatcher(None, previous_words, current_words, autojunk=False)
        similarity = round(matcher.ratio(), 4)

        removed: list[str] = []
        added: list[str] = []
        first_before = 0
        first_after = 0
        found_change = False
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if not found_change:
                first_before, first_after = i1, j1
                found_change = True
            removed.extend(previous_words[i1:i2])
            added.extend(current_words[j1:j2])

        changed_word_count = len(removed) + len(added)
        changed_text = " ".join(removed + added).casefold()
        change_type = cls.classify_change(changed_text, source_url)
        significance = round(
            min(1.0, (1.0 - similarity) + min(changed_word_count / 100.0, 0.35)),
            4,
        )
        keyword_change = change_type != "website"
        meaningful = bool(
            found_change
            and (
                changed_word_count >= 3
                or significance >= 0.08
                or (keyword_change and changed_word_count >= 1)
            )
        )

        before_excerpt = cls._excerpt(previous_words, first_before) if found_change else ""
        after_excerpt = cls._excerpt(current_words, first_after) if found_change else ""
        summary = cls._summarize(change_type, added, removed)
        return ChangeAnalysis(
            meaningful=meaningful,
            change_type=change_type,
            summary=summary,
            before_excerpt=before_excerpt,
            after_excerpt=after_excerpt,
            similarity=similarity,
            significance=significance,
        )

    @classmethod
    def classify_change(cls, changed_text: str, source_url: str) -> str:
        searchable = f"{changed_text} {source_url}".casefold()
        for category, keywords in cls.CATEGORY_KEYWORDS.items():
            if any(keyword in searchable for keyword in keywords):
                return category
        return "website"

    @staticmethod
    def _excerpt(words: list[str], position: int, radius: int = 24) -> str:
        start = max(0, position - radius)
        end = min(len(words), position + radius)
        excerpt = " ".join(words[start:end])
        return excerpt[:600]

    @staticmethod
    def _summarize(change_type: str, added: list[str], removed: list[str]) -> str:
        label = {
            "pricing": "Pricing or packaging changed",
            "product": "Product information changed",
            "integration": "Integration information changed",
            "leadership": "Leadership information changed",
            "hiring": "Hiring information changed",
            "website": "Website content changed",
        }[change_type]
        added_preview = " ".join(added[:18]).strip()
        removed_preview = " ".join(removed[:18]).strip()
        if added_preview and removed_preview:
            return f'{label}: replaced "{removed_preview}" with "{added_preview}".'
        if added_preview:
            return f'{label}: added "{added_preview}".'
        if removed_preview:
            return f'{label}: removed "{removed_preview}".'
        return f"{label}."

    def record_snapshot(
        self,
        source_url: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SnapshotResult:
        normalized = self.normalize_content(content)
        if not normalized:
            return SnapshotResult(snapshot_saved=False, change_detected=False)

        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        captured_at = datetime.now(timezone.utc).isoformat()
        evidence_hash = hashlib.sha256(
            f"{source_url}\0{content_hash}\0{captured_at}".encode("utf-8")
        ).hexdigest()
        metadata = metadata or {}

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, normalized_content, content_hash
                    FROM page_snapshots
                    WHERE competitor_id = %s AND source_url = %s
                    ORDER BY captured_at DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (self.competitor_id, source_url),
                )
                previous = cur.fetchone()
                if previous and previous["content_hash"] == content_hash:
                    return SnapshotResult(snapshot_saved=False, change_detected=False)

                cur.execute(
                    """
                    INSERT INTO evidence (
                        competitor_id, source_url, title, snippet, full_text,
                        confidence, hash, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, 1.0, %s, %s)
                    ON CONFLICT (competitor_id, hash)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        snippet = EXCLUDED.snippet,
                        full_text = EXCLUDED.full_text,
                        metadata = EXCLUDED.metadata
                    RETURNING id
                    """,
                    (
                        self.competitor_id,
                        source_url,
                        title[:1000] if title else None,
                        normalized[:1000],
                        normalized,
                        evidence_hash,
                        Json(
                            {
                                **metadata,
                                "kind": "page_snapshot",
                                "content_hash": content_hash,
                                "captured_at": captured_at,
                            }
                        ),
                    ),
                )
                evidence_id = cur.fetchone()["id"]
                cur.execute(
                    """
                    INSERT INTO page_snapshots (
                        competitor_id, evidence_id, source_url, title,
                        normalized_content, content_hash, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        self.competitor_id,
                        evidence_id,
                        source_url,
                        title[:1000] if title else None,
                        normalized,
                        content_hash,
                        Json(metadata),
                    ),
                )
                snapshot_id = cur.fetchone()["id"]

                if not previous:
                    conn.commit()
                    return SnapshotResult(snapshot_saved=True, change_detected=False)

                analysis = self.analyze_change(
                    previous["normalized_content"],
                    normalized,
                    source_url,
                )
                if analysis.meaningful:
                    cur.execute(
                        """
                        INSERT INTO page_changes (
                            competitor_id, previous_snapshot_id, current_snapshot_id,
                            evidence_id, source_url, change_type, summary,
                            before_excerpt, after_excerpt, similarity, significance
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (current_snapshot_id) DO NOTHING
                        """,
                        (
                            self.competitor_id,
                            previous["id"],
                            snapshot_id,
                            evidence_id,
                            source_url,
                            analysis.change_type,
                            analysis.summary,
                            analysis.before_excerpt,
                            analysis.after_excerpt,
                            analysis.similarity,
                            analysis.significance,
                        ),
                    )
                conn.commit()
                return SnapshotResult(
                    snapshot_saved=True,
                    change_detected=analysis.meaningful,
                    change_type=analysis.change_type if analysis.meaningful else None,
                    significance=analysis.significance,
                )
