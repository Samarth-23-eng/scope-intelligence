'use client';

import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { Icon } from '@/components/Icon';
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
  cancelSocialRun,
  createSocialRun,
  getSocialComments,
  getSocialConnectors,
  getSocialOverview,
  getSocialPosts,
  getSocialProfiles,
  getSocialRun,
  getSocialRuns,
} from '@/lib/api';
import type {
  SocialCollectionMode,
  SocialCommentRecord,
  SocialConnector,
  SocialOverview,
  SocialPostRecord,
  SocialProfileRecord,
  SocialRun,
} from '@/lib/types';

type StudioView = 'collect' | 'live' | 'content' | 'history';
type RecordKind = 'posts' | 'profiles' | 'comments';
type SelectedRecord = SocialPostRecord | SocialProfileRecord | SocialCommentRecord;

const TERMINAL = new Set(['completed', 'partial', 'failed', 'cancelled']);

const modeCopy: Record<
  SocialCollectionMode,
  { label: string; description: string; placeholder: string }
> = {
  discover: {
    label: 'Discover',
    description: 'Find videos around a company, product, executive, or narrative.',
    placeholder: 'Company, product, executive, or campaign query',
  },
  account: {
    label: 'Account Monitor',
    description: 'Collect recent public activity from a known company channel.',
    placeholder: 'https://www.youtube.com/@OpenAI',
  },
  evidence: {
    label: 'Evidence Capture',
    description: 'Preserve one exact video with provenance and optional conversation.',
    placeholder: 'https://www.youtube.com/watch?v=...',
  },
};

