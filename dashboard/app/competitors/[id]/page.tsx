'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { Icon } from '@/components/Icon';
import { useCompanyWorkspace } from '@/components/company/CompanyWorkspace';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricTile,
  PageHeading,
  Panel,
  SectionLink,
  formatDate,
  percent,
} from '@/components/company/PagePrimitives';
import {
  getCompetitorPredictions,
  getCompetitorSignals,
  getCompetitorSummary,
  getEvidenceOverview,
  getRelationshipIntelligence,
} from '@/lib/api';
import type {
  EvidenceOverview,
  Insight,
  Prediction,
  RelationshipIntelligence,
  Signal,
} from '@/lib/types';

function InlineSummary({ text }: { text: string }) {
  return (
    <>
      {text.split('**').map((part, index) =>
        index % 2 ? <strong key={`${part}-${index}`}>{part}</strong> : part,
      )}
    </>
  );
}

function ExecutiveSummary({ text }: { text: string }) {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  return (
    <div className="executive-summary">
      {lines.map((line, index) => {
        const normalized = line.replace(/^#+\s*/, '');
        if (line.startsWith('#')) {
          return <h4 key={`${line}-${index}`}><InlineSummary text={normalized} /></h4>;
        }
        if (/^[-•]\s/.test(line)) {
          return (
            <div className="summary-point" key={`${line}-${index}`}>
              <span />
              <p><InlineSummary text={line.replace(/^[-•]\s*/, '')} /></p>
            </div>
          );
        }
        return <p key={`${line}-${index}`}><InlineSummary text={line} /></p>;
      })}
    </div>
  );
}

export default function CompanyOverviewPage() {
  const {
    competitorId,
    competitor,
    loading: companyLoading,
    dataVersion,
    pipelineRunning,
    runCollection,
  } = useCompanyWorkspace();
  const [summary, setSummary] = useState<Insight | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [evidence, setEvidence] = useState<EvidenceOverview | null>(null);
  const [relationships, setRelationships] = useState<RelationshipIntelligence | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const results = await Promise.allSettled([
      getCompetitorSummary(competitorId),
      getCompetitorSignals(competitorId),
      getCompetitorPredictions(competitorId),
      getEvidenceOverview(competitorId),
      getRelationshipIntelligence(competitorId),
    ]);

    if (results[0].status === 'fulfilled') {
      setSummary('id' in results[0].value ? results[0].value : null);
    }
    if (results[1].status === 'fulfilled') setSignals(results[1].value);
    if (results[2].status === 'fulfilled') setPredictions(results[2].value);
    if (results[3].status === 'fulfilled') setEvidence(results[3].value);
    if (results[4].status === 'fulfilled') setRelationships(results[4].value);

    const failures = results.filter((result) => result.status === 'rejected');
    if (failures.length === results.length) {
      const reason = failures[0].reason;
      setError(reason instanceof Error ? reason.message : 'Company intelligence is unavailable.');
    } else if (failures.length) {
      setError(`${failures.length} supporting data source${failures.length === 1 ? '' : 's'} could not be loaded.`);
    }
    setLoading(false);
  }, [competitorId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, dataVersion]);

  const criticalSignals = signals.filter(
    (signal) => signal.severity === 'critical' || signal.severity === 'high',
  );
  const latestSignals = [...signals]
    .sort((a, b) => Date.parse(b.detected_at) - Date.parse(a.detected_at))
    .slice(0, 4);
  const latestPredictions = [...predictions]
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
    .slice(0, 3);
  const basePath = `/competitors/${competitorId}`;

  return (
    <main className="company-page">
      <PageHeading
        eyebrow="COMPANY OVERVIEW"
        title="Decision brief"
        description="A concise view of the strongest evidence, priority signals, forecasts, and research coverage for this company."
        actions={
          <button type="button" className="secondary-button" onClick={() => void load()} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh brief
          </button>
        }
      />

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      {companyLoading || loading ? (
        <LoadingState label="Assembling company brief" />
      ) : (
        <>
          <section className="workspace-metric-grid">
            <MetricTile
              label="Evidence documents"
              value={evidence?.documents ?? 0}
              note={`${evidence?.indexed_chunks ?? 0} searchable passages`}
              icon="database"
              tone={(evidence?.documents ?? 0) > 0 ? 'good' : 'warning'}
            />
            <MetricTile
              label="Citation coverage"
              value={percent(evidence?.citation_coverage)}
              note={`${evidence?.cited_claims ?? 0} of ${evidence?.claims ?? 0} claims cited`}
              icon="shield"
              tone={(evidence?.citation_coverage ?? 0) >= 0.7 ? 'good' : 'warning'}
            />
            <MetricTile
              label="Priority signals"
              value={criticalSignals.length}
              note={`${signals.length} signals in total`}
              icon="activity"
              tone={criticalSignals.length > 0 ? 'warning' : 'neutral'}
            />
            <MetricTile
              label="Mapped relationships"
              value={relationships?.relationship_count ?? 0}
              note={`${relationships?.entity_count ?? 0} resolved entities`}
              icon="network"
              tone={(relationships?.disputed_relationships ?? 0) > 0 ? 'warning' : 'neutral'}
            />
          </section>

          <div className="overview-layout">
            <Panel
              eyebrow="EXECUTIVE ASSESSMENT"
              title="Current intelligence brief"
              className="overview-summary-panel"
              action={
                summary ? (
                  <span className="confidence-pill">
                    {percent(summary.confidence)} confidence
                  </span>
                ) : null
              }
            >
              {summary ? (
                <>
                  <ExecutiveSummary text={summary.summary} />
                  <div className="panel-footnote">
                    <Icon name="check" size={14} />
                    Generated {formatDate(summary.created_at, true)}
                  </div>
                </>
              ) : (
                <EmptyState
                  icon="document"
                  title="No executive brief yet"
                  description="Run the collection pipeline to gather evidence and generate a grounded company assessment."
                  action={
                    <button
                      type="button"
                      className="primary-button"
                      disabled={pipelineRunning}
                      onClick={() => void runCollection()}
                    >
                      <Icon name="play" size={15} />
                      {pipelineRunning ? 'Collection running' : 'Build first brief'}
                    </button>
                  }
                />
              )}
            </Panel>

            <div className="overview-side-stack">
              <Panel
                eyebrow="IDENTITY"
                title="Company profile"
                action={<span className={`identity-badge ${competitor?.domain_verified ? 'verified' : ''}`}>
                  {competitor?.domain_verified ? 'Verified identity' : 'Name-first identity'}
                </span>}
              >
                <dl className="profile-facts">
                  <div><dt>Official website</dt><dd>{competitor?.website || competitor?.domain || 'Not resolved'}</dd></div>
                  <div><dt>Headquarters</dt><dd>{competitor?.hq || 'Not established'}</dd></div>
                  <div><dt>Founded</dt><dd>{competitor?.founded || 'Not established'}</dd></div>
                  <div><dt>Discovery state</dt><dd>{competitor?.discovery_status?.replaceAll('_', ' ') || 'Unknown'}</dd></div>
                </dl>
              </Panel>

              <Panel eyebrow="WORKSPACE" title="Continue analysis">
                <div className="section-link-list">
                  <SectionLink href={`${basePath}/research`} icon="spark" title="Open research desk" description="Ask multi-step research questions" />
                  <SectionLink href={`${basePath}/evidence`} icon="book" title="Inspect evidence" description="Search source documents and claims" />
                  <SectionLink href={`${basePath}/relationships`} icon="network" title="Explore entity graph" description="Trace people, products, and partners" />
                </div>
              </Panel>
            </div>
          </div>

          <div className="overview-lower-grid">
            <Panel
              eyebrow="PRIORITY WATCH"
              title="Recent signals"
              action={<Link href={`${basePath}/intelligence`} className="text-link">View all <Icon name="arrow" size={14} /></Link>}
            >
              {latestSignals.length ? (
                <div className="compact-feed">
                  {latestSignals.map((signal) => (
                    <article key={signal.id}>
                      <span className={`severity-dot ${signal.severity}`} />
                      <div>
                        <div className="compact-feed-meta">
                          <span>{signal.signal_type.replaceAll('_', ' ')}</span>
                          <time>{formatDate(signal.detected_at)}</time>
                        </div>
                        <p>{signal.description}</p>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <EmptyState title="No signals detected" description="Signals will appear after the first successful analysis run." />
              )}
            </Panel>

            <Panel
              eyebrow="FORWARD VIEW"
              title="Latest forecasts"
              action={<Link href={`${basePath}/intelligence`} className="text-link">View all <Icon name="arrow" size={14} /></Link>}
            >
              {latestPredictions.length ? (
                <div className="forecast-list">
                  {latestPredictions.map((prediction) => (
                    <article key={prediction.id}>
                      <div>
                        <span>{prediction.timeframe || 'Open timeframe'}</span>
                        <strong>{percent(prediction.confidence)}</strong>
                      </div>
                      <p>{prediction.prediction}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <EmptyState title="No forecasts available" description="Evidence-backed forecasts will appear after analysis completes." />
              )}
            </Panel>
          </div>
        </>
      )}
    </main>
  );
}
