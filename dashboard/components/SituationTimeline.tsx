'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getIntelligenceTimeline,
  rebuildIntelligenceTimeline,
} from '@/lib/api';
import type {
  EventCorrelation,
  IntelligenceEvent,
  TimelineOverview,
} from '@/lib/types';

type Range = 'all' | '7' | '30' | '90';

function label(value: string) {
  return value.replaceAll('_', ' ');
}

function percentage(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatDate(value: string | null, withTime = false) {
  if (!value) return 'Date unknown';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    ...(withTime ? { timeStyle: 'short' as const } : {}),
  }).format(new Date(value));
}

function monthKey(value: string | null) {
  if (!value) return 'Undated intelligence';
  return new Intl.DateTimeFormat(undefined, {
    month: 'long',
    year: 'numeric',
  }).format(new Date(value));
}

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : 'The timeline could not be loaded.';
}

function Momentum({
  recent,
  previous,
}: {
  recent: number;
  previous: number;
}) {
  if (recent === previous) {
    return <span className="timeline-trend stable">Steady vs prior week</span>;
  }
  const direction = recent > previous ? 'up' : 'down';
  const delta = Math.abs(recent - previous);
  return (
    <span className={`timeline-trend ${direction}`}>
      {direction === 'up' ? 'Rising' : 'Cooling'} by {delta} event{delta === 1 ? '' : 's'}
    </span>
  );
}

function CorrelationList({
  event,
  correlations,
}: {
  event: IntelligenceEvent;
  correlations: EventCorrelation[];
}) {
  const related = correlations.filter(
    (item) =>
      item.source_event_id === event.id || item.target_event_id === event.id,
  );
  if (!related.length) {
    return (
      <div className="timeline-related-empty">
        No strong cross-event pattern has been detected for this event.
      </div>
    );
  }

  return (
    <div className="timeline-related-list">
      {related.slice(0, 5).map((item) => {
        const otherTitle =
          item.source_event_id === event.id
            ? item.target_title
            : item.source_title;
        return (
          <article key={item.id}>
            <div>
              <span>{label(item.correlation_type)}</span>
              <strong>{otherTitle}</strong>
              <p>{item.rationale}</p>
            </div>
            <b>{percentage(item.score)}</b>
          </article>
        );
      })}
    </div>
  );
}

