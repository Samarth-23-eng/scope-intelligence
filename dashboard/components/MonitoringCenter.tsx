'use client';

import { FormEvent, KeyboardEvent, useCallback, useEffect, useState } from 'react';
import {
  getMonitoringOverview,
  runMonitoringNow,
  updateMonitoringProfile,
} from '@/lib/api';
import type { MonitoringOverview } from '@/lib/types';

const cadenceOptions = [
  { value: 15, label: 'Every 15 minutes' },
  { value: 60, label: 'Hourly' },
  { value: 360, label: 'Every 6 hours' },
  { value: 720, label: 'Every 12 hours' },
  { value: 1440, label: 'Daily' },
  { value: 10080, label: 'Weekly' },
];

const severityOptions = ['low', 'medium', 'high', 'critical'] as const;

function formatTime(value: string | null) {
  if (!value) return 'Not scheduled';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function statusTone(status: string) {
  if (status === 'completed') return 'monitor-status good';
  if (status === 'running' || status === 'queued') return 'monitor-status active';
  if (status === 'failed' || status === 'partial') return 'monitor-status danger';
  return 'monitor-status';
}

export function MonitoringCenter({
  competitorId,
  pipelineRunning,
  onRunQueued,
}: {
  competitorId: number;
  pipelineRunning: boolean;
  onRunQueued: () => void;
}) {
  const [overview, setOverview] = useState<MonitoringOverview | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [cadence, setCadence] = useState(1440);
  const [topics, setTopics] = useState<string[]>([]);
  const [topicInput, setTopicInput] = useState('');
  const [severities, setSeverities] = useState<string[]>(['high', 'critical']);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const applyOverview = useCallback((value: MonitoringOverview) => {
    setOverview(value);
    setEnabled(value.profile.enabled);
    setCadence(value.profile.cadence_minutes);
    setTopics(value.profile.focus_topics);
    setSeverities(value.profile.alert_severities);
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      applyOverview(await getMonitoringOverview(competitorId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Monitoring data is unavailable');
    } finally {
      setLoading(false);
    }
  }, [applyOverview, competitorId]);

  useEffect(() => {
    let cancelled = false;
    getMonitoringOverview(competitorId)
      .then((result) => {
        if (!cancelled) applyOverview(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Monitoring data is unavailable');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applyOverview, competitorId]);

  useEffect(() => {
    if (!overview || !['queued', 'running'].includes(overview.profile.last_status)) {
      return;
    }
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => window.clearInterval(timer);
  }, [overview, refresh]);

  const addTopic = (event?: FormEvent) => {
    event?.preventDefault();
    const value = topicInput.trim();
    if (!value || topics.some((topic) => topic.toLowerCase() === value.toLowerCase())) {
      setTopicInput('');
      return;
    }
    setTopics((current) => [...current, value].slice(0, 12));
    setTopicInput('');
  };

  const handleTopicKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault();
      addTopic();
    }
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const next = await updateMonitoringProfile(competitorId, {
        enabled,
        cadence_minutes: cadence,
        focus_topics: topics,
        alert_severities: severities,
      });
      applyOverview(next);
      setMessage(enabled ? 'Watch schedule saved and active.' : 'Watch schedule saved and paused.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save monitoring settings');
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    setRunning(true);
    setMessage(null);
    setError(null);
    try {
      await runMonitoringNow(competitorId);
      setMessage('Monitoring run queued. Live progress is shown above.');
      onRunQueued();
      window.setTimeout(() => void refresh(), 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start monitoring run');
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="monitoring-shell">
        <div className="panel h-56 animate-pulse bg-[#11141e]" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((item) => (
            <div key={item} className="panel h-28 animate-pulse bg-[#11141e]" />
          ))}
        </div>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="panel p-8 text-center">
        <p className="font-medium text-rose-300">Watch Center unavailable</p>
        <p className="mt-2 text-sm text-rose-400">{error}</p>
        <button onClick={() => void refresh()} className="secondary-button mt-5">
          Try again
        </button>
      </div>
    );
  }

  const metrics = [
    ['New documents', overview.metrics.documents_7d, 'Collected in 7 days'],
    ['Material changes', overview.metrics.changes_7d, 'Detected in 7 days'],
    ['Priority signals', overview.metrics.priority_signals_7d, `${overview.metrics.signals_7d} total signals`],
    ['Collection issues', overview.metrics.open_collection_errors, 'Currently unresolved'],
  ];

  return (
    <div className="monitoring-shell">
      <section className="monitor-hero">
        <div className="monitor-hero-copy">
          <div className="flex flex-wrap items-center gap-2">
            <p className="eyebrow">CONTINUOUS MONITORING</p>
            <span className={overview.scheduler_online ? 'system-chip good' : 'system-chip danger'}>
              {overview.scheduler_online ? 'Scheduler online' : 'Scheduler offline'}
            </span>
          </div>
          <h2>Watch Center</h2>
          <p>
            Turn this company into a living intelligence target. The platform will rerun
            collection and analysis on schedule while preserving every source, change,
            signal, and pipeline decision.
          </p>
        </div>
        <div className="monitor-hero-actions">
          <button
            type="button"
            className={enabled ? 'switch-control on' : 'switch-control'}
            role="switch"
            aria-checked={enabled}
            onClick={() => setEnabled((value) => !value)}
          >
            <span />
            {enabled ? 'Autopilot on' : 'Autopilot paused'}
          </button>
          <button
            onClick={() => void runNow()}
            disabled={running || pipelineRunning}
            className="primary-button"
          >
            {running ? 'Queuing…' : pipelineRunning ? 'Pipeline running' : 'Run watch now'}
          </button>
        </div>
      </section>

      {(message || error) && (
        <div className={error ? 'feedback-banner error' : 'feedback-banner success'} role="status">
          <strong>{error ? 'Action failed' : 'Saved'}</strong>
          <span>{error || message}</span>
        </div>
      )}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Seven day intelligence pulse">
        {metrics.map(([label, value, note]) => (
          <article key={label} className="monitor-metric">
            <p>{label}</p>
            <strong>{value}</strong>
            <span>{note}</span>
          </article>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <div className="panel p-5 sm:p-6">
          <div className="section-heading">
            <div>
              <p className="eyebrow">WATCH POLICY</p>
              <h3>Collection schedule and research focus</h3>
            </div>
            <button onClick={() => void save()} disabled={saving} className="secondary-button">
              {saving ? 'Saving…' : 'Save policy'}
            </button>
          </div>

          <div className="monitor-form-grid">
            <label>
              Collection cadence
              <select
                className="field mt-2"
                value={cadence}
                onChange={(event) => setCadence(Number(event.target.value))}
              >
                {cadenceOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>

            <fieldset>
              <legend>Alert threshold</legend>
              <div className="severity-picker">
                {severityOptions.map((severity) => {
                  const active = severities.includes(severity);
                  return (
                    <button
                      key={severity}
                      type="button"
                      aria-pressed={active}
                      className={active ? `severity-option active ${severity}` : 'severity-option'}
                      onClick={() => {
                        setSeverities((current) =>
                          active
                            ? current.length > 1
                              ? current.filter((item) => item !== severity)
                              : current
                            : [...current, severity],
                        );
                      }}
                    >
                      {severity}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          </div>

          <div className="mt-6">
            <label className="text-sm text-[#aeb4c3]" htmlFor="watch-topic">
              Focus topics
            </label>
            <p className="mt-1 text-xs leading-5 text-[#687186]">
              Guide scheduled agents toward the questions that matter most. Add up to 12.
            </p>
            <form onSubmit={addTopic} className="mt-3 flex gap-2">
              <input
                id="watch-topic"
                className="field flex-1"
                value={topicInput}
                maxLength={80}
                onChange={(event) => setTopicInput(event.target.value)}
                onKeyDown={handleTopicKey}
                placeholder="e.g. India hiring, partnerships, product launches"
              />
              <button type="submit" className="secondary-button">Add</button>
            </form>
            <div className="topic-list" aria-label="Monitoring focus topics">
              {topics.length ? topics.map((topic) => (
                <button
                  key={topic}
                  type="button"
                  onClick={() => setTopics((current) => current.filter((item) => item !== topic))}
                  className="topic-chip"
                  aria-label={`Remove ${topic}`}
                >
                  {topic}<span aria-hidden="true">×</span>
                </button>
              )) : (
                <p className="empty-inline">No focus topics yet. Scheduled runs will use broad company coverage.</p>
              )}
            </div>
          </div>
        </div>

        <aside className="panel p-5 sm:p-6">
          <p className="eyebrow">NEXT WINDOW</p>
          <div className="next-run-card">
            <span className={overview.profile.enabled ? 'status-orbit on' : 'status-orbit'} />
            <div>
              <strong>{overview.profile.enabled ? formatTime(overview.profile.next_run_at) : 'Monitoring paused'}</strong>
              <p>
                {overview.profile.enabled
                  ? `Repeats ${cadenceOptions.find((item) => item.value === cadence)?.label.toLowerCase()}.`
                  : 'Save the policy with Autopilot on to schedule collection.'}
              </p>
            </div>
          </div>
          <dl className="monitor-details">
            <div><dt>Last status</dt><dd className={statusTone(overview.profile.last_status)}>{overview.profile.last_status}</dd></div>
            <div><dt>Last scheduled</dt><dd>{formatTime(overview.profile.last_scheduled_at)}</dd></div>
            <div><dt>Latest pipeline</dt><dd>{overview.latest_run ? `#${overview.latest_run.id} · ${overview.latest_run.status}` : 'No runs yet'}</dd></div>
            <div><dt>Shared model</dt><dd>Platform default</dd></div>
          </dl>
          {overview.profile.last_error && (
            <div className="monitor-last-error">
              <strong>Last issue</strong>
              <p>{overview.profile.last_error}</p>
            </div>
          )}
        </aside>
      </section>

      <section className="panel overflow-hidden">
        <div className="section-heading border-b border-[#222636] p-5 sm:p-6">
          <div>
            <p className="eyebrow">AUDIT TRAIL</p>
            <h3>Monitoring activity</h3>
          </div>
          <button onClick={() => void refresh()} className="text-button">Refresh</button>
        </div>
        {overview.activity.length ? (
          <div className="activity-list">
            {overview.activity.map((event) => (
              <article key={event.id} className="activity-row">
                <span className={`activity-mark ${event.status}`} />
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <strong>{event.message}</strong>
                    <span className={statusTone(event.status)}>{event.status}</span>
                  </div>
                  <p>
                    {event.event_type.replaceAll('_', ' ')}
                    {event.pipeline_run_id ? ` · pipeline #${event.pipeline_run_id}` : ''}
                    {' · '}
                    {formatTime(event.created_at)}
                  </p>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-monitoring">
            <strong>No monitoring activity yet</strong>
            <p>Save a watch policy or run the first monitoring cycle to begin the audit trail.</p>
          </div>
        )}
      </section>
    </div>
  );
}
