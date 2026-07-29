'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Icon } from '@/components/Icon';
import { SituationTimeline } from '@/components/SituationTimeline';
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
  getAlerts,
  getCompetitorChanges,
  getCompetitorPredictions,
  getCompetitorSignals,
} from '@/lib/api';
import type { PageChange, Prediction, Signal } from '@/lib/types';

interface Alert {
  type: string;
  competitor_id: number;
  competitor_name: string;
  title: string;
  details: string;
  severity: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}

type View = 'signals' | 'timeline' | 'forecasts' | 'changes' | 'alerts';

export default function IntelligencePage() {
  const { competitorId, dataVersion } = useCompanyWorkspace();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [changes, setChanges] = useState<PageChange[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [view, setView] = useState<View>('signals');
  const [severity, setSeverity] = useState('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [signalRows, predictionRows, changeRows, alertRows] = await Promise.all([
        getCompetitorSignals(competitorId),
        getCompetitorPredictions(competitorId),
        getCompetitorChanges(competitorId),
        getAlerts(competitorId),
      ]);
      setSignals(signalRows);
      setPredictions(predictionRows);
      setChanges(changeRows);
      setAlerts(alertRows);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Intelligence stream is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [competitorId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, dataVersion]);

  const visibleSignals = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return signals.filter((signal) => {
      if (severity !== 'all' && signal.severity !== severity) return false;
      return !needle || `${signal.signal_type} ${signal.description}`.toLowerCase().includes(needle);
    });
  }, [query, severity, signals]);

  const highPriority = signals.filter((item) => ['high', 'critical'].includes(item.severity)).length;
  const significantChanges = changes.filter((item) => item.significance >= 0.7).length;
  const strongForecasts = predictions.filter((item) => item.confidence >= 0.7).length;

  return (
    <main className="company-page">
      <PageHeading
        eyebrow="INTELLIGENCE STREAM"
        title="Signals and activity"
        description="Review observed changes, emerging signals, correlated events, alerts, and evidence-backed forward assessments."
        actions={
          <button type="button" className="secondary-button" onClick={() => void load()} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh stream
          </button>
        }
      />

      <section className="workspace-metric-grid">
        <MetricTile label="Signals" value={signals.length} note={`${highPriority} high priority`} icon="activity" tone={highPriority ? 'warning' : 'neutral'} />
        <MetricTile label="Observed changes" value={changes.length} note={`${significantChanges} high significance`} icon="layers" />
        <MetricTile label="Forecasts" value={predictions.length} note={`${strongForecasts} above 70% confidence`} icon="spark" />
        <MetricTile label="Alerts" value={alerts.length} note="Operator-facing notifications" icon="shield" tone={alerts.length ? 'warning' : 'neutral'} />
      </section>

      <div className="view-switcher" role="tablist" aria-label="Intelligence views">
        {([
          ['signals', 'Signals', signals.length],
          ['timeline', 'Timeline', null],
          ['forecasts', 'Forecasts', predictions.length],
          ['changes', 'Changes', changes.length],
          ['alerts', 'Alerts', alerts.length],
        ] as const).map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={view === id}
            className={view === id ? 'active' : ''}
            onClick={() => setView(id)}
          >
            {label}
            {count !== null ? <span>{count}</span> : null}
          </button>
        ))}
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingState label="Loading intelligence stream" /> : null}

      {!loading && view === 'signals' ? (
        <Panel>
          <div className="filter-bar">
            <label className="search-field">
              <Icon name="search" size={16} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search signals"
                aria-label="Search signals"
              />
            </label>
            <label>
              <span className="sr-only">Signal severity</span>
              <select value={severity} onChange={(event) => setSeverity(event.target.value)} className="select-field">
                <option value="all">All severities</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
          </div>
          {visibleSignals.length ? (
            <div className="intelligence-list">
              {visibleSignals.map((signal) => (
                <article key={signal.id}>
                  <div className={`signal-marker ${signal.severity}`}>
                    <Icon name="activity" size={17} />
                  </div>
                  <div className="intelligence-list-content">
                    <div className="intelligence-list-top">
                      <div>
                        <span className={`severity-label ${signal.severity}`}>{signal.severity}</span>
                        <span className="type-label">{signal.signal_type.replaceAll('_', ' ')}</span>
                      </div>
                      <time>{formatDate(signal.detected_at, true)}</time>
                    </div>
                    <p>{signal.description}</p>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="No matching signals" description="Adjust the search or severity filter, or run a new collection." />
          )}
        </Panel>
      ) : null}

      {!loading && view === 'timeline' ? <SituationTimeline competitorId={competitorId} /> : null}

      {!loading && view === 'forecasts' ? (
        <div className="forecast-grid">
          {predictions.length ? predictions.map((prediction) => (
            <article key={prediction.id} className="forecast-card">
              <div className="forecast-card-top">
                <span><Icon name="spark" size={15} /> {prediction.timeframe || 'Open timeframe'}</span>
                <strong>{percent(prediction.confidence)}</strong>
              </div>
              <p>{prediction.prediction}</p>
              <div className="confidence-track"><span style={{ width: percent(prediction.confidence) }} /></div>
              <time>Assessed {formatDate(prediction.created_at)}</time>
            </article>
          )) : <EmptyState title="No forecasts available" description="Run analysis after collecting evidence to generate grounded forecasts." />}
        </div>
      ) : null}

      {!loading && view === 'changes' ? (
        <Panel>
          {changes.length ? (
            <div className="change-list">
              {changes.map((change) => (
                <article key={change.id}>
                  <div className="change-list-rail">
                    <span />
                  </div>
                  <div>
                    <div className="change-list-top">
                      <div>
                        <span className="type-label">{change.change_type}</span>
                        <strong>{change.title || 'Observed page change'}</strong>
                      </div>
                      <span className="confidence-pill">{percent(change.significance)} significance</span>
                    </div>
                    <p>{change.summary}</p>
                    {change.after_excerpt ? <blockquote>{change.after_excerpt}</blockquote> : null}
                    <footer>
                      <a href={change.source_url} target="_blank" rel="noreferrer">Open source</a>
                      <time>{formatDate(change.detected_at, true)}</time>
                    </footer>
                  </div>
                </article>
              ))}
            </div>
          ) : <EmptyState title="No page changes detected" description="The first collection creates a baseline; later runs expose meaningful changes." />}
        </Panel>
      ) : null}

      {!loading && view === 'alerts' ? (
        <Panel>
          {alerts.length ? (
            <div className="alert-feed">
              {alerts.map((alert, index) => (
                <article key={`${alert.type}-${alert.timestamp}-${index}`}>
                  <span className={`alert-icon ${alert.severity}`}><Icon name="shield" size={17} /></span>
                  <div>
                    <div><strong>{alert.title}</strong><time>{formatDate(alert.timestamp, true)}</time></div>
                    <p>{alert.details}</p>
                    <span>{alert.type.replaceAll('_', ' ')}</span>
                  </div>
                </article>
              ))}
            </div>
          ) : <EmptyState title="No active alerts" description="Priority activity will create clear operator-facing alerts here." />}
        </Panel>
      ) : null}
    </main>
  );
}
