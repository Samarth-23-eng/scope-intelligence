'use client';

import { useMemo, useState } from 'react';

import { Entity, Relationship, RelationshipIntelligence } from '@/lib/types';

interface RelationshipGraphProps {
  entities: Entity[];
  relationships: Relationship[];
  intelligence: RelationshipIntelligence | null;
  resolving: boolean;
  onResolve: () => void;
}

interface GraphNode {
  id: number;
  name: string;
  type: string;
  degree: number;
  root: boolean;
  x: number;
  y: number;
}

const WIDTH = 920;
const HEIGHT = 560;
const CENTER_X = WIDTH / 2;
const CENTER_Y = HEIGHT / 2;

const ENTITY_COLORS: Record<string, string> = {
  company: '#5b8def',
  person: '#60a5fa',
  executive: '#60a5fa',
  product: '#8cb4f4',
  subsidiary: '#fb7185',
  competitor: '#f87171',
  partner: '#34d399',
  technology: '#22d3ee',
  customer: '#fbbf24',
  integration: '#2dd4bf',
  location: '#94a3b8',
  investor: '#e879f9',
};

const EDGE_COLORS: Record<string, string> = {
  employs: '#60a5fa',
  offers: '#8cb4f4',
  owns: '#fb7185',
  competes_with: '#f87171',
  partners_with: '#34d399',
  uses: '#22d3ee',
  integrates_with: '#2dd4bf',
  serves: '#fbbf24',
  invested_in: '#e879f9',
  located_in: '#94a3b8',
  founded_by: '#818cf8',
  acquired: '#fb7185',
};

function truncateLabel(value: string, maximum = 22) {
  return value.length > maximum ? `${value.slice(0, maximum - 1)}…` : value;
}

function formatRelationship(value: string) {
  return value.replaceAll('_', ' ');
}

