from __future__ import annotations

import csv
import heapq
import io
import json
import math
from datetime import datetime
from html import escape
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from db.postgres import get_connection
from intelligence.foundation import json_safe


router = APIRouter()


def _verify_competitor(competitor_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM competitors WHERE id = %s", (competitor_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Competitor not found")


def _graph_rows(competitor_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, competitor_id, name, entity_type, metadata,
                       created_at, updated_at
                FROM entities
                WHERE competitor_id = %s
                ORDER BY entity_type, name, id
                """,
                (competitor_id,),
            )
            entities = [dict(row) for row in (cur.fetchall() or [])]
            cur.execute(
                """
                SELECT relationship.id,
                       relationship.source_entity_id,
                       source.name AS source_name,
                       source.entity_type AS source_type,
                       relationship.target_entity_id,
                       target.name AS target_name,
                       target.entity_type AS target_type,
                       relationship.relationship_type,
                       relationship.weight,
                       relationship.rationale,
                       relationship.extraction_method,
                       relationship.evidence_count,
                       relationship.corroboration_score,
                       relationship.source_diversity,
                       relationship.freshness_score,
                       relationship.contradiction_count,
                       relationship.risk_level,
                       relationship.status,
                       relationship.operator_status,
                       relationship.operator_note,
                       relationship.metadata,
                       relationship.created_at,
                       relationship.first_seen_at,
                       relationship.last_seen_at,
                       COALESCE(
                           (
                               SELECT JSONB_AGG(
                                   JSONB_BUILD_OBJECT(
                                       'id', evidence.id,
                                       'source_url', evidence.source_url,
                                       'title', evidence.title,
                                       'snippet', relationship_evidence.support_excerpt,
                                       'confidence', relationship_evidence.confidence,
                                       'collected_at', evidence.collected_at
                                   )
                                   ORDER BY evidence.collected_at DESC
                               )
                               FROM relationship_evidence
                               JOIN evidence
                                 ON evidence.id = relationship_evidence.evidence_id
                               WHERE relationship_evidence.relationship_id = relationship.id
                           ),
                           '[]'::jsonb
                       ) AS evidence
                FROM relationships AS relationship
                JOIN entities AS source
                  ON source.id = relationship.source_entity_id
                JOIN entities AS target
                  ON target.id = relationship.target_entity_id
                WHERE source.competitor_id = %s
                  AND target.competitor_id = %s
                  AND relationship.operator_status IS DISTINCT FROM 'dismissed'
                ORDER BY relationship.weight DESC, relationship.id
                """,
                (competitor_id, competitor_id),
            )
            relationships = [dict(row) for row in (cur.fetchall() or [])]
    return entities, relationships


@router.get("/competitors/{competitor_id}/graph/snapshots")
def list_graph_snapshots(competitor_id: int, limit: int = Query(50, ge=1, le=200)):
    _verify_competitor(competitor_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT snapshot.id, snapshot.pipeline_run_id,
                       snapshot.entity_count, snapshot.relationship_count,
                       snapshot.component_count,
                       snapshot.disputed_relationships,
                       snapshot.weak_relationships,
                       snapshot.metrics, snapshot.created_at,
                       EXISTS (
                           SELECT 1
                           FROM graph_snapshot_entities
                           WHERE graph_snapshot_entities.snapshot_id = snapshot.id
                       ) AS has_state
                FROM graph_snapshots AS snapshot
                WHERE snapshot.competitor_id = %s
                ORDER BY snapshot.created_at DESC, snapshot.id DESC
                LIMIT %s
                """,
                (competitor_id, limit),
            )
            return json_safe(cur.fetchall() or [])