function humanize(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function numericSummary(value: Record<string, unknown>, key: string) {
  const candidate = value[key];
  return typeof candidate === 'number' ? candidate : 0;
}

function statusLabel(status: SocialRun['status']) {
  if (status === 'queued') return 'Queued';
  if (status === 'running') return 'Collecting';
  if (status === 'partial') return 'Review warnings';
  return humanize(status);
}

function targetForRun(run: SocialRun) {
  return run.query || run.target_url || 'No target';
}

function recordLabel(record: SelectedRecord) {
  if ('platform_post_id' in record && 'title' in record) {
    return record.title || `${record.platform} ${record.content_type}`;
  }
  if ('platform_profile_id' in record) {
    return record.display_name || record.handle || record.platform_profile_id;
  }
  return record.text.slice(0, 90);
}

function recordSource(record: SelectedRecord) {
  if ('url' in record) return record.url;
  if ('profile_url' in record) return record.profile_url;
  return null;
}

function ConnectorCard({ connector }: { connector: SocialConnector }) {
  const configured = connector.api_key_configured;
  return (
    <article className="social-connector-card active">
      <div className="social-connector-mark">YT</div>
      <div className="social-connector-main">
        <div className="social-connector-title">
          <div>
            <strong>{connector.label}</strong>
            <span>Reference connector · v{connector.version}</span>
          </div>
          <span className="social-readiness ready">Public collection ready</span>
        </div>
        <div className="social-feature-grid">
          {Object.entries(connector.features).map(([feature, state]) => (
            <span key={feature} className={state}>
              <Icon name={state === 'ready' ? 'check' : 'settings'} size={13} />
              {humanize(feature)}
            </span>
          ))}
        </div>
        <p>
          {configured
            ? 'YouTube Data API connected. Search, metrics, and public comments are available.'
            : 'Public channel feeds and direct video capture are ready. Add a YouTube API key for search, metrics, and comments.'}
        </p>
      </div>
    </article>
  );
}

function RunConsole({
  run,
  cancelling,
  onCancel,
}: {
  run: SocialRun;
  cancelling: boolean;
  onCancel: () => void;
}) {
  const current = Number(run.checkpoint.current || 0);
  const total = Number(run.checkpoint.total || 0);
  const progress =
    TERMINAL.has(run.status)
      ? 100
      : total > 0
        ? Math.min(Math.round((current / total) * 100), 96)
        : run.status === 'running'
          ? 18
          : 4;
  const persisted = run.checkpoint.persisted || {};
  const diagnostics = run.checkpoint.diagnostics || [];
  const failureCode =
    typeof run.summary.error_code === 'string' ? run.summary.error_code : null;
  const failureAction =
    typeof run.summary.suggested_action === 'string'
      ? run.summary.suggested_action
      : null;

  return (
    <div className="social-live-console">
      <div className="social-live-hero">
        <div>
          <span className={`social-run-status ${run.status}`}>
            <i />
            {statusLabel(run.status)}
          </span>
          <p className="eyebrow">RUN #{run.id} · {run.platform.toUpperCase()}</p>
          <h3>{modeCopy[run.mode].label}</h3>
          <p>{targetForRun(run)}</p>
        </div>
        {['queued', 'running'].includes(run.status) ? (
          <button
            type="button"
            className="danger-button"
            onClick={onCancel}
            disabled={cancelling}
          >
            <Icon name="close" size={14} />
            {cancelling ? 'Cancelling' : 'Cancel run'}
          </button>
        ) : null}
      </div>

      <div className="social-progress-block">
        <div>
          <span>{humanize(run.checkpoint.stage || run.task_status || run.status)}</span>
          <strong>{progress}%</strong>
        </div>
        <div className="social-progress-track">
          <i style={{ width: `${progress}%` }} />
        </div>
        <footer>
          <span>{current && total ? `${current} of ${total} posts` : 'Preparing bounded collection'}</span>
          <span>Heartbeat {formatDate(run.heartbeat_at || run.updated_at, true)}</span>
        </footer>
      </div>

      <div className="social-run-output">
        {[
          ['Profiles', Number(persisted.profiles || 0)],
          ['Posts', Number(persisted.posts || 0)],
          ['Comments', Number(persisted.comments || 0)],
          ['Evidence', Number(persisted.evidence || 0)],
        ].map(([label, value]) => (
          <div key={String(label)}>
            <strong>{value}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>

      {run.error ? (
        <div className="social-run-diagnostic error">
          <Icon name="error" size={17} />
          <div>
            <strong>{failureCode ? `Error: ${failureCode}` : 'Collection stopped'}</strong>
            <p>{run.error}</p>
            {failureAction ? <span>{failureAction}</span> : null}
          </div>
        </div>
      ) : null}

      {diagnostics.map((diagnostic) => (
        <div
          className={`social-run-diagnostic ${diagnostic.severity}`}
          key={`${diagnostic.code}-${diagnostic.message}`}
        >
          <Icon name={diagnostic.severity === 'error' ? 'error' : 'activity'} size={17} />
          <div>
            <strong>{humanize(diagnostic.code)}</strong>
            <p>{diagnostic.message}</p>
            {diagnostic.suggested_action ? <span>{diagnostic.suggested_action}</span> : null}
          </div>
        </div>
      ))}

      <div className="social-event-stream">
        <header>
          <strong>Run activity</strong>
          <span>{run.events?.length || 0} events</span>
        </header>
        {run.events?.length ? (
          run.events.slice().reverse().map((event) => (
            <article key={event.id}>
              <i className={event.success ? 'success' : 'failure'} />
              <div>
                <strong>{humanize(event.event_type)}</strong>
                <span>{event.items ? `${event.items} items · ` : ''}{formatDate(event.created_at, true)}</span>
              </div>
            </article>
          ))
        ) : (
          <p className="social-event-empty">The first connector event will appear here.</p>
        )}
      </div>
    </div>
  );
}

export function SocialCollectionStudio({
  competitorId,
  dataVersion,
  onIntelligenceChanged,
}: {
  competitorId: number;
  dataVersion: number;
  onIntelligenceChanged: () => void;
}) {
  const [view, setView] = useState<StudioView>('collect');
  const [overview, setOverview] = useState<SocialOverview | null>(null);
  const [connectors, setConnectors] = useState<SocialConnector[]>([]);
  const [runs, setRuns] = useState<SocialRun[]>([]);
  const [profiles, setProfiles] = useState<SocialProfileRecord[]>([]);
  const [posts, setPosts] = useState<SocialPostRecord[]>([]);
  const [comments, setComments] = useState<SocialCommentRecord[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [selectedRun, setSelectedRun] = useState<SocialRun | null>(null);
  const [recordKind, setRecordKind] = useState<RecordKind>('posts');
  const [selectedRecord, setSelectedRecord] = useState<SelectedRecord | null>(null);
  const [mode, setMode] = useState<SocialCollectionMode>('account');
  const [target, setTarget] = useState('');
  const [maxItems, setMaxItems] = useState(8);
  const [includeComments, setIncludeComments] = useState(false);
  const [commentLimit, setCommentLimit] = useState(30);
  const [includeReplies, setIncludeReplies] = useState(false);
  const [includeTranscript, setIncludeTranscript] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const youtube = connectors.find((connector) => connector.platform === 'youtube');
  const activeRun = runs.find((run) => ['queued', 'running'].includes(run.status));
  const apiConfigured = Boolean(youtube?.api_key_configured);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [overviewResult, connectorResult, runResult, profileResult, postResult, commentResult] =
        await Promise.all([
          getSocialOverview(competitorId),
          getSocialConnectors(competitorId),
          getSocialRuns(competitorId),
          getSocialProfiles(competitorId),
          getSocialPosts(competitorId),
          getSocialComments(competitorId),
        ]);
      setOverview(overviewResult);
      setConnectors(connectorResult);
      setRuns(runResult);
      setProfiles(profileResult);
      setPosts(postResult);
      setComments(commentResult);

      const preferredRunId =
        runResult.find((run) => ['queued', 'running'].includes(run.status))?.id ||
        selectedRunId ||
        runResult[0]?.id ||
        null;
      if (preferredRunId) {
        const detail = await getSocialRun(competitorId, preferredRunId);
        setSelectedRun(detail);
        setSelectedRunId(preferredRunId);
      } else {
        setSelectedRun(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Collection Studio could not be loaded.');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [competitorId, selectedRunId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [competitorId, dataVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!activeRun) return;
    const timer = setInterval(() => void load(true), 2500);
    return () => clearInterval(timer);
  }, [activeRun?.id, load]); // eslint-disable-line react-hooks/exhaustive-deps

  const startRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createSocialRun(competitorId, {
        platform: 'youtube',
        mode,
        target: target.trim(),
        options: {
          max_items: mode === 'evidence' ? 1 : maxItems,
          include_comments: apiConfigured && includeComments,
          comment_limit: apiConfigured && includeComments ? commentLimit : 0,
          include_replies: apiConfigured && includeComments && includeReplies,
          max_reply_depth: apiConfigured && includeComments && includeReplies ? 1 : 0,
          include_transcript: includeTranscript,
        },
      });
      setSelectedRunId(created.id);
      setSelectedRun(created);
      setRuns((current) => [created, ...current.filter((run) => run.id !== created.id)]);
      setView('live');
      setNotice(`Run #${created.id} queued. Scope will preserve each result with provenance.`);
      window.setTimeout(() => void load(true), 500);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Social collection could not be started.');
    } finally {
      setSubmitting(false);
    }
  };

  const cancelRun = async () => {
    if (!selectedRun) return;
    setCancelling(true);
    setError(null);
    try {
      setSelectedRun(await cancelSocialRun(competitorId, selectedRun.id));
      setNotice(`Cancellation requested for run #${selectedRun.id}.`);
      await load(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Run cancellation failed.');
    } finally {
      setCancelling(false);
    }
  };

  const selectRun = async (runId: number, nextView: StudioView = 'live') => {
    setSelectedRunId(runId);
    setView(nextView);
    try {
      setSelectedRun(await getSocialRun(competitorId, runId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Run details could not be loaded.');
    }
  };

  const records = useMemo<SelectedRecord[]>(() => {
    if (recordKind === 'profiles') return [...profiles];
    if (recordKind === 'comments') return [...comments];
    return [...posts];
  }, [comments, posts, profiles, recordKind]);

  const previousActiveStatus = selectedRun?.status;
  useEffect(() => {
    if (previousActiveStatus && TERMINAL.has(previousActiveStatus)) {
      onIntelligenceChanged();
    }
  }, [previousActiveStatus, onIntelligenceChanged]);

  return (
    <main className="company-page social-studio">
      <PageHeading
        eyebrow="SOCIAL COLLECTION STUDIO"
        title="Collect conversations, channels, and media evidence"
        description="Run bounded platform research, inspect exact progress, and promote normalized social records into the same evidence and relationship system as the rest of Scope."
        actions={
          <button
            type="button"
            className="secondary-button"
            onClick={() => void load()}
            disabled={loading}
          >
            <Icon name="refresh" size={15} />
            Refresh studio
          </button>
        }
      />

      <div className="experimental-content-warning">
        <Icon name="error" size={18} />
        <div>
          <strong>Experimental pre-alpha content warning</strong>
          <p>Public comments and transcripts may contain explicit, graphic, hateful, false, or otherwise disturbing material. Treat every record as untrusted evidence and review it before use.</p>
        </div>
        <span>PRE-ALPHA</span>
      </div>

      <section className="workspace-metric-grid">
        <MetricTile
          label="Tracked accounts"
          value={overview?.profiles ?? 0}
          note="Normalized public profiles"
          icon="building"
          tone={overview?.profiles ? 'good' : 'neutral'}
        />
        <MetricTile
          label="Collected content"
          value={overview?.posts ?? 0}
          note={`${overview?.observations ?? 0} historical observations`}
          icon="layers"
          tone={overview?.posts ? 'good' : 'neutral'}
        />
        <MetricTile
          label="Conversation records"
          value={overview?.comments ?? 0}
          note="Identity-minimized public comments"
          icon="book"
        />
        <MetricTile
          label="Collection state"
          value={overview?.active_runs ? 'Live' : 'Ready'}
          note={
            overview?.refresh_due
              ? `${overview.refresh_due} records due for refresh`
              : 'Retention state healthy'
          }
          icon={overview?.active_runs ? 'activity' : 'shield'}
          tone={overview?.refresh_due ? 'warning' : overview?.active_runs ? 'good' : 'neutral'}
        />
      </section>

      <div className="view-switcher social-studio-switcher" role="tablist">
        {([
          ['collect', 'Collect', null],
          ['live', 'Live runs', overview?.active_runs ?? 0],
          ['content', 'Content', overview?.posts ?? 0],
          ['history', 'Run history', runs.length],
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

      {notice ? (
        <div className="feedback-banner success">
          <Icon name="check" size={16} />
          <div><strong>Collection update</strong><span>{notice}</span></div>
        </div>
      ) : null}
      {error ? <ErrorState title="Collection Studio needs attention" message={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingState label="Loading Social Collection Studio" /> : null}

      {!loading && view === 'collect' ? (
        <div className="social-launch-layout">
          <Panel eyebrow="NEW COLLECTION" title="Configure a bounded research run" className="social-launcher-panel">
            <form className="social-launch-form" onSubmit={startRun}>
              <div className="social-mode-grid">
                {(Object.keys(modeCopy) as SocialCollectionMode[]).map((item) => (
                  <button
                    type="button"
                    key={item}
                    className={mode === item ? 'active' : ''}
                    onClick={() => {
                      setMode(item);
                      setTarget('');
                    }}
                  >
                    <span>{item === 'discover' ? '01' : item === 'account' ? '02' : '03'}</span>
                    <strong>{modeCopy[item].label}</strong>
                    <p>{modeCopy[item].description}</p>
                  </button>
                ))}
              </div>

              <label className="social-field">
                <span>{mode === 'discover' ? 'Research query' : mode === 'account' ? 'Channel target' : 'Evidence URL'}</span>
                <input
                  required
                  value={target}
                  onChange={(event) => setTarget(event.target.value)}
                  placeholder={modeCopy[mode].placeholder}
                  autoComplete="off"
                />
                {mode === 'discover' && !apiConfigured ? (
                  <small>Keyword discovery needs a YouTube Data API key. A direct channel or video URL still works.</small>
                ) : null}
              </label>

              <div className="social-budget-grid">
                <label>
                  <span>Content budget</span>
                  <div>
                    <input
                      type="range"
                      min="1"
                      max="25"
                      value={mode === 'evidence' ? 1 : maxItems}
                      disabled={mode === 'evidence'}
                      onChange={(event) => setMaxItems(Number(event.target.value))}
                    />
                    <strong>{mode === 'evidence' ? 1 : maxItems}</strong>
                  </div>
                  <small>Maximum posts or videos for this run</small>
                </label>
                <label>
                  <span>Comment budget</span>
                  <div>
                    <input
                      type="range"
                      min="5"
                      max="100"
                      step="5"
                      value={commentLimit}
                      disabled={!includeComments}
                      onChange={(event) => setCommentLimit(Number(event.target.value))}
                    />
                    <strong>{includeComments ? commentLimit : 0}</strong>
                  </div>
                  <small>Maximum comments per collected video</small>
                </label>
              </div>

              <div className="social-option-grid">
                <label className={!apiConfigured ? 'disabled' : ''}>
                  <input
                    type="checkbox"
                    checked={apiConfigured && includeComments}
                    disabled={!apiConfigured}
                    onChange={(event) => {
                      setIncludeComments(event.target.checked);
                      if (!event.target.checked) setIncludeReplies(false);
                    }}
                  />
                  <span>
                    <strong>Collect public comments</strong>
                    <small>{apiConfigured ? 'Preserve text, timestamps, and thread structure' : 'YouTube API key required'}</small>
                  </span>
                </label>
                <label className={!includeComments ? 'disabled' : ''}>
                  <input
                    type="checkbox"
                    checked={includeReplies}
                    disabled={!includeComments}
                    onChange={(event) => setIncludeReplies(event.target.checked)}
                  />
                  <span>
                    <strong>Follow reply threads</strong>
                    <small>Collect one complete public reply level</small>
                  </span>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={includeTranscript}
                    onChange={(event) => setIncludeTranscript(event.target.checked)}
                  />
                  <span>
                    <strong>Experimental transcript</strong>
                    <small>Opt-in public transcript capture when available</small>
                  </span>
                </label>
              </div>

              <div className="social-policy-note">
                <Icon name="shield" size={17} />
                <div>
                  <strong>Privacy-minimized collection</strong>
                  <p>Scope does not retain YouTube commenter names, handles, channel IDs, cookies, or session credentials.</p>
                </div>
              </div>

              <button
                type="submit"
                className="primary-button social-run-button"
                disabled={submitting || Boolean(activeRun) || !target.trim()}
              >
                <Icon name={submitting ? 'refresh' : 'play'} size={16} />
                {submitting ? 'Preparing collection' : activeRun ? 'A collection is already active' : 'Start collection'}
              </button>
            </form>
          </Panel>

          <div className="social-connector-stack">
            <Panel eyebrow="CONNECTOR READINESS" title="Collection channels">
              {connectors.map((connector) => (
                <ConnectorCard connector={connector} key={connector.platform} />
              ))}
              <div className="social-coming-connectors">
                <article>
                  <span>RD</span>
                  <div><strong>Reddit</strong><p>Community search and discussion threads</p></div>
                  <em>Next connector</em>
                </article>
                <article>
                  <span>WB</span>
                  <div><strong>Authenticated browser</strong><p>Local encrypted Session Vault</p></div>
                  <em>Planned</em>
                </article>
              </div>
            </Panel>
            <Panel eyebrow="COLLECTION CONTRACT" title="What every run preserves">
              <div className="social-contract-list">
                {[
                  ['Normalized records', 'Profiles, posts, comments, and engagement snapshots'],
                  ['Evidence linkage', 'Every content record connects to its exact evidence version'],
                  ['Exact diagnostics', 'Quotas, access failures, disabled comments, and invalid targets'],
                  ['Bounded execution', 'Visible item limits, cancellation, timeouts, and retention dates'],
                ].map(([title, description]) => (
                  <div key={title}><Icon name="check" size={15} /><span><strong>{title}</strong><small>{description}</small></span></div>
                ))}
              </div>
            </Panel>
          </div>
        </div>
      ) : null}

      {!loading && view === 'live' ? (
        selectedRun ? (
          <div className="social-live-layout">
            <Panel className="social-live-panel">
              <RunConsole run={selectedRun} cancelling={cancelling} onCancel={() => void cancelRun()} />
            </Panel>
            <Panel eyebrow="RUN QUEUE" title="Recent collection runs">
              <div className="social-run-queue">
                {runs.slice(0, 8).map((run) => (
                  <button
                    type="button"
                    className={selectedRun.id === run.id ? 'active' : ''}
                    key={run.id}
                    onClick={() => void selectRun(run.id)}
                  >
                    <span className={`social-run-dot ${run.status}`} />
                    <div><strong>Run #{run.id}</strong><small>{modeCopy[run.mode].label} · {formatDate(run.created_at, true)}</small></div>
                    <em>{statusLabel(run.status)}</em>
                  </button>
                ))}
              </div>
            </Panel>
          </div>
        ) : (
          <EmptyState
            icon="activity"
            title="No social collection run yet"
            description="Configure the first bounded run to see live connector events and exact diagnostics."
            action={<button type="button" className="primary-button" onClick={() => setView('collect')}>Configure collection</button>}
          />
        )
      ) : null}

      {!loading && view === 'content' ? (
        <div className="social-content-layout">
          <Panel className="social-record-browser">
            <div className="social-record-tabs">
              {([
                ['posts', 'Posts & videos', posts.length],
                ['profiles', 'Accounts', profiles.length],
                ['comments', 'Comments', comments.length],
              ] as const).map(([kind, label, count]) => (
                <button
                  type="button"
                  key={kind}
                  className={recordKind === kind ? 'active' : ''}
                  onClick={() => {
                    setRecordKind(kind);
                    setSelectedRecord(null);
                  }}
                >
                  {label}<span>{count}</span>
                </button>
              ))}
            </div>
            {records.length ? (
              <div className="social-record-list">
                {records.map((record) => (
                  <button
                    type="button"
                    key={`${recordKind}-${record.id}`}
                    className={selectedRecord?.id === record.id ? 'active' : ''}
                    onClick={() => setSelectedRecord(record)}
                  >
                    <span className="social-platform-badge">{record.platform.slice(0, 2).toUpperCase()}</span>
                    <div>
                      <strong>{recordLabel(record)}</strong>
                      <p>
                        {'depth' in record
                          ? `${record.depth ? 'Reply' : 'Top-level comment'} · ${record.like_count} likes`
                          : 'follower_count' in record
                            ? `${record.follower_count ?? '—'} followers · ${record.content_count ?? '—'} posts`
                            : `${humanize(record.content_type)} · ${Object.entries(record.engagement).map(([key, value]) => `${humanize(key)} ${value}`).join(' · ') || 'Public metadata'}`}
                      </p>
                    </div>
                    <time>{formatDate('published_at' in record ? record.published_at : record.last_seen_at, true)}</time>
                    <Icon name="arrow" size={15} />
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState
                title={`No ${recordKind} collected`}
                description="Run Collection Studio to populate normalized, evidence-linked social records."
              />
            )}
          </Panel>

          <Panel eyebrow="RECORD INSPECTOR" title={selectedRecord ? recordLabel(selectedRecord) : 'Select a record'} className="social-record-inspector">
            {selectedRecord ? (
              <div className="social-inspector-body">
                <div className="social-inspector-provenance">
                  <span><Icon name="shield" size={14} /> Evidence #{selectedRecord.evidence_id ?? 'pending'}</span>
                  <span><Icon name="document" size={14} /> Version #{selectedRecord.document_version_id ?? 'pending'}</span>
                </div>
                {'body' in selectedRecord && selectedRecord.body ? <p className="social-record-copy">{selectedRecord.body}</p> : null}
                {'biography' in selectedRecord && selectedRecord.biography ? <p className="social-record-copy">{selectedRecord.biography}</p> : null}
                {'text' in selectedRecord ? <p className="social-record-copy">{selectedRecord.text}</p> : null}
                {recordSource(selectedRecord) ? (
                  <a href={recordSource(selectedRecord) || '#'} target="_blank" rel="noreferrer" className="secondary-button">
                    <Icon name="link" size={14} />
                    Open original source
                  </a>
                ) : null}
                <dl className="social-record-facts">
                  <div><dt>Platform</dt><dd>{humanize(selectedRecord.platform)}</dd></div>
                  <div><dt>First observed</dt><dd>{formatDate(selectedRecord.first_seen_at, true)}</dd></div>
                  <div><dt>Last observed</dt><dd>{formatDate(selectedRecord.last_seen_at, true)}</dd></div>
                  <div><dt>Refresh due</dt><dd>{formatDate(selectedRecord.refresh_due_at, true)}</dd></div>
                </dl>
                <details className="social-metadata-details">
                  <summary>Normalized metadata <Icon name="arrow" size={14} /></summary>
                  <pre>{JSON.stringify(selectedRecord.metadata, null, 2)}</pre>
                </details>
              </div>
            ) : (
              <EmptyState icon="search" title="Inspect collected evidence" description="Choose an account, post, video, or comment to review provenance and normalized metadata." />
            )}
          </Panel>
        </div>
      ) : null}

      {!loading && view === 'history' ? (
        <Panel eyebrow="AUDITABLE RUN HISTORY" title="Social collection runs">
          {runs.length ? (
            <div className="social-history-table">
              <header><span>Run</span><span>Mode and target</span><span>Output</span><span>Started</span><span>Status</span><span /></header>
              {runs.map((run) => (
                <article key={run.id}>
                  <strong>#{run.id}</strong>
                  <div><strong>{modeCopy[run.mode].label}</strong><p>{targetForRun(run)}</p></div>
                  <div><strong>{numericSummary(run.summary, 'posts') + numericSummary(run.summary, 'comments')}</strong><p>records</p></div>
                  <time>{formatDate(run.started_at || run.created_at, true)}</time>
                  <span className={`social-run-status ${run.status}`}><i />{statusLabel(run.status)}</span>
                  <button type="button" className="table-action" onClick={() => void selectRun(run.id)}>Inspect</button>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="No social run history" description="Completed and interrupted runs will remain available here with task-level diagnostics." />
          )}
        </Panel>
      ) : null}
    </main>
  );
}
