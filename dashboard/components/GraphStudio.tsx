'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Graph from 'graphology';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import Sigma from 'sigma';

import { Icon } from '@/components/Icon';
import {
  getGraphDiff,
  getGraphPath,
  graphExportUrl,
} from '@/lib/api';
import type {
  Entity,
  GraphDiff,
  GraphPath,
  GraphSnapshot,
  Relationship,
  RelationshipIntelligence,
} from '@/lib/types';

type StudioMode = 'explore' | 'path' | 'timeline';

interface GraphStudioProps {
  competitorId: number;
  entities: Entity[];
  relationships: Relationship[];
  intelligence: RelationshipIntelligence | null;
  snapshots: GraphSnapshot[];
}

const ENTITY_COLORS: Record<string, string> = {
  company: '#77a7ff',
  person: '#c49aff',
  executive: '#c49aff',
  product: '#51d5c6',
  subsidiary: '#fb7185',
  competitor: '#ff7e78',
  partner: '#7cdda8',
  technology: '#59c9ee',
  customer: '#f7c66b',
  integration: '#45d4bd',
  location: '#9da9ba',
  investor: '#ef91d8',
};

const RISK_COLORS: Record<string, string> = {
  unassessed: '#536074',
  low: '#55cf9a',
  medium: '#e8b35f',
  high: '#f0806d',
  critical: '#ff5b66',
};

function entityColor(type: string) {
  return ENTITY_COLORS[type] ?? '#88a1c7';
}

function relationshipColor(relationship: Relationship) {
  if (relationship.status === 'disputed') return '#ff5b66';
  if (relationship.status === 'stale') return '#667085';
  return RISK_COLORS[relationship.risk_level] ?? '#536074';
}

function label(value: string) {
  return value.replaceAll('_', ' ');
}

