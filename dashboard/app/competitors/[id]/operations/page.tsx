'use client';

import { type FormEvent, useCallback, useEffect, useState } from 'react';
import { Icon } from '@/components/Icon';
import { MonitoringCenter } from '@/components/MonitoringCenter';
import { useCompanyWorkspace } from '@/components/company/CompanyWorkspace';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricTile,
  PageHeading,
  Panel,
  formatDate,
} from '@/components/company/PagePrimitives';
import {
  cancelPipelineRun,
  deletePipelineData,
  getAccessRecoveryConfig,
  getCollectionCampaigns,
  getCollectionCoverage,
  getCollectionErrors,
  getCompetitorRawData,
  getPipelineRuns,
  getSourceProfiles,
  registerSourceProfile,
  retryPipelineTask,
  updateAccessRecoveryConfig,
  updateSourceProfile,
} from '@/lib/api';
import type {
  AccessRecoveryConfig,
  CollectionCampaign,
  CollectionCoverage,
  CollectionError,
  PipelineRun,
  RawData,
  SourceProfile,
} from '@/lib/types';

type View = 'monitoring' | 'collection' | 'runs' | 'raw' | 'settings';

function countSummaryValue(value: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === 'number') return candidate;
  }
  return 0;
}

export default function OperationsPage() {
  const {
    competitorId,
    competitor,
    dataVersion,
    pipelineRunning,
    pipelineStatus,
    refreshWorkspace,
  } = useCompanyWorkspace();
  const [view, setView] = useState<View>('monitoring');
  const [campaigns, setCampaigns] = useState<CollectionCampaign[]>([]);
  const [coverage, setCoverage] = useState<CollectionCoverage | null>(null);
  const [errors, setErrors] = useState<CollectionError[]>([]);
  const [profiles, setProfiles] = useState<SourceProfile[]>([]);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [rawData, setRawData] = useState<RawData[]>([]);
  const [accessRecovery, setAccessRecovery] = useState<AccessRecoveryConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sourceUrl, setSourceUrl] = useState('');
  const [sourceType, setSourceType] = useState('auto');
  const [deleteDialog, setDeleteDialog] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState('');
  const [expandedRun, setExpandedRun] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const results = await Promise.allSettled([
      getCollectionCampaigns(competitorId),
      getCollectionCoverage(competitorId),
      getCollectionErrors(competitorId),
      getSourceProfiles(competitorId),
      getPipelineRuns(competitorId),
      getCompetitorRawData(competitorId),
      getAccessRecoveryConfig(competitorId),
    ]);

    if (results[0].status === 'fulfilled') setCampaigns(results[0].value);
    if (results[1].status === 'fulfilled') setCoverage(results[1].value);
    if (results[2].status === 'fulfilled') setErrors(results[2].value);
    if (results[3].status === 'fulfilled') setProfiles(results[3].value);
    if (results[4].status === 'fulfilled') setRuns(results[4].value);
    if (results[5].status === 'fulfilled') setRawData(results[5].value);
    if (results[6].status === 'fulfilled') setAccessRecovery(results[6].value);

    const failures = results.filter((result) => result.status === 'rejected');
    if (failures.length) {
      const first = failures[0].status === 'rejected' ? failures[0].reason : null;
      setError(
        failures.length === results.length && first instanceof Error
          ? first.message
          : `${failures.length} operational data source${failures.length === 1 ? '' : 's'} could not be loaded.`,
      );
    }
    setLoading(false);
  }, [competitorId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, dataVersion]);

  const registerSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setActionPending(true);
    setError(null);
    setNotice(null);
    try {
      await registerSourceProfile(competitorId, sourceUrl.trim(), sourceType === 'auto' ? undefined : sourceType);
      setSourceUrl('');
      setNotice('Source profile registered and ready for collection.');
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Source profile could not be registered.');
    } finally {
      setActionPending(false);
    }
  };

  const toggleProfile = async (profile: SourceProfile) => {
    setActionPending(true);
    setError(null);
    try {
      await updateSourceProfile(
        competitorId,
        profile.id,
        profile.status === 'disabled' ? 'active' : 'disabled',
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Source status could not be changed.');
    } finally {
      setActionPending(false);
    }
  };

  const toggleRecovery = async () => {
    if (!accessRecovery) return;
    setActionPending(true);
    setError(null);
    try {
      setAccessRecovery(await updateAccessRecoveryConfig(competitorId, !accessRecovery.enabled));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Advanced hard search could not be changed.');
    } finally {
      setActionPending(false);
    }
  };

  const cancelRun = async (runId: number) => {
    setActionPending(true);
    setError(null);
    try {
      await cancelPipelineRun(competitorId, runId);
      setNotice(`Cancellation requested for run #${runId}.`);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Pipeline run could not be cancelled.');
    } finally {
      setActionPending(false);
    }
  };

  const retryTask = async (runId: number, taskId: number) => {
    setActionPending(true);
    setError(null);
    try {
      const result = await retryPipelineTask(competitorId, runId, taskId);
      setNotice(`Retry run #${result.retry_run_id} queued for ${result.task_key}.`);
      refreshWorkspace();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Pipeline task could not be retried.');
    } finally {
      setActionPending(false);
    }
  };

  const clearPipelineData = async () => {
    if (deleteConfirmation !== competitor?.name) return;
    setActionPending(true);
    setError(null);
    try {
      const result = await deletePipelineData(competitorId);
      const total = Object.values(result.deleted).reduce((sum, count) => sum + count, 0);
      setNotice(`Removed ${total} pipeline records and ${result.reports_deleted} generated reports.`);
      setDeleteDialog(false);
      setDeleteConfirmation('');
      refreshWorkspace();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Pipeline data could not be deleted.');
    } finally {
      setActionPending(false);
    }
  };

  const activeSources = profiles.filter((profile) => profile.status === 'active' || profile.status === 'verified').length;
  const failedRuns = runs.filter((run) => run.status === 'failed' || run.status === 'partial').length;
  const collectedItems = coverage?.documents_by_source.reduce(
    (sum, source) => sum + source.documents,
    0,
  ) ?? rawData.length;
  const sourceChannels = coverage?.documents_by_source.length ?? 0;
  const recoverableErrors = errors.filter((item) => item.recoverable).length;

  return (
    <main className="company-page">
      <PageHeading
        eyebrow="COLLECTION OPERATIONS"
        title="Pipeline control center"
        description="Configure monitoring, inspect collection coverage, diagnose exact failures, and manage the complete pipeline run history."
        actions={
          <button type="button" className="secondary-button" onClick={() => void load()} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh operations
          </button>
        }
      />

      <section className="workspace-metric-grid">
        <MetricTile label="Pipeline state" value={pipelineStatus?.status ?? 'idle'} note={pipelineStatus?.stage ? `Current stage: ${pipelineStatus.stage}` : 'No active run'} icon="play" tone={pipelineRunning ? 'good' : pipelineStatus?.status === 'failed' ? 'danger' : 'neutral'} />
        <MetricTile label="Collected records" value={collectedItems} note={`${rawData.length} raw records retained`} icon="database" />
        <MetricTile label="Source channels" value={sourceChannels} note={`${activeSources} active source profiles`} icon="link" tone={sourceChannels ? 'good' : 'warning'} />
        <MetricTile label="Open errors" value={errors.length} note={`${recoverableErrors} recoverable · ${failedRuns} incomplete runs`} icon="error" tone={errors.length ? 'danger' : 'good'} />
      </section>

      <div className="view-switcher" role="tablist" aria-label="Collection operation views">
        {([
          ['monitoring', 'Monitoring', null],
          ['collection', 'Collection', campaigns.length],
          ['runs', 'Pipeline runs', runs.length],
          ['raw', 'Raw records', rawData.length],
          ['settings', 'Source settings', profiles.length],
        ] as const).map(([id, label, count]) => (
          <button key={id} type="button" role="tab" aria-selected={view === id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>
            {label}{count !== null ? <span>{count}</span> : null}
          </button>
        ))}
      </div>

      {notice ? <div className="feedback-banner success"><Icon name="check" size={16} /><div><strong>Operation complete</strong><span>{notice}</span></div></div> : null}
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingState label="Loading collection operations" /> : null}

      {!loading && view === 'monitoring' ? (
        <MonitoringCenter
          competitorId={competitorId}
          pipelineRunning={pipelineRunning}
          onRunQueued={refreshWorkspace}
        />
      ) : null}

      {!loading && view === 'collection' ? (
        <div className="operations-stack">
          {errors.length ? (
            <Panel eyebrow="ACTION REQUIRED" title="Collection errors" className="error-panel">
              <div className="collection-error-list">
                {errors.map((item) => (
                  <article key={item.id}>
                    <span className={`error-severity ${item.severity}`}><Icon name="error" size={17} /></span>
                    <div>
                      <div className="collection-error-top">
                        <div><strong>{item.user_message}</strong><span>{item.error_code} · {item.engine || 'collector'}</span></div>
                        <span className="error-count">{item.occurrences} occurrence{item.occurrences === 1 ? '' : 's'}</span>
                      </div>
                      <p>{item.suggested_action || item.technical_message}</p>
                      {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.url}</a> : null}
                      <footer><span>HTTP {item.http_status ?? 'n/a'}</span><span>{item.recoverable ? 'Recoverable' : 'Manual action needed'}</span><time>{formatDate(item.last_occurred_at, true)}</time></footer>
                    </div>
                  </article>
                ))}
              </div>
            </Panel>
          ) : (
            <div className="page-state success"><Icon name="check" size={20} /><div><strong>No open collection errors</strong><p>Every recent source adapter completed without a recorded failure.</p></div></div>
          )}

          <div className="coverage-grid">
            <Panel eyebrow="SOURCE COVERAGE" title="Documents by channel">
              {coverage?.documents_by_source.length ? (
                <div className="coverage-bars">
                  {coverage.documents_by_source.map((item) => {
                    const max = Math.max(...coverage.documents_by_source.map((row) => row.documents), 1);
                    return <div key={item.source_type}><span><strong>{item.source_type.replaceAll('_', ' ')}</strong><em>{item.documents} docs · {item.recent} recent</em></span><div><i style={{ width: `${(item.documents / max) * 100}%` }} /></div></div>;
                  })}
                </div>
              ) : <EmptyState title="No source coverage yet" description="Coverage appears after the first collection campaign." />}
            </Panel>
            <Panel eyebrow="ADAPTER OUTPUT" title="Collector performance">
              {coverage?.adapters.length ? (
                <div className="adapter-list">
                  {coverage.adapters.map((adapter) => (
                    <article key={adapter.adapter_name}>
                      <div><strong>{adapter.adapter_name.replaceAll('_', ' ')}</strong><span>{adapter.successful_events}/{adapter.events} successful</span></div>
                      <div><strong>{adapter.items}</strong><span>items</span></div>
                      <div><strong>{Math.round(adapter.bytes_collected / 1024)}</strong><span>KB</span></div>
                    </article>
                  ))}
                </div>
              ) : <EmptyState title="No adapter output" description="Collector performance will be recorded here." />}
            </Panel>
          </div>

          <Panel eyebrow="CAMPAIGN HISTORY" title="Collection campaigns">
            {campaigns.length ? (
              <div className="campaign-list">
                {campaigns.map((campaign) => (
                  <article key={campaign.id}>
                    <span className={`run-status ${campaign.status}`}>{campaign.status}</span>
                    <div><strong>{campaign.campaign_type.replaceAll('_', ' ')}</strong><p>{campaign.strategy || 'Standard collection strategy'}</p></div>
                    <div><strong>{countSummaryValue(campaign.statistics, ['items', 'items_collected', 'documents'])}</strong><span>items</span></div>
                    <div><strong>{Object.values(campaign.frontier).reduce((sum, count) => sum + count, 0)}</strong><span>frontier URLs</span></div>
                    <time>{formatDate(campaign.created_at, true)}</time>
                  </article>
                ))}
              </div>
            ) : <EmptyState title="No collection campaigns" description="Run the pipeline to create the first collection campaign." />}
          </Panel>
        </div>
      ) : null}

      {!loading && view === 'runs' ? (
        <Panel>
          {runs.length ? (
            <div className="run-list">
              {runs.map((run) => {
                const expanded = expandedRun === run.id;
                const grounded = run.tasks.reduce((sum, task) => sum + (task.quality.grounded_items ?? 0), 0);
                const rejected = run.tasks.reduce((sum, task) => sum + (task.quality.rejected_items ?? 0), 0);
                return (
                  <article key={run.id} className={expanded ? 'expanded' : ''}>
                    <button type="button" className="run-summary" onClick={() => setExpandedRun(expanded ? null : run.id)}>
                      <span className={`run-status ${run.status}`}>{run.status}</span>
                      <div><strong>Run #{run.id}</strong><p>{run.run_type.replaceAll('_', ' ')} · {run.trigger_type.replaceAll('_', ' ')}</p></div>
                      <div><strong>{run.tasks.filter((task) => task.status === 'completed').length}/{run.tasks.length}</strong><span>tasks</span></div>
                      <div><strong>{grounded}</strong><span>grounded outputs</span></div>
                      <time>{formatDate(run.created_at, true)}</time>
                      <Icon name="arrow" size={16} />
                    </button>
                    {expanded ? (
                      <div className="run-details">
                        <div className="run-quality-strip">
                          <span>Model <strong>{run.model || 'default model'}</strong></span>
                          <span>Grounded <strong>{grounded}</strong></span>
                          <span>Rejected <strong>{rejected}</strong></span>
                          <span>Started <strong>{formatDate(run.started_at, true)}</strong></span>
                        </div>
                        {run.error ? <div className="inline-error"><Icon name="error" size={15} />{run.error}</div> : null}
                        <div className="task-list">
                          {run.tasks.map((task) => (
                            <article key={task.id}>
                              <span className={`task-status ${task.status}`} />
                              <div><strong>{task.agent_name}</strong><p>{task.task_key.replaceAll('_', ' ')} · attempt {task.attempt}/{task.max_attempts}</p></div>
                              <span className={`quality-status ${task.quality.status ?? 'empty'}`}>{task.quality.status ?? task.status}</span>
                              <div className="task-quality"><span>{task.quality.grounded_items ?? 0} grounded</span><span>{task.quality.latency_ms ? `${task.quality.latency_ms}ms` : '—'}</span></div>
                              {task.status === 'failed' ? <button type="button" className="table-action" disabled={actionPending} onClick={() => void retryTask(run.id, task.id)}>Retry</button> : null}
                            </article>
                          ))}
                        </div>
                        {['running', 'queued'].includes(run.status) ? <button type="button" className="danger-button" disabled={actionPending} onClick={() => void cancelRun(run.id)}>Cancel run</button> : null}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          ) : <EmptyState title="No pipeline runs" description="Each collection or analysis run will be preserved here with task-level diagnostics." />}
        </Panel>
      ) : null}

      {!loading && view === 'raw' ? (
        <Panel>
          {rawData.length ? (
            <div className="raw-record-list">
              {rawData.map((record) => (
                <details key={record.id}>
                  <summary><span className="type-label">{record.source}</span><strong>Record #{record.id}</strong><time>{formatDate(record.collected_at, true)}</time><Icon name="arrow" size={15} /></summary>
                  <div><pre>{record.content}</pre><footer><span>SHA {record.hash.slice(0, 12)}</span><span>{Object.keys(record.metadata).length} metadata fields</span></footer></div>
                </details>
              ))}
            </div>
          ) : <EmptyState title="No raw records retained" description="Unprocessed collection output will be available here after ingestion." />}
        </Panel>
      ) : null}

      {!loading && view === 'settings' ? (
        <div className="operations-stack">
          <Panel eyebrow="SOURCE REGISTRY" title="Collection sources">
            <form onSubmit={registerSource} className="source-register-form">
              <input type="url" required value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://company.com/news" className="field" />
              <select value={sourceType} onChange={(event) => setSourceType(event.target.value)} className="select-field">
                <option value="auto">Detect source type</option>
                <option value="website">Website</option>
                <option value="news">News</option>
                <option value="blog">Blog</option>
                <option value="careers">Careers</option>
                <option value="github">GitHub</option>
                <option value="linkedin">LinkedIn</option>
              </select>
              <button type="submit" className="primary-button" disabled={actionPending}><Icon name="link" size={15} /> Add source</button>
            </form>
            {profiles.length ? (
              <div className="source-profile-list">
                {profiles.map((profile) => (
                  <article key={profile.id}>
                    <span className={`source-status-dot ${profile.status}`} />
                    <div><strong>{profile.profile_url}</strong><p>{profile.source_type.replaceAll('_', ' ')} · {Math.round(profile.confidence * 100)}% confidence</p></div>
                    <span className={`source-status ${profile.status}`}>{profile.status}</span>
                    <button type="button" className="table-action" disabled={actionPending} onClick={() => void toggleProfile(profile)}>{profile.status === 'disabled' ? 'Enable' : 'Disable'}</button>
                  </article>
                ))}
              </div>
            ) : <EmptyState title="No source profiles" description="Register high-value sources to include them in future collection campaigns." />}
          </Panel>

          {accessRecovery?.available ? (
            <Panel eyebrow="EXPERIMENTAL" title={accessRecovery.label}>
              <div className="advanced-search-setting">
                <span><Icon name="shield" size={20} /></span>
                <div><strong>Advanced hard search</strong><p>Optional recovery for blocked or inaccessible sources. It runs only after standard collection fails and may be less stable.</p></div>
                <button type="button" className={accessRecovery.enabled ? 'switch-control on' : 'switch-control'} onClick={() => void toggleRecovery()} disabled={actionPending}><span />{accessRecovery.enabled ? 'Enabled' : 'Disabled'}</button>
              </div>
            </Panel>
          ) : null}

          <Panel eyebrow="DATA MANAGEMENT" title="Reset company intelligence" className="danger-zone">
            <div className="danger-zone-row">
              <div><strong>Delete all pipeline data</strong><p>Remove collected records, evidence, analysis, relationships, reports, and run history. The company profile itself remains.</p></div>
              <button type="button" className="danger-button" onClick={() => setDeleteDialog(true)}><Icon name="trash" size={15} /> Delete pipeline data</button>
            </div>
          </Panel>
        </div>
      ) : null}

      {deleteDialog ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => !actionPending && setDeleteDialog(false)}>
          <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="delete-title" onMouseDown={(event) => event.stopPropagation()}>
            <span className="modal-danger-icon"><Icon name="trash" size={22} /></span>
            <h3 id="delete-title">Delete pipeline data?</h3>
            <p>This permanently removes the collected and generated intelligence for <strong>{competitor?.name}</strong>. The monitored company profile will remain.</p>
            <label>Type <strong>{competitor?.name}</strong> to confirm<input className="field" value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} autoFocus /></label>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setDeleteDialog(false)} disabled={actionPending}>Cancel</button><button type="button" className="danger-button" onClick={() => void clearPipelineData()} disabled={actionPending || deleteConfirmation !== competitor?.name}>{actionPending ? 'Deleting data' : 'Delete permanently'}</button></div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