export function SituationTimeline({ competitorId }: { competitorId: number }) {
  const [overview, setOverview] = useState<TimelineOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [eventType, setEventType] = useState('all');
  const [impact, setImpact] = useState('all');
  const [status, setStatus] = useState('all');
  const [range, setRange] = useState<Range>('all');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [timelineAnchor] = useState(Date.now);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getIntelligenceTimeline(competitorId);
      setOverview(result);
      setSelectedId((current) => current ?? result.events[0]?.id ?? null);
    } catch (loadError) {
      setError(messageFrom(loadError));
    } finally {
      setLoading(false);
    }
  }, [competitorId]);

  useEffect(() => {
    let cancelled = false;
    getIntelligenceTimeline(competitorId)
      .then((result) => {
        if (cancelled) return;
        setOverview(result);
        setSelectedId((current) => current ?? result.events[0]?.id ?? null);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(messageFrom(loadError));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [competitorId]);

  const rebuild = async () => {
    setRebuilding(true);
    setError(null);
    try {
      const result = await rebuildIntelligenceTimeline(competitorId);
      setOverview(result.overview);
      setSelectedId(result.overview.events[0]?.id ?? null);
    } catch (rebuildError) {
      setError(messageFrom(rebuildError));
    } finally {
      setRebuilding(false);
    }
  };

  const filteredEvents = useMemo(() => {
    if (!overview) return [];
    const search = query.trim().toLocaleLowerCase();
    const cutoff =
      range === 'all'
        ? null
        : timelineAnchor -
          Number.parseInt(range, 10) * 24 * 60 * 60 * 1000;
    return overview.events.filter((event) => {
      const searchable = `${event.title} ${event.summary} ${event.event_type}`.toLocaleLowerCase();
      return (
        (!search || searchable.includes(search)) &&
        (eventType === 'all' || event.event_type === eventType) &&
        (impact === 'all' || event.impact_level === impact) &&
        (status === 'all' || event.status === status) &&
        (!cutoff ||
          (event.occurred_at &&
            new Date(event.occurred_at).getTime() >= cutoff))
      );
    });
  }, [eventType, impact, overview, query, range, status, timelineAnchor]);

  const groupedEvents = useMemo(() => {
    const groups = new Map<string, IntelligenceEvent[]>();
    for (const event of filteredEvents) {
      const key = monthKey(event.occurred_at);
      groups.set(key, [...(groups.get(key) ?? []), event]);
    }
    return [...groups.entries()];
  }, [filteredEvents]);

  const selected =
    overview?.events.find((event) => event.id === selectedId) ?? null;
  const maxWeekly = Math.max(
    1,
    ...(overview?.weekly_activity.map((week) => week.events) ?? [1]),
  );

  if (loading) {
    return (
      <section className="timeline-loading panel">
        <span />
        <p>Building the chronological intelligence picture...</p>
      </section>
    );
  }

  if (!overview) {
    return (
      <section className="timeline-empty panel">
        <span>!</span>
        <h2>Situation Timeline is unavailable</h2>
        <p>{error ?? 'The event-fusion service did not return a timeline.'}</p>
        <button className="secondary-button" onClick={() => void load()}>
          Try again
        </button>
      </section>
    );
  }

  const summary = overview.summary;

  return (
    <div className="situation-timeline">
      <section className="timeline-hero panel">
        <div>
          <p className="eyebrow">EVENT TIMELINE</p>
          <h2>Situation Timeline</h2>
          <p>
            Verified claims, material changes, and strategic signals fused into
            one chronological intelligence picture.
          </p>
        </div>
        <button
          className="primary-button"
          disabled={rebuilding}
          onClick={() => void rebuild()}
        >
          {rebuilding ? 'Fusing intelligence...' : 'Rebuild timeline'}
        </button>
      </section>

      {error ? <div className="timeline-error">{error}</div> : null}

      <section className="timeline-metrics">
        <article>
          <p>Total events</p>
          <strong>{summary.total_events}</strong>
          <span>{summary.top_type ? `Leading theme: ${label(summary.top_type)}` : 'Awaiting evidence'}</span>
        </article>
        <article>
          <p>Last 7 days</p>
          <strong>{summary.recent_events}</strong>
          <Momentum
            recent={summary.recent_events}
            previous={summary.previous_period_events}
          />
        </article>
        <article>
          <p>High impact</p>
          <strong>{summary.high_impact}</strong>
          <span>High and critical developments</span>
        </article>
        <article>
          <p>Active watch</p>
          <strong>{summary.developing + summary.disputed}</strong>
          <span>{summary.developing} developing / {summary.disputed} disputed</span>
        </article>
      </section>

      <section className="timeline-pulse panel">
        <div className="timeline-section-heading">
          <div>
            <p className="eyebrow">8-WEEK SIGNAL</p>
            <h3>Activity pulse</h3>
          </div>
          <div className="timeline-legend">
            <span><i className="all-events" />All events</span>
            <span><i className="high-events" />High impact</span>
          </div>
        </div>
        <div className="timeline-bars">
          {overview.weekly_activity.map((week) => (
            <div className="timeline-bar-column" key={week.start}>
              <div className="timeline-bar-track">
                <i
                  className="timeline-bar-total"
                  style={{ height: `${Math.max((week.events / maxWeekly) * 100, week.events ? 8 : 2)}%` }}
                />
                <i
                  className="timeline-bar-high"
                  style={{ height: `${Math.max((week.high_impact / maxWeekly) * 100, week.high_impact ? 8 : 0)}%` }}
                />
              </div>
              <span>{new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(week.start))}</span>
              <b>{week.events}</b>
            </div>
          ))}
        </div>
      </section>

      <section className="timeline-controls panel">
        <label className="timeline-search">
          <span>Search the situation picture</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search events, topics, or entities..."
          />
        </label>
        <label>
          <span>Event type</span>
          <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
            <option value="all">All types</option>
            {Object.keys(overview.event_types).sort().map((type) => (
              <option value={type} key={type}>{label(type)}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Impact</span>
          <select value={impact} onChange={(event) => setImpact(event.target.value)}>
            <option value="all">All impact</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label>
          <span>Status</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="all">All states</option>
            <option value="active">Active</option>
            <option value="developing">Developing</option>
            <option value="disputed">Disputed</option>
            <option value="stale">Stale</option>
          </select>
        </label>
        <label>
          <span>Time window</span>
          <select value={range} onChange={(event) => setRange(event.target.value as Range)}>
            <option value="all">All time</option>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
          </select>
        </label>
      </section>

      {!overview.events.length ? (
        <section className="timeline-empty panel">
          <span>T</span>
          <h2>No fused events yet</h2>
          <p>
            No verified developments currently meet the event criteria.
            Forecasts and absence-of-evidence statements are intentionally
            excluded from the chronological feed.
          </p>
          <button
            className="primary-button"
            disabled={rebuilding}
            onClick={() => void rebuild()}
          >
            Build the first timeline
          </button>
        </section>
      ) : (
        <div className="timeline-workspace">
          <section className="timeline-stream panel">
            <div className="timeline-stream-header">
              <div>
                <p className="eyebrow">CHRONOLOGICAL FEED</p>
                <h3>{filteredEvents.length} event{filteredEvents.length === 1 ? '' : 's'} shown</h3>
              </div>
              <button
                className="timeline-clear"
                onClick={() => {
                  setQuery('');
                  setEventType('all');
                  setImpact('all');
                  setStatus('all');
                  setRange('all');
                }}
              >
                Clear filters
              </button>
            </div>

            {groupedEvents.length ? groupedEvents.map(([month, events]) => (
              <div className="timeline-month" key={month}>
                <h4>{month}</h4>
                <div className="timeline-event-list">
                  {events.map((event) => (
                    <button
                      className={`timeline-event ${selectedId === event.id ? 'selected' : ''}`}
                      key={event.id}
                      onClick={() => setSelectedId(event.id)}
                    >
                      <i className={`timeline-node impact-${event.impact_level}`} />
                      <div className="timeline-event-date">
                        <strong>{formatDate(event.occurred_at)}</strong>
                        <span>{event.metadata.momentum ?? 'established'}</span>
                      </div>
                      <div className="timeline-event-body">
                        <div className="timeline-event-badges">
                          <span className={`impact-badge ${event.impact_level}`}>{event.impact_level}</span>
                          <span>{label(event.event_type)}</span>
                          <span className={`event-state ${event.status}`}>{event.status}</span>
                        </div>
                        <h5>{event.title}</h5>
                        <p>{event.summary}</p>
                        <footer>
                          <span>{percentage(event.confidence)} confidence</span>
                          <span>{event.source_count} independent source{event.source_count === 1 ? '' : 's'}</span>
                          <span>{event.linked_observations} fused observation{event.linked_observations === 1 ? '' : 's'}</span>
                        </footer>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )) : (
              <div className="timeline-no-results">
                No events match these filters.
              </div>
            )}
          </section>

          <aside className="timeline-inspector panel">
            {selected ? (
              <>
                <div className="timeline-inspector-top">
                  <p className="eyebrow">EVENT INSPECTOR</p>
                  <span className={`impact-badge ${selected.impact_level}`}>
                    {selected.impact_level} impact
                  </span>
                </div>
                <h3>{selected.title}</h3>
                <p>{selected.summary}</p>
                <dl>
                  <div><dt>Occurred</dt><dd>{formatDate(selected.occurred_at, true)}</dd></div>
                  <div><dt>Date basis</dt><dd>{label(selected.metadata.date_basis ?? 'observed_at')}</dd></div>
                  <div><dt>Confidence</dt><dd>{percentage(selected.confidence)}</dd></div>
                  <div><dt>Verification</dt><dd>{selected.verification_status}</dd></div>
                  <div><dt>Independent sources</dt><dd>{selected.source_count}</dd></div>
                  <div><dt>Observation span</dt><dd>{selected.metadata.span_days ?? 0} days</dd></div>
                  <div><dt>Source layers</dt><dd>{selected.metadata.source_kinds?.map(label).join(', ') || 'Unknown'}</dd></div>
                </dl>
                <div className="timeline-related">
                  <div>
                    <p className="eyebrow">CORRELATED DEVELOPMENTS</p>
                    <span>{selected.correlation_count} detected</span>
                  </div>
                  <CorrelationList
                    event={selected}
                    correlations={overview.correlations}
                  />
                </div>
              </>
            ) : (
              <div className="timeline-related-empty">
                Select an event to inspect its evidence status and related
                developments.
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