export function RelationshipGraph({
  entities,
  relationships,
  intelligence,
  resolving,
  onResolve,
}: RelationshipGraphProps) {
  const [query, setQuery] = useState('');
  const [relationshipType, setRelationshipType] = useState('all');
  const [entityType, setEntityType] = useState('all');
  const [minimumConfidence, setMinimumConfidence] = useState(40);
  const [includeStale, setIncludeStale] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [selectedRelationshipId, setSelectedRelationshipId] = useState<number | null>(null);

  const relationshipTypes = useMemo(
    () => Array.from(new Set(relationships.map((item) => item.relationship_type))).sort(),
    [relationships]
  );
  const entityTypes = useMemo(
    () => Array.from(new Set(entities.map((item) => item.entity_type))).sort(),
    [entities]
  );

  const filteredRelationships = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return relationships.filter((relationship) => {
      if (!includeStale && relationship.status !== 'active') return false;
      if (relationship.weight * 100 < minimumConfidence) return false;
      if (relationshipType !== 'all' && relationship.relationship_type !== relationshipType) {
        return false;
      }
      if (
        entityType !== 'all'
        && relationship.source_type !== entityType
        && relationship.target_type !== entityType
      ) {
        return false;
      }
      if (
        normalizedQuery
        && !relationship.source_name.toLocaleLowerCase().includes(normalizedQuery)
        && !relationship.target_name.toLocaleLowerCase().includes(normalizedQuery)
        && !relationship.relationship_type.toLocaleLowerCase().includes(normalizedQuery)
      ) {
        return false;
      }
      return true;
    });
  }, [
    relationships,
    includeStale,
    minimumConfidence,
    relationshipType,
    entityType,
    query,
  ]);

  const graph = useMemo(() => {
    const entityById = new Map(entities.map((entity) => [entity.id, entity]));
    const degreeById = new Map<number, number>();
    const nodeIds = new Set<number>();
    for (const relationship of filteredRelationships) {
      nodeIds.add(relationship.source_entity_id);
      nodeIds.add(relationship.target_entity_id);
      degreeById.set(
        relationship.source_entity_id,
        (degreeById.get(relationship.source_entity_id) ?? 0) + 1
      );
      degreeById.set(
        relationship.target_entity_id,
        (degreeById.get(relationship.target_entity_id) ?? 0) + 1
      );
    }

    const rootEntity = entities.find((entity) => entity.metadata.root === true)
      ?? entities
        .filter((entity) => nodeIds.has(entity.id))
        .sort((a, b) => (degreeById.get(b.id) ?? 0) - (degreeById.get(a.id) ?? 0))[0];
    if (rootEntity) nodeIds.add(rootEntity.id);

    const peripheral = Array.from(nodeIds)
      .filter((id) => id !== rootEntity?.id)
      .map((id) => entityById.get(id))
      .filter((entity): entity is Entity => Boolean(entity))
      .sort((a, b) => (
        (degreeById.get(b.id) ?? 0) - (degreeById.get(a.id) ?? 0)
        || a.entity_type.localeCompare(b.entity_type)
        || a.name.localeCompare(b.name)
      ));

    const nodes: GraphNode[] = [];
    if (rootEntity) {
      nodes.push({
        id: rootEntity.id,
        name: rootEntity.name,
        type: rootEntity.entity_type,
        degree: degreeById.get(rootEntity.id) ?? 0,
        root: true,
        x: CENTER_X,
        y: CENTER_Y,
      });
    }
    const ringCount = Math.min(4, Math.max(1, Math.ceil(peripheral.length / 12)));
    const itemsPerRing = Math.ceil(peripheral.length / ringCount);
    peripheral.forEach((entity, index) => {
      const ring = Math.floor(index / itemsPerRing);
      const indexInRing = index % itemsPerRing;
      const goldenAngle = Math.PI * (3 - Math.sqrt(5));
      const angle = -Math.PI / 2 + indexInRing * goldenAngle + ring * 0.35;
      const radius = ringCount === 1
        ? 175
        : 105 + (ring / (ringCount - 1)) * 125;
      nodes.push({
        id: entity.id,
        name: entity.name,
        type: entity.entity_type,
        degree: degreeById.get(entity.id) ?? 0,
        root: false,
        x: CENTER_X + Math.cos(angle) * radius,
        y: CENTER_Y + Math.sin(angle) * radius,
      });
    });
    return { nodes, nodeById: new Map(nodes.map((node) => [node.id, node])) };
  }, [entities, filteredRelationships]);

  const selectedRelationship = filteredRelationships.find(
    (relationship) => relationship.id === selectedRelationshipId
  ) ?? null;
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedNodeRelationships = selectedNode
    ? filteredRelationships.filter(
        (relationship) => (
          relationship.source_entity_id === selectedNode.id
          || relationship.target_entity_id === selectedNode.id
        )
      )
    : [];

  const averageConfidence = filteredRelationships.length
    ? filteredRelationships.reduce((total, relationship) => total + relationship.weight, 0)
      / filteredRelationships.length
    : 0;
  const citedRelationships = filteredRelationships.filter(
    (relationship) => relationship.evidence_count > 0
  ).length;

  const selectNode = (id: number) => {
    setSelectedNodeId(id);
    setSelectedRelationshipId(null);
  };
  const selectRelationship = (id: number) => {
    setSelectedRelationshipId(id);
    setSelectedNodeId(null);
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-[#0d0f16] border border-[#242424] rounded-lg p-4">
          <div className="text-2xl font-semibold text-white">{graph.nodes.length}</div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Visible entities</div>
        </div>
        <div className="bg-[#0d0f16] border border-[#242424] rounded-lg p-4">
          <div className="text-2xl font-semibold text-white">{filteredRelationships.length}</div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Visible relationships</div>
        </div>
        <div className="bg-[#0d0f16] border border-[#242424] rounded-lg p-4">
          <div className="text-2xl font-semibold text-white">
            {Math.round(averageConfidence * 100)}%
          </div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Average confidence</div>
        </div>
        <div className="bg-[#0d0f16] border border-[#242424] rounded-lg p-4">
          <div className="text-2xl font-semibold text-white">
            {filteredRelationships.length
              ? Math.round((citedRelationships / filteredRelationships.length) * 100)
              : 0}%
          </div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Evidence coverage</div>
        </div>
      </div>

      {intelligence && intelligence.snapshot_id && (
        <div className="bg-[#0d0f16] border border-[#242424] rounded-lg p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.18em] text-blue-300">
                Phase 3 intelligence fusion
              </div>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">
                Confidence now combines source reliability, independent corroboration,
                freshness, and contradictory observations.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(['low', 'medium', 'high', 'critical'] as const).map((level) => (
                <div key={level} className="rounded-lg border border-[#282a32] bg-[#090a0e] px-3 py-2">
                  <div className="font-mono text-lg text-white">
                    {intelligence.metrics.risk_distribution[level] ?? 0}
                  </div>
                  <div className="text-[10px] uppercase tracking-wide text-gray-500">
                    {level} risk
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">
                Strategic entities
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {intelligence.metrics.strategic_nodes.slice(0, 8).map((node) => (
                  <button
                    key={node.entity_id}
                    type="button"
                    onClick={() => selectNode(node.entity_id)}
                    className="rounded-full border border-blue-400/20 bg-blue-400/5 px-3 py-1.5 text-xs text-blue-200 hover:border-blue-300/50"
                    title={`${node.degree} connections · rank ${node.page_rank.toFixed(3)}`}
                  >
                    {node.name}
                  </button>
                ))}
                {intelligence.metrics.strategic_nodes.length === 0 && (
                  <span className="text-xs text-gray-600">No connected entities yet.</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">
                Identity review
              </div>
              <p className="mt-2 text-sm text-gray-400">
                {intelligence.metrics.duplicate_candidates.length > 0
                  ? `${intelligence.metrics.duplicate_candidates.length} possible duplicate entity groups need review.`
                  : `No duplicate identity candidates detected across ${intelligence.metrics.alias_count ?? 0} aliases.`}
              </p>
              <p className="mt-1 text-xs text-gray-600">
                {intelligence.component_count} graph components · {intelligence.weak_relationships} weak
                edges · {intelligence.disputed_relationships} disputed edges
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="bg-[#0d0f16] border border-[#242424] rounded-lg p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-[1.4fr_1fr_1fr_1.2fr_auto] gap-3 items-end">
          <label className="text-xs text-gray-400">
            Search network
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Entity or relationship"
              className="mt-1.5 w-full bg-[#090909] border border-[#333333] rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-[#5b8def]"
            />
          </label>
          <label className="text-xs text-gray-400">
            Relationship
            <select
              value={relationshipType}
              onChange={(event) => setRelationshipType(event.target.value)}
              className="mt-1.5 w-full bg-[#090909] border border-[#333333] rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-[#5b8def]"
            >
              <option value="all">All relationships</option>
              {relationshipTypes.map((type) => (
                <option key={type} value={type}>{formatRelationship(type)}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-400">
            Entity type
            <select
              value={entityType}
              onChange={(event) => setEntityType(event.target.value)}
              className="mt-1.5 w-full bg-[#090909] border border-[#333333] rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-[#5b8def]"
            >
              <option value="all">All entity types</option>
              {entityTypes.map((type) => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-400">
            Minimum confidence: {minimumConfidence}%
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={minimumConfidence}
              onChange={(event) => setMinimumConfidence(Number(event.target.value))}
              className="mt-3 w-full accent-[#5b8def]"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-400 pb-2 whitespace-nowrap">
            <input
              type="checkbox"
              checked={includeStale}
              onChange={(event) => setIncludeStale(event.target.checked)}
              className="accent-[#5b8def]"
            />
            Include stale
          </label>
        </div>
      </div>

      {relationships.length > 0 ? (
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)] gap-5">
          <div className="bg-[#0c0c0c] border border-[#242424] rounded-lg overflow-hidden">
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              role="img"
              aria-label={`Relationship network with ${graph.nodes.length} entities and ${filteredRelationships.length} relationships`}
              className="w-full min-h-[420px]"
            >
              <title>Competitor relationship network</title>
              <desc>
                Entities are arranged around the monitored company. Line thickness represents
                relationship confidence. Select a node or line for evidence and details.
              </desc>
              <defs>
                <marker
                  id="relationship-arrow"
                  markerWidth="8"
                  markerHeight="8"
                  refX="7"
                  refY="4"
                  orient="auto"
                  markerUnits="strokeWidth"
                >
                  <path d="M0,0 L8,4 L0,8 Z" fill="#6b7280" />
                </marker>
              </defs>

              {filteredRelationships.map((relationship) => {
                const source = graph.nodeById.get(relationship.source_entity_id);
                const target = graph.nodeById.get(relationship.target_entity_id);
                if (!source || !target) return null;
                const selected = relationship.id === selectedRelationshipId;
                return (
                  <g
                    key={relationship.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${source.name} ${formatRelationship(relationship.relationship_type)} ${target.name}, ${Math.round(relationship.weight * 100)} percent confidence`}
                    onClick={() => selectRelationship(relationship.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        selectRelationship(relationship.id);
                      }
                    }}
                    className="cursor-pointer outline-none"
                  >
                    <line
                      x1={source.x}
                      y1={source.y}
                      x2={target.x}
                      y2={target.y}
                      stroke="transparent"
                      strokeWidth={18}
                      pointerEvents="stroke"
                    />
                    <line
                      x1={source.x}
                      y1={source.y}
                      x2={target.x}
                      y2={target.y}
                      stroke={EDGE_COLORS[relationship.relationship_type] ?? '#6b7280'}
                      strokeWidth={selected ? 6 : 1.5 + relationship.weight * 3}
                      strokeOpacity={selected ? 1 : 0.58}
                      markerEnd="url(#relationship-arrow)"
                      pointerEvents="none"
                    />
                    <circle
                      cx={(source.x + target.x) / 2}
                      cy={(source.y + target.y) / 2}
                      r={12}
                      fill="#ffffff"
                      fillOpacity={0.001}
                      pointerEvents="all"
                    />
                  </g>
                );
              })}

              {graph.nodes.map((node) => {
                const selected = node.id === selectedNodeId;
                const radius = node.root ? 30 : Math.min(24, 14 + node.degree * 1.6);
                const color = ENTITY_COLORS[node.type] ?? '#9ca3af';
                return (
                  <g
                    key={node.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${node.name}, ${node.type}, ${node.degree} relationships`}
                    onClick={() => selectNode(node.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        selectNode(node.id);
                      }
                    }}
                    className="cursor-pointer outline-none"
                  >
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={radius}
                      fill={color}
                      fillOpacity={node.root ? 0.95 : 0.78}
                      stroke={selected ? '#ffffff' : color}
                      strokeWidth={selected ? 4 : 1.5}
                    />
                    <text
                      x={node.x}
                      y={node.y + radius + 16}
                      textAnchor="middle"
                      fill="#f3f4f6"
                      fontSize="12"
                      fontWeight={node.root ? 600 : 500}
                    >
                      {truncateLabel(node.name)}
                    </text>
                    <text
                      x={node.x}
                      y={node.y + radius + 30}
                      textAnchor="middle"
                      fill="#6b7280"
                      fontSize="10"
                    >
                      {node.type}
                    </text>
                  </g>
                );
              })}
            </svg>

            <div className="border-t border-[#222636] px-4 py-3 space-y-2">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <span className="text-[10px] uppercase tracking-wide text-gray-600">
                  Entity types
                </span>
                {Array.from(new Set(graph.nodes.map((node) => node.type))).sort().map((type) => (
                  <div key={type} className="flex items-center gap-2 text-xs text-gray-400">
                    <span
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: ENTITY_COLORS[type] ?? '#9ca3af' }}
                    />
                    <span>{type}</span>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <span className="text-[10px] uppercase tracking-wide text-gray-600">
                  Connections
                </span>
                {Array.from(
                  new Set(filteredRelationships.map((item) => item.relationship_type))
                ).sort().map((type) => (
                  <div key={type} className="flex items-center gap-2 text-xs text-gray-400">
                    <span
                      className="w-5 border-t-2"
                      style={{ borderColor: EDGE_COLORS[type] ?? '#6b7280' }}
                    />
                    <span>{formatRelationship(type)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <aside className="bg-[#0d0f16] border border-[#242424] rounded-lg p-5 min-h-[420px]">
            {selectedRelationship ? (
              <div>
                <div className="text-xs uppercase tracking-wide text-[#5b8def] mb-2">
                  Relationship
                </div>
                <h3 className="text-lg font-semibold text-white">
                  {selectedRelationship.source_name}
                  <span className="text-gray-600 mx-2" aria-hidden="true">→</span>
                  {selectedRelationship.target_name}
                </h3>
                <div className="mt-2 text-sm text-gray-400">
                  {formatRelationship(selectedRelationship.relationship_type)}
                </div>

                <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-gray-500">Confidence</dt>
                    <dd className="text-white font-mono">
                      {Math.round(selectedRelationship.weight * 100)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-gray-500">Evidence sources</dt>
                    <dd className="text-white font-mono">{selectedRelationship.evidence_count}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-gray-500">Corroboration</dt>
                    <dd className="text-white font-mono">
                      {Math.round(selectedRelationship.corroboration_score * 100)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-gray-500">Independent sources</dt>
                    <dd className="text-white font-mono">{selectedRelationship.source_diversity}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-gray-500">Freshness</dt>
                    <dd className="text-white font-mono">
                      {Math.round(selectedRelationship.freshness_score * 100)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-gray-500">Assessment risk</dt>
                    <dd className="text-white capitalize">{selectedRelationship.risk_level}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-gray-500">Status</dt>
                    <dd className="text-white capitalize">{selectedRelationship.status}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-gray-500">Method</dt>
                    <dd className="text-white">{formatRelationship(selectedRelationship.extraction_method)}</dd>
                  </div>
                </dl>

                {selectedRelationship.rationale && (
                  <div className="mt-5">
                    <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">
                      Why this connection exists
                    </div>
                    <p className="text-sm text-gray-300 leading-relaxed">
                      {selectedRelationship.rationale}
                    </p>
                  </div>
                )}

                <div className="mt-5">
                  <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">
                    Supporting evidence
                  </div>
                  {selectedRelationship.evidence.length > 0 ? (
                    <div className="space-y-3">
                      {selectedRelationship.evidence.map((evidence) => (
                        <a
                          key={evidence.id}
                          href={evidence.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block rounded-lg border border-[#2a2a2a] p-3 hover:border-[#5b8def]/60 transition-colors"
                        >
                          <div className="text-sm font-medium text-white">
                            {evidence.title || evidence.source_url}
                          </div>
                          {evidence.snippet && (
                            <p className="mt-1 text-xs text-gray-500 line-clamp-3">
                              {evidence.snippet}
                            </p>
                          )}
                          <div className="mt-2 text-[11px] text-gray-600">
                            {Math.round(evidence.confidence * 100)}% source confidence ·{' '}
                            {new Date(evidence.collected_at).toLocaleDateString()}
                          </div>
                        </a>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-amber-300/80">
                      Legacy relationship without a source citation. Re-run relationship
                      resolution after collecting current website evidence.
                    </p>
                  )}
                </div>
              </div>
            ) : selectedNode ? (
              <div>
                <div className="text-xs uppercase tracking-wide text-[#5b8def] mb-2">
                  {selectedNode.type}
                </div>
                <h3 className="text-lg font-semibold text-white">{selectedNode.name}</h3>
                <p className="mt-2 text-sm text-gray-400">
                  {selectedNode.degree} visible relationship{selectedNode.degree === 1 ? '' : 's'}
                </p>
                <div className="mt-5 space-y-2">
                  {selectedNodeRelationships.map((relationship) => (
                    <button
                      key={relationship.id}
                      onClick={() => selectRelationship(relationship.id)}
                      className="w-full text-left rounded-lg border border-[#2a2a2a] p-3 hover:border-[#5b8def]/60"
                    >
                      <div className="text-xs text-gray-500">
                        {relationship.source_entity_id === selectedNode.id
                          ? 'Outgoing'
                          : 'Incoming'}
                        {' · '}
                        {formatRelationship(relationship.relationship_type)}
                      </div>
                      <div className="mt-1 text-sm text-white">
                        {relationship.source_name}
                        <span className="text-gray-600 mx-2" aria-hidden="true">→</span>
                        {relationship.target_name}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center">
                <div className="w-12 h-12 rounded-full bg-[#5b8def]/10 flex items-center justify-center text-[#5b8def] text-xl mb-4">
                  ↗
                </div>
                <h3 className="text-lg font-medium text-white">Explore the network</h3>
                <p className="mt-2 text-sm text-gray-500 max-w-xs">
                  Select a node to see its connections or select a line to inspect confidence,
                  provenance, and source evidence.
                </p>
              </div>
            )}
          </aside>
        </div>
      ) : (
        <div className="bg-[#0d0f16] border border-[#222636] rounded-lg py-14 text-center">
          <h3 className="text-lg font-medium text-white">No relationship network yet</h3>
          <p className="mt-2 text-sm text-gray-500">
            Collect current evidence, then resolve entities to build the graph.
          </p>
          <button
            onClick={onResolve}
            disabled={resolving}
            className="mt-5 px-4 py-2 bg-[#5b8def] hover:bg-[#4776c7] text-white rounded-lg disabled:opacity-50"
          >
            {resolving ? 'Resolving relationships...' : 'Build relationship network'}
          </button>
        </div>
      )}

      {filteredRelationships.length > 0 && (
        <div className="bg-[#0d0f16] border border-[#242424] rounded-lg overflow-hidden">
          <div className="px-5 py-4 border-b border-[#242424] flex items-center justify-between">
            <h3 className="font-medium text-white">Relationship inventory</h3>
            <button
              onClick={onResolve}
              disabled={resolving}
              className="px-3 py-1.5 bg-[#151823] hover:bg-[#1d2130] text-sm text-white rounded-lg disabled:opacity-50"
            >
              {resolving ? 'Refreshing...' : 'Refresh from evidence'}
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[#080a10] text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-5 py-3 text-left">Connection</th>
                  <th className="px-5 py-3 text-left">Type</th>
                  <th className="px-5 py-3 text-right">Confidence</th>
                  <th className="px-5 py-3 text-right">Evidence</th>
                  <th className="px-5 py-3 text-left">Last seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#222222]">
                {filteredRelationships.map((relationship) => (
                  <tr
                    key={relationship.id}
                    onClick={() => selectRelationship(relationship.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        selectRelationship(relationship.id);
                      }
                    }}
                    tabIndex={0}
                    aria-label={`Inspect ${relationship.source_name} to ${relationship.target_name}`}
                    className="hover:bg-[#171717] focus:bg-[#171717] focus:outline-none focus:ring-1 focus:ring-inset focus:ring-[#5b8def] cursor-pointer"
                  >
                    <td className="px-5 py-3 text-white">
                      {relationship.source_name}
                      <span className="text-gray-600 mx-2" aria-hidden="true">→</span>
                      {relationship.target_name}
                    </td>
                    <td className="px-5 py-3 text-gray-400">
                      {formatRelationship(relationship.relationship_type)}
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-gray-300">
                      {Math.round(relationship.weight * 100)}%
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-gray-300">
                      {relationship.evidence_count}
                    </td>
                    <td className="px-5 py-3 text-gray-500 font-mono">
                      {new Date(relationship.last_seen_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