function confidence(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function GraphStudio({
  competitorId,
  entities,
  relationships,
  intelligence,
  snapshots,
}: GraphStudioProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<Sigma | null>(null);
  const [mode, setMode] = useState<StudioMode>('explore');
  const [query, setQuery] = useState('');
  const [entityType, setEntityType] = useState('all');
  const [relationshipType, setRelationshipType] = useState('all');
  const [minimumConfidence, setMinimumConfidence] = useState(35);
  const [showStale, setShowStale] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [selectedRelationshipId, setSelectedRelationshipId] = useState<number | null>(null);
  const [pathSource, setPathSource] = useState('');
  const [pathTarget, setPathTarget] = useState('');
  const [pathMode, setPathMode] = useState<'strongest' | 'shortest'>('strongest');
  const [path, setPath] = useState<GraphPath | null>(null);
  const [fromSnapshot, setFromSnapshot] = useState('');
  const [toSnapshot, setToSnapshot] = useState('');
  const [diff, setDiff] = useState<GraphDiff | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const entityTypes = useMemo(
    () => Array.from(new Set(entities.map((entity) => entity.entity_type))).sort(),
    [entities],
  );
  const relationshipTypes = useMemo(
    () => Array.from(new Set(relationships.map((item) => item.relationship_type))).sort(),
    [relationships],
  );
  const statefulSnapshots = useMemo(
    () => snapshots.filter((snapshot) => snapshot.has_state),
    [snapshots],
  );
  const highlightedRelationshipIds = useMemo(
    () => new Set(path?.relationships.map((item) => item.id) ?? []),
    [path],
  );

  const filteredRelationships = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return relationships.filter((relationship) => {
      if (!showStale && relationship.status === 'stale') return false;
      if (relationship.weight * 100 < minimumConfidence) return false;
      if (
        relationshipType !== 'all'
        && relationship.relationship_type !== relationshipType
      ) return false;
      if (
        entityType !== 'all'
        && relationship.source_type !== entityType
        && relationship.target_type !== entityType
      ) return false;
      if (
        normalized
        && !relationship.source_name.toLocaleLowerCase().includes(normalized)
        && !relationship.target_name.toLocaleLowerCase().includes(normalized)
        && !relationship.relationship_type.toLocaleLowerCase().includes(normalized)
      ) return false;
      return true;
    });
  }, [
    entityType,
    minimumConfidence,
    query,
    relationshipType,
    relationships,
    showStale,
  ]);

  const visibleEntityIds = useMemo(() => {
    const ids = new Set<number>();
    filteredRelationships.forEach((relationship) => {
      ids.add(relationship.source_entity_id);
      ids.add(relationship.target_entity_id);
    });
    if (!query.trim() && entityType === 'all') {
      entities.forEach((entity) => ids.add(entity.id));
    }
    return ids;
  }, [entities, entityType, filteredRelationships, query]);

  const selectedEntity = entities.find((entity) => entity.id === selectedNodeId) ?? null;
  const selectedRelationship = relationships.find(
    (relationship) => relationship.id === selectedRelationshipId,
  ) ?? null;
  const selectedConnections = selectedEntity
    ? relationships.filter(
      (relationship) => (
        relationship.source_entity_id === selectedEntity.id
        || relationship.target_entity_id === selectedEntity.id
      ),
    )
    : [];

  useEffect(() => {
    if (!containerRef.current) return;
    rendererRef.current?.kill();
    rendererRef.current = null;
    const graph = new Graph({ multi: true, type: 'directed' });
    const visibleEntities = entities
      .filter((entity) => visibleEntityIds.has(entity.id))
      .sort((a, b) => a.entity_type.localeCompare(b.entity_type) || a.name.localeCompare(b.name));
    const total = Math.max(visibleEntities.length, 1);
    visibleEntities.forEach((entity, index) => {
      const root = entity.metadata.root === true;
      const angle = (index / total) * Math.PI * 2;
      const ring = 7 + (index % 3) * 2.4;
      graph.addNode(String(entity.id), {
        label: entity.name,
        x: root ? 0 : Math.cos(angle) * ring,
        y: root ? 0 : Math.sin(angle) * ring,
        size: root ? 15 : 7.5,
        color: entityColor(entity.entity_type),
        forceLabel: root || visibleEntities.length < 40,
        entityType: entity.entity_type,
      });
    });
    filteredRelationships.forEach((relationship) => {
      const source = String(relationship.source_entity_id);
      const target = String(relationship.target_entity_id);
      if (!graph.hasNode(source) || !graph.hasNode(target)) return;
      const highlighted = highlightedRelationshipIds.has(relationship.id);
      graph.addDirectedEdgeWithKey(`r${relationship.id}`, source, target, {
        label: label(relationship.relationship_type),
        size: highlighted ? 4.5 : Math.max(1.2, relationship.weight * 3),
        color: highlighted ? '#f8d477' : relationshipColor(relationship),
        forceLabel: highlighted || filteredRelationships.length < 30,
        relationshipId: relationship.id,
      });
    });
    if (graph.order > 2 && graph.order < 1200) {
      forceAtlas2.assign(graph, {
        iterations: Math.min(120, 35 + graph.order),
        settings: {
          ...forceAtlas2.inferSettings(graph),
          gravity: 1.4,
          scalingRatio: graph.order < 30 ? 8 : 16,
          slowDown: 5,
          strongGravityMode: false,
        },
      });
    }
    const renderer = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: true,
      labelDensity: 0.12,
      labelGridCellSize: 120,
      labelRenderedSizeThreshold: 7,
      labelColor: { color: '#d6dfec' },
      edgeLabelSize: 10,
      edgeLabelColor: { color: '#aebbd0' },
      defaultNodeColor: '#88a1c7',
      defaultEdgeColor: '#4c586b',
      stagePadding: 54,
      minCameraRatio: 0.05,
      maxCameraRatio: 8,
    });
    renderer.on('clickNode', ({ node }) => {
      setSelectedNodeId(Number(node));
      setSelectedRelationshipId(null);
    });
    renderer.on('clickEdge', ({ edge }) => {
      const relationshipId = Number(graph.getEdgeAttribute(edge, 'relationshipId'));
      setSelectedRelationshipId(relationshipId);
      setSelectedNodeId(null);
    });
    renderer.on('clickStage', () => {
      setSelectedNodeId(null);
      setSelectedRelationshipId(null);
    });
    rendererRef.current = renderer;
    return () => {
      renderer.kill();
      if (rendererRef.current === renderer) rendererRef.current = null;
    };
  }, [
    entities,
    filteredRelationships,
    highlightedRelationshipIds,
    visibleEntityIds,
  ]);

  const findPath = async () => {
    if (!pathSource || !pathTarget) return;
    setWorking(true);
    setOperationError(null);
    try {
      const result = await getGraphPath(
        competitorId,
        Number(pathSource),
        Number(pathTarget),
        pathMode,
      );
      setPath(result);
    } catch (reason) {
      setPath(null);
      setOperationError(reason instanceof Error ? reason.message : 'No path was found.');
    } finally {
      setWorking(false);
    }
  };

  const compareSnapshots = async () => {
    if (!fromSnapshot || !toSnapshot) return;
    setWorking(true);
    setOperationError(null);
    try {
      setDiff(await getGraphDiff(
        competitorId,
        Number(fromSnapshot),
        Number(toSnapshot),
      ));
    } catch (reason) {
      setDiff(null);
      setOperationError(
        reason instanceof Error ? reason.message : 'Snapshot comparison failed.',
      );
    } finally {
      setWorking(false);
    }
  };

  const resetCamera = () => {
    rendererRef.current?.getCamera().animatedReset({ duration: 420 });
  };

  return (
    <section className="graph-studio">
      <header className="graph-studio-command">
        <div className="graph-mode-switch" role="tablist" aria-label="Graph investigation mode">
          {([
            ['explore', 'Explore', 'search'],
            ['path', 'Pathfinder', 'arrow'],
            ['timeline', 'Timeline', 'activity'],
          ] as const).map(([value, text, icon]) => (
            <button
              key={value}
              type="button"
              className={mode === value ? 'active' : ''}
              onClick={() => setMode(value)}
            >
              <Icon name={icon} size={14} />
              {text}
            </button>
          ))}
        </div>
        <div className="graph-export-menu">
          <span>Export</span>
          {(['json', 'csv', 'graphml'] as const).map((format) => (
            <a key={format} href={graphExportUrl(competitorId, format)}>
              {format.toUpperCase()}
            </a>
          ))}
        </div>
      </header>

      {mode === 'explore' ? (
        <div className="graph-tool-row">
          <label className="graph-search">
            <Icon name="search" size={15} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Find an entity, connection, or relationship type"
            />
          </label>
          <label>
            <span>Entity lens</span>
            <select value={entityType} onChange={(event) => setEntityType(event.target.value)}>
              <option value="all">All entities</option>
              {entityTypes.map((type) => <option key={type} value={type}>{label(type)}</option>)}
            </select>
          </label>
          <label>
            <span>Relationship</span>
            <select
              value={relationshipType}
              onChange={(event) => setRelationshipType(event.target.value)}
            >
              <option value="all">All relationships</option>
              {relationshipTypes.map((type) => <option key={type} value={type}>{label(type)}</option>)}
            </select>
          </label>
          <label className="graph-confidence">
            <span>Confidence ≥ {minimumConfidence}%</span>
            <input
              type="range"
              min="0"
              max="95"
              step="5"
              value={minimumConfidence}
              onChange={(event) => setMinimumConfidence(Number(event.target.value))}
            />
          </label>
          <label className="graph-check">
            <input
              type="checkbox"
              checked={showStale}
              onChange={(event) => setShowStale(event.target.checked)}
            />
            Include stale
          </label>
        </div>
      ) : null}

      {mode === 'path' ? (
        <div className="graph-path-command">
          <div>
            <span>Start entity</span>
            <select value={pathSource} onChange={(event) => setPathSource(event.target.value)}>
              <option value="">Choose an entity</option>
              {entities.map((entity) => <option key={entity.id} value={entity.id}>{entity.name}</option>)}
            </select>
          </div>
          <Icon name="arrow" size={16} />
          <div>
            <span>Target entity</span>
            <select value={pathTarget} onChange={(event) => setPathTarget(event.target.value)}>
              <option value="">Choose an entity</option>
              {entities.map((entity) => <option key={entity.id} value={entity.id}>{entity.name}</option>)}
            </select>
          </div>
          <div>
            <span>Path logic</span>
            <select value={pathMode} onChange={(event) => setPathMode(event.target.value as 'strongest' | 'shortest')}>
              <option value="strongest">Strongest evidence</option>
              <option value="shortest">Fewest hops</option>
            </select>
          </div>
          <button
            type="button"
            className="primary-button"
            onClick={() => void findPath()}
            disabled={working || !pathSource || !pathTarget}
          >
            {working ? 'Tracing path' : 'Trace connection'}
          </button>
          {path ? (
            <button type="button" className="text-button" onClick={() => setPath(null)}>
              Clear path
            </button>
          ) : null}
        </div>
      ) : null}

      {mode === 'timeline' ? (
        <div className="graph-path-command">
          <div>
            <span>Earlier snapshot</span>
            <select value={fromSnapshot} onChange={(event) => setFromSnapshot(event.target.value)}>
              <option value="">Choose snapshot</option>
              {statefulSnapshots.map((snapshot) => (
                <option key={snapshot.id} value={snapshot.id}>
                  #{snapshot.id} · {new Date(snapshot.created_at).toLocaleString()}
                </option>
              ))}
            </select>
          </div>
          <Icon name="arrow" size={16} />
          <div>
            <span>Later snapshot</span>
            <select value={toSnapshot} onChange={(event) => setToSnapshot(event.target.value)}>
              <option value="">Choose snapshot</option>
              {statefulSnapshots.map((snapshot) => (
                <option key={snapshot.id} value={snapshot.id}>
                  #{snapshot.id} · {new Date(snapshot.created_at).toLocaleString()}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="primary-button"
            onClick={() => void compareSnapshots()}
            disabled={working || !fromSnapshot || !toSnapshot || fromSnapshot === toSnapshot}
          >
            {working ? 'Comparing graph' : 'Compare snapshots'}
          </button>
          <p>
            {statefulSnapshots.length >= 2
              ? `${statefulSnapshots.length} comparable snapshots`
              : 'Analyze the graph twice to enable temporal comparison.'}
          </p>
        </div>
      ) : null}

      {operationError ? (
        <div className="graph-operation-error">
          <Icon name="error" size={15} />
          {operationError}
        </div>
      ) : null}

      {path ? (
        <div className="graph-result-strip">
          <span>Connection found</span>
          <strong>{path.hop_count} {path.hop_count === 1 ? 'hop' : 'hops'}</strong>
          <p>{path.nodes.map((node) => node.name).join(' → ')}</p>
        </div>
      ) : null}

      {diff ? (
        <div className="graph-diff-strip">
          <article><strong>+{diff.summary.entities_added}</strong><span>entities</span></article>
          <article><strong>+{diff.summary.relationships_added}</strong><span>connections</span></article>
          <article><strong>{diff.summary.relationships_changed}</strong><span>changed</span></article>
          <article><strong>−{diff.summary.relationships_removed}</strong><span>removed</span></article>
          <p>
            Snapshot #{diff.from_snapshot_id} → #{diff.to_snapshot_id}
          </p>
        </div>
      ) : null}

      <div className="graph-studio-stage">
        <div className="graph-canvas-shell">
          <div className="graph-canvas-toolbar">
            <span>
              <i className="live-dot" />
              {visibleEntityIds.size} visible entities · {filteredRelationships.length} connections
            </span>
            <button type="button" onClick={resetCamera}>
              <Icon name="refresh" size={13} />
              Fit graph
            </button>
          </div>
          {visibleEntityIds.size ? (
            <div
              ref={containerRef}
              className="graph-sigma-canvas"
              aria-label={`Interactive graph with ${visibleEntityIds.size} entities and ${filteredRelationships.length} relationships`}
            />
          ) : (
            <div className="graph-empty">
              <Icon name="network" size={24} />
              <strong>No relationships match this lens</strong>
              <p>Reduce the confidence threshold or clear the active filters.</p>
            </div>
          )}
          <footer className="graph-canvas-legend">
            {entityTypes.slice(0, 8).map((type) => (
              <span key={type}><i style={{ background: entityColor(type) }} />{label(type)}</span>
            ))}
            <span className="graph-legend-divider" />
            <span><i className="edge-active" />active</span>
            <span><i className="edge-disputed" />disputed</span>
          </footer>
        </div>

        <aside className="graph-inspector">
          {selectedRelationship ? (
            <>
              <div className="graph-inspector-kicker">
                <span style={{ background: relationshipColor(selectedRelationship) }} />
                Relationship evidence
              </div>
              <h3>{selectedRelationship.source_name}</h3>
              <div className="graph-inspector-relation">
                <Icon name="arrow" size={14} />
                {label(selectedRelationship.relationship_type)}
              </div>
              <h3>{selectedRelationship.target_name}</h3>
              <div className="graph-score-grid">
                <div><strong>{confidence(selectedRelationship.weight)}</strong><span>confidence</span></div>
                <div><strong>{confidence(selectedRelationship.freshness_score)}</strong><span>freshness</span></div>
                <div><strong>{selectedRelationship.source_diversity}</strong><span>source types</span></div>
                <div><strong>{selectedRelationship.contradiction_count}</strong><span>conflicts</span></div>
              </div>
              {selectedRelationship.rationale ? <p>{selectedRelationship.rationale}</p> : null}
              <div className="graph-evidence-list">
                <header>
                  <strong>Source evidence</strong>
                  <span>{selectedRelationship.evidence.length}</span>
                </header>
                {selectedRelationship.evidence.length ? selectedRelationship.evidence.map((evidence) => (
                  <a
                    key={evidence.id}
                    href={evidence.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <span>{evidence.title || new URL(evidence.source_url).hostname}</span>
                    <p>{evidence.snippet || 'Open the preserved source evidence.'}</p>
                    <em>{confidence(evidence.confidence)} · {new Date(evidence.collected_at).toLocaleDateString()}</em>
                  </a>
                )) : <p className="graph-muted">No direct evidence link was preserved for this edge.</p>}
              </div>
            </>
          ) : selectedEntity ? (
            <>
              <div className="graph-inspector-kicker">
                <span style={{ background: entityColor(selectedEntity.entity_type) }} />
                Entity dossier
              </div>
              <h2>{selectedEntity.name}</h2>
              <p className="graph-type-chip">{label(selectedEntity.entity_type)}</p>
              <div className="graph-score-grid">
                <div><strong>{selectedConnections.length}</strong><span>connections</span></div>
                <div><strong>{selectedConnections.reduce((sum, item) => sum + item.evidence_count, 0)}</strong><span>evidence links</span></div>
              </div>
              <div className="graph-connection-list">
                <strong>Connected intelligence</strong>
                {selectedConnections.slice(0, 12).map((relationship) => (
                  <button
                    key={relationship.id}
                    type="button"
                    onClick={() => {
                      setSelectedRelationshipId(relationship.id);
                      setSelectedNodeId(null);
                    }}
                  >
                    <span>{label(relationship.relationship_type)}</span>
                    <strong>
                      {relationship.source_entity_id === selectedEntity.id
                        ? relationship.target_name
                        : relationship.source_name}
                    </strong>
                    <em>{confidence(relationship.weight)}</em>
                  </button>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="graph-inspector-kicker">
                <span className="live-dot" />
                Graph intelligence
              </div>
              <h2>Investigate the network</h2>
              <p>
                Select an entity or relationship to inspect confidence, source diversity,
                contradictions, chronology, and original evidence.
              </p>
              <div className="graph-score-grid">
                <div><strong>{entities.length}</strong><span>entities</span></div>
                <div><strong>{relationships.length}</strong><span>relationships</span></div>
                <div><strong>{intelligence?.component_count ?? 0}</strong><span>components</span></div>
                <div><strong>{intelligence?.disputed_relationships ?? 0}</strong><span>disputed</span></div>
              </div>
              <div className="graph-inspector-guide">
                <article><Icon name="search" size={15} /><span><strong>Explore</strong>Filter the network through investigative lenses.</span></article>
                <article><Icon name="arrow" size={15} /><span><strong>Pathfinder</strong>Explain how any two entities are connected.</span></article>
                <article><Icon name="activity" size={15} /><span><strong>Timeline</strong>Compare relationship snapshots across runs.</span></article>
              </div>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