def _snapshot_state(
    competitor_id: int,
    snapshot_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM graph_snapshots
                WHERE id = %s AND competitor_id = %s
                """,
                (snapshot_id, competitor_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Graph snapshot not found")
            cur.execute(
                """
                SELECT entity_id AS id, name, entity_type, metadata
                FROM graph_snapshot_entities
                WHERE snapshot_id = %s
                ORDER BY entity_id
                """,
                (snapshot_id,),
            )
            entities = [dict(row) for row in (cur.fetchall() or [])]
            cur.execute(
                """
                SELECT relationship_id AS id, source_entity_id, target_entity_id,
                       relationship_type, weight, status, risk_level,
                       evidence_count, source_diversity, freshness_score,
                       contradiction_count, first_seen_at, last_seen_at, metadata
                FROM graph_snapshot_relationships
                WHERE snapshot_id = %s
                ORDER BY relationship_id
                """,
                (snapshot_id,),
            )
            relationships = [dict(row) for row in (cur.fetchall() or [])]
    if not entities and not relationships:
        raise HTTPException(
            status_code=409,
            detail=(
                "This legacy snapshot predates Graph Studio state capture. "
                "Analyze the graph again to create a comparable snapshot."
            ),
        )
    return entities, relationships


@router.get("/competitors/{competitor_id}/graph/diff")
def diff_graph_snapshots(
    competitor_id: int,
    from_snapshot_id: int = Query(gt=0),
    to_snapshot_id: int = Query(gt=0),
):
    if from_snapshot_id == to_snapshot_id:
        raise HTTPException(status_code=400, detail="Choose two different snapshots")
    from_entities, from_relationships = _snapshot_state(
        competitor_id,
        from_snapshot_id,
    )
    to_entities, to_relationships = _snapshot_state(competitor_id, to_snapshot_id)
    from_entity_map = {int(row["id"]): row for row in from_entities}
    to_entity_map = {int(row["id"]): row for row in to_entities}
    from_edge_map = {int(row["id"]): row for row in from_relationships}
    to_edge_map = {int(row["id"]): row for row in to_relationships}

    changed: list[dict[str, Any]] = []
    for relationship_id in sorted(from_edge_map.keys() & to_edge_map.keys()):
        before = from_edge_map[relationship_id]
        after = to_edge_map[relationship_id]
        weight_delta = round(float(after["weight"]) - float(before["weight"]), 4)
        if (
            abs(weight_delta) < 0.01
            and before["status"] == after["status"]
            and before["risk_level"] == after["risk_level"]
            and before["evidence_count"] == after["evidence_count"]
        ):
            continue
        if after["status"] == "disputed" and before["status"] != "disputed":
            change_type = "disputed"
        elif weight_delta >= 0.01:
            change_type = "strengthened"
        elif weight_delta <= -0.01:
            change_type = "weakened"
        else:
            change_type = "updated"
        changed.append(
            {
                "relationship_id": relationship_id,
                "change_type": change_type,
                "weight_delta": weight_delta,
                "before": before,
                "after": after,
            }
        )

    return json_safe(
        {
            "from_snapshot_id": from_snapshot_id,
            "to_snapshot_id": to_snapshot_id,
            "entities": {
                "added": [
                    to_entity_map[key]
                    for key in sorted(to_entity_map.keys() - from_entity_map.keys())
                ],
                "removed": [
                    from_entity_map[key]
                    for key in sorted(from_entity_map.keys() - to_entity_map.keys())
                ],
            },
            "relationships": {
                "added": [
                    to_edge_map[key]
                    for key in sorted(to_edge_map.keys() - from_edge_map.keys())
                ],
                "removed": [
                    from_edge_map[key]
                    for key in sorted(from_edge_map.keys() - to_edge_map.keys())
                ],
                "changed": changed,
            },
            "summary": {
                "entities_added": len(to_entity_map.keys() - from_entity_map.keys()),
                "entities_removed": len(from_entity_map.keys() - to_entity_map.keys()),
                "relationships_added": len(to_edge_map.keys() - from_edge_map.keys()),
                "relationships_removed": len(from_edge_map.keys() - to_edge_map.keys()),
                "relationships_changed": len(changed),
            },
        }
    )


@router.get("/competitors/{competitor_id}/graph/path")
def find_graph_path(
    competitor_id: int,
    source_entity_id: int = Query(gt=0),
    target_entity_id: int = Query(gt=0),
    mode: Literal["strongest", "shortest"] = "strongest",
):
    if source_entity_id == target_entity_id:
        raise HTTPException(status_code=400, detail="Choose two different entities")
    entities, relationships = _graph_rows(competitor_id)
    entity_by_id = {int(row["id"]): row for row in entities}
    if source_entity_id not in entity_by_id or target_entity_id not in entity_by_id:
        raise HTTPException(status_code=404, detail="Entity not found in this company graph")

    adjacency: dict[int, list[tuple[int, float, dict[str, Any]]]] = {
        entity_id: [] for entity_id in entity_by_id
    }
    for relationship in relationships:
        source = int(relationship["source_entity_id"])
        target = int(relationship["target_entity_id"])
        if mode == "shortest":
            cost = 1.0
        else:
            confidence = max(float(relationship.get("weight") or 0), 0.01)
            freshness = max(float(relationship.get("freshness_score") or 0.5), 0.2)
            cost = -math.log(max(confidence * (0.75 + freshness * 0.25), 0.01))
        adjacency[source].append((target, cost, relationship))
        adjacency[target].append((source, cost, relationship))

    queue: list[tuple[float, int]] = [(0.0, source_entity_id)]
    distances = {source_entity_id: 0.0}
    previous: dict[int, tuple[int, dict[str, Any]]] = {}
    while queue:
        distance, node_id = heapq.heappop(queue)
        if distance > distances.get(node_id, float("inf")):
            continue
        if node_id == target_entity_id:
            break
        for neighbor, edge_cost, relationship in adjacency.get(node_id, []):
            candidate = distance + edge_cost
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                previous[neighbor] = (node_id, relationship)
                heapq.heappush(queue, (candidate, neighbor))

    if target_entity_id not in previous:
        raise HTTPException(status_code=404, detail="No relationship path connects these entities")

    node_ids = [target_entity_id]
    path_relationships: list[dict[str, Any]] = []
    cursor = target_entity_id
    while cursor != source_entity_id:
        parent, relationship = previous[cursor]
        path_relationships.append(relationship)
        node_ids.append(parent)
        cursor = parent
    node_ids.reverse()
    path_relationships.reverse()
    return json_safe(
        {
            "mode": mode,
            "hop_count": len(path_relationships),
            "score": round(distances[target_entity_id], 5),
            "nodes": [entity_by_id[node_id] for node_id in node_ids],
            "relationships": path_relationships,
        }
    )


@router.get("/competitors/{competitor_id}/graph/export")
def export_graph(
    competitor_id: int,
    format: Literal["json", "csv", "graphml"] = "json",
):
    _verify_competitor(competitor_id)
    entities, relationships = _graph_rows(competitor_id)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    basename = f"scope_graph_{competitor_id}_{stamp}"
    if format == "json":
        body = json.dumps(
            json_safe({"entities": entities, "relationships": relationships}),
            indent=2,
        )
        return Response(
            body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{basename}.json"'},
        )
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "relationship_id",
                "source",
                "source_type",
                "relationship",
                "target",
                "target_type",
                "confidence",
                "status",
                "risk",
                "evidence_count",
                "last_seen",
            ]
        )
        for row in relationships:
            writer.writerow(
                [
                    row["id"],
                    row["source_name"],
                    row["source_type"],
                    row["relationship_type"],
                    row["target_name"],
                    row["target_type"],
                    row["weight"],
                    row["status"],
                    row["risk_level"],
                    row["evidence_count"],
                    row["last_seen_at"],
                ]
            )
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{basename}.csv"'},
        )

    node_rows = "\n".join(
        (
            f'<node id="n{row["id"]}">'
            f'<data key="name">{escape(str(row["name"]))}</data>'
            f'<data key="type">{escape(str(row["entity_type"]))}</data>'
            "</node>"
        )
        for row in entities
    )
    edge_rows = "\n".join(
        (
            f'<edge id="e{row["id"]}" source="n{row["source_entity_id"]}" '
            f'target="n{row["target_entity_id"]}">'
            f'<data key="relationship">{escape(str(row["relationship_type"]))}</data>'
            f'<data key="confidence">{float(row["weight"]):.4f}</data>'
            f'<data key="status">{escape(str(row["status"]))}</data>'
            "</edge>"
        )
        for row in relationships
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n'
        '<key id="name" for="node" attr.name="name" attr.type="string"/>\n'
        '<key id="type" for="node" attr.name="type" attr.type="string"/>\n'
        '<key id="relationship" for="edge" attr.name="relationship" attr.type="string"/>\n'
        '<key id="confidence" for="edge" attr.name="confidence" attr.type="double"/>\n'
        '<key id="status" for="edge" attr.name="status" attr.type="string"/>\n'
        '<graph edgedefault="directed">\n'
        f"{node_rows}\n{edge_rows}\n"
        "</graph>\n</graphml>\n"
    )
    return Response(
        body,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": f'attachment; filename="{basename}.graphml"'},
    )
