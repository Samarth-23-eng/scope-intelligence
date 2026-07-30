'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Icon } from '@/components/Icon';
import { GraphStudio } from '@/components/GraphStudio';
import { useCompanyWorkspace } from '@/components/company/CompanyWorkspace';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricTile,
  PageHeading,
  Panel,
  formatDate,
  percent,
} from '@/components/company/PagePrimitives';
import {
  analyzeRelationships,
  getCompetitorEntities,
  getCompetitorRelationships,
  getGraphSnapshots,
  getRelationshipIntelligence,
  resolveEntities,
} from '@/lib/api';
import type {
  Entity,
  GraphSnapshot,
  Relationship,
  RelationshipIntelligence,
} from '@/lib/types';

type View = 'graph' | 'relationships' | 'entities' | 'quality';

export default function RelationshipsPage() {
  const { competitorId, dataVersion, refreshWorkspace } = useCompanyWorkspace();
  const [entities, setEntities] = useState<Entity[]>([]);
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [intelligence, setIntelligence] = useState<RelationshipIntelligence | null>(null);
  const [snapshots, setSnapshots] = useState<GraphSnapshot[]>([]);
  const [view, setView] = useState<View>('graph');
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [entityRows, relationshipRows, graphIntelligence, graphSnapshots] = await Promise.all([
        getCompetitorEntities(competitorId),
        getCompetitorRelationships(competitorId),
        getRelationshipIntelligence(competitorId),
        getGraphSnapshots(competitorId),
      ]);
      setEntities(entityRows);
      setRelationships(relationshipRows);
      setIntelligence(graphIntelligence);
      setSnapshots(graphSnapshots);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Relationship intelligence is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [competitorId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, dataVersion]);

  const handleResolve = async () => {
    setResolving(true);
    setError(null);
    try {
      await resolveEntities(competitorId);
      await load();
      refreshWorkspace();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Entity resolution failed.');
    } finally {
      setResolving(false);
    }
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      setIntelligence(await analyzeRelationships(competitorId));
      setRelationships(await getCompetitorRelationships(competitorId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Graph analysis failed.');
    } finally {
      setAnalyzing(false);
    }
  };

  const entityCounts = useMemo(
    () => entities.reduce<Record<string, number>>((counts, entity) => {
      counts[entity.entity_type] = (counts[entity.entity_type] ?? 0) + 1;
      return counts;
    }, {}),
    [entities],
  );
  const activeRelationships = relationships.filter((item) => item.status === 'active').length;
  const highRisk = relationships.filter((item) => ['high', 'critical'].includes(item.risk_level)).length;

  return (
    <main className="company-page relationship-page">
      <PageHeading
        eyebrow="RELATIONSHIP INTELLIGENCE"
        title="Entity and influence map"
        description="Trace people, products, technologies, partners, investors, and organizations—then inspect the evidence behind every connection."
        actions={
          <>
            <button type="button" className="secondary-button" onClick={() => void handleAnalyze()} disabled={analyzing || loading}>
              <Icon name="activity" size={15} />
              {analyzing ? 'Analyzing graph' : 'Analyze graph'}
            </button>
            <button type="button" className="primary-button" onClick={() => void handleResolve()} disabled={resolving || loading}>
              <Icon name="network" size={15} />
              {resolving ? 'Resolving entities' : 'Resolve relationships'}
            </button>
          </>
        }
      />

      <section className="workspace-metric-grid">
        <MetricTile label="Resolved entities" value={entities.length} note={`${Object.keys(entityCounts).length} entity classes`} icon="building" />
        <MetricTile label="Relationships" value={relationships.length} note={`${activeRelationships} currently active`} icon="network" />
        <MetricTile label="Graph components" value={intelligence?.component_count ?? 0} note={`${intelligence?.metrics.isolated_entities ?? 0} isolated entities`} icon="layers" />
        <MetricTile label="Quality risks" value={(intelligence?.weak_relationships ?? 0) + (intelligence?.disputed_relationships ?? 0)} note={`${highRisk} high-risk edges`} icon="shield" tone={highRisk ? 'danger' : 'neutral'} />
      </section>

      <div className="view-switcher" role="tablist" aria-label="Relationship views">
        {([
          ['graph', 'Graph explorer', null],
          ['relationships', 'Relationship ledger', relationships.length],
          ['entities', 'Entity registry', entities.length],
          ['quality', 'Graph quality', null],
        ] as const).map(([id, label, count]) => (
          <button key={id} type="button" role="tab" aria-selected={view === id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>
            {label}{count !== null ? <span>{count}</span> : null}
          </button>
        ))}
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingState label="Building relationship workspace" /> : null}

      {!loading && view === 'graph' ? (
        <GraphStudio
          competitorId={competitorId}
          entities={entities}
          relationships={relationships}
          intelligence={intelligence}
          snapshots={snapshots}
        />
      ) : null}

      {!loading && view === 'relationships' ? (
        <Panel>
          {relationships.length ? (
            <div className="relationship-ledger">
              {relationships.map((relationship) => (
                <article key={relationship.id}>
                  <div className="relationship-parties">
                    <div><span>{relationship.source_type}</span><strong>{relationship.source_name}</strong></div>
                    <div className="relationship-verb"><Icon name="arrow" size={16} /><span>{relationship.relationship_type.replaceAll('_', ' ')}</span></div>
                    <div><span>{relationship.target_type}</span><strong>{relationship.target_name}</strong></div>
                  </div>
                  <div className="relationship-quality">
                    <span className={`relationship-status ${relationship.status}`}>{relationship.status}</span>
                    <span>{percent(relationship.weight)} confidence</span>
                    <span>{relationship.evidence_count} evidence links</span>
                    <span>{relationship.source_diversity} source types</span>
                  </div>
                  {relationship.rationale ? <p>{relationship.rationale}</p> : null}
                  <footer>
                    <span>Last observed {formatDate(relationship.last_seen_at)}</span>
                    <span className={`risk-label ${relationship.risk_level}`}>{relationship.risk_level} risk</span>
                  </footer>
                </article>
              ))}
            </div>
          ) : <EmptyState icon="network" title="No relationships resolved" description="Resolve entities after collecting evidence to build the relationship ledger." />}
        </Panel>
      ) : null}

      {!loading && view === 'entities' ? (
        <Panel>
          {entities.length ? (
            <div className="entity-registry">
              {Object.entries(entityCounts).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
                <div className="entity-type-summary" key={type}><span>{type.replaceAll('_', ' ')}</span><strong>{count}</strong></div>
              ))}
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>Entity</th><th>Type</th><th>Created</th><th>Metadata</th></tr></thead>
                  <tbody>
                    {entities.map((entity) => (
                      <tr key={entity.id}>
                        <td><strong>{entity.name}</strong><small>Entity #{entity.id}</small></td>
                        <td><span className="type-label">{entity.entity_type.replaceAll('_', ' ')}</span></td>
                        <td>{formatDate(entity.created_at)}</td>
                        <td><small>{Object.keys(entity.metadata).slice(0, 3).join(' · ') || 'No additional attributes'}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : <EmptyState title="No entities registered" description="Entity resolution will turn names in collected evidence into a structured registry." />}
        </Panel>
      ) : null}

      {!loading && view === 'quality' ? (
        <div className="quality-layout">
          <Panel eyebrow="GRAPH HEALTH" title="Evidence quality">
            <div className="quality-score-list">
              {[
                ['Disputed relationships', intelligence?.disputed_relationships ?? 0, relationships.length],
                ['Weak relationships', intelligence?.weak_relationships ?? 0, relationships.length],
                ['Duplicate candidates', intelligence?.metrics.duplicate_candidates?.length ?? 0, entities.length],
                ['Isolated entities', intelligence?.metrics.isolated_entities ?? 0, entities.length],
              ].map(([label, count, total]) => {
                const width = total ? Math.min(100, (Number(count) / Number(total)) * 100) : 0;
                return <div key={String(label)}><span><strong>{label}</strong><em>{count}</em></span><div><i style={{ width: `${width}%` }} /></div></div>;
              })}
            </div>
          </Panel>
          <Panel eyebrow="CENTRALITY" title="Strategic nodes">
            {intelligence?.metrics.strategic_nodes?.length ? (
              <div className="strategic-node-list">
                {intelligence.metrics.strategic_nodes.slice(0, 8).map((node, index) => (
                  <article key={node.entity_id}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{node.name}</strong><p>{node.entity_type}</p></div><em>{node.degree} links</em></article>
                ))}
              </div>
            ) : <EmptyState title="No centrality analysis yet" description="Analyze the graph to identify the most strategically connected entities." />}
          </Panel>
        </div>
      ) : null}
    </main>
  );
}
