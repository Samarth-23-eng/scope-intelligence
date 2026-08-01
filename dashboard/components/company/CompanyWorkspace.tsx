'use client';

import Link from 'next/link';
import { useParams, usePathname } from 'next/navigation';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { Icon, type IconName } from '@/components/Icon';
import { getCompetitor, getPipelineStatus, runPipeline } from '@/lib/api';
import type { Competitor, PipelineStatus } from '@/lib/types';

type CompanyWorkspaceValue = {
  competitorId: number;
  competitor: Competitor | null;
  loading: boolean;
  error: string | null;
  pipelineStatus: PipelineStatus | null;
  pipelineRunning: boolean;
  pipelineError: string | null;
  dataVersion: number;
  runCollection: () => Promise<void>;
  refreshWorkspace: () => void;
};

const CompanyWorkspaceContext = createContext<CompanyWorkspaceValue | null>(null);

const sections: Array<{
  label: string;
  description: string;
  segment: string;
  icon: IconName;
  group: string;
}> = [
  { label: 'Briefing', description: 'Company assessment', segment: '', icon: 'grid', group: 'Dossier' },
  { label: 'Intelligence', description: 'Signals and events', segment: 'intelligence', icon: 'activity', group: 'Analysis' },
  { label: 'Research', description: 'Agent investigations', segment: 'research', icon: 'spark', group: 'Analysis' },
  { label: 'Evidence', description: 'Sources and claims', segment: 'evidence', icon: 'book', group: 'Analysis' },
  { label: 'Relationships', description: 'Entity graph', segment: 'relationships', icon: 'network', group: 'Analysis' },
  { label: 'Collection Studio', description: 'Social & public sources', segment: 'collection', icon: 'layers', group: 'Collection' },
  { label: 'Reports', description: 'Briefings and export', segment: 'reports', icon: 'document', group: 'Output' },
  { label: 'Operations', description: 'Pipeline and sources', segment: 'operations', icon: 'settings', group: 'System' },
];

function statusCopy(status: PipelineStatus | null) {
  if (!status || status.status === 'idle') return 'Ready for collection';
  if (status.status === 'queued') return 'Collection queued';
  if (status.status === 'running') {
    const stage = status.stage ? status.stage.replaceAll('_', ' ') : 'pipeline';
    return `Collecting · ${stage}`;
  }
  if (status.status === 'partial') return 'Completed with warnings';
  if (status.status === 'failed') return 'Collection needs attention';
  if (status.status === 'cancelled') return 'Collection cancelled';
  return 'Collection complete';
}

export function useCompanyWorkspace() {
  const value = useContext(CompanyWorkspaceContext);
  if (!value) {
    throw new Error('useCompanyWorkspace must be used inside CompanyWorkspace');
  }
  return value;
}

export function CompanyWorkspace({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const pathname = usePathname();
  const competitorId = Number(params.id);
  const [competitor, setCompetitor] = useState<Competitor | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [pipelinePollKey, setPipelinePollKey] = useState(0);
  const [dataVersion, setDataVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getCompetitor(competitorId)
      .then((result) => {
        if (!cancelled) setCompetitor(result);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : 'Company profile could not be loaded.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [competitorId]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let previousStatus: string | null = null;

    const poll = async () => {
      try {
        const status = await getPipelineStatus(competitorId);
        if (cancelled) return;
        setPipelineStatus(status);
        setPipelineError(null);
        if (
          previousStatus &&
          ['queued', 'running'].includes(previousStatus) &&
          ['completed', 'partial', 'failed', 'cancelled'].includes(status.status)
        ) {
          setDataVersion((version) => version + 1);
        }
        previousStatus = status.status;
        if (status.status === 'running' || status.status === 'queued') {
          timer = setTimeout(poll, 3000);
        }
      } catch (reason) {
        if (!cancelled) {
          setPipelineError(
            reason instanceof Error ? reason.message : 'Pipeline status is unavailable.',
          );
        }
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [competitorId, pipelinePollKey]);

  const runCollection = useCallback(async () => {
    setPipelineError(null);
    try {
      const result = await runPipeline(competitorId);
      setPipelineStatus((current) => ({
        status: 'queued',
        competitor_id: competitorId,
        stage: 'collection',
        stage_status: 'queued',
        started_at: new Date().toISOString(),
        finished_at: null,
        results: current?.results ?? {},
        models: current?.models ?? {},
        error: null,
        run_id: result.run_id,
      }));
      setPipelinePollKey((key) => key + 1);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Collection could not be started.';
      setPipelineError(message);
    }
  }, [competitorId]);

  const refreshWorkspace = useCallback(() => {
    setDataVersion((version) => version + 1);
    setPipelinePollKey((key) => key + 1);
  }, []);

  const pipelineRunning =
    pipelineStatus?.status === 'queued' || pipelineStatus?.status === 'running';

  const value = useMemo<CompanyWorkspaceValue>(
    () => ({
      competitorId,
      competitor,
      loading,
      error,
      pipelineStatus,
      pipelineRunning,
      pipelineError,
      dataVersion,
      runCollection,
      refreshWorkspace,
    }),
    [
      competitorId,
      competitor,
      loading,
      error,
      pipelineStatus,
      pipelineRunning,
      pipelineError,
      dataVersion,
      runCollection,
      refreshWorkspace,
    ],
  );

  const basePath = `/competitors/${competitorId}`;
  const initial = competitor?.name?.slice(0, 1).toUpperCase() ?? 'C';

  if (!Number.isFinite(competitorId)) {
    return (
      <main className="page-wrap">
        <div className="page-state error">
          <Icon name="error" size={22} />
          <div>
            <strong>Invalid company reference</strong>
            <p>Return to the portfolio and select a valid company dossier.</p>
          </div>
        </div>
      </main>
    );
  }

  const groupedSections = sections.reduce<Array<{ group: string; items: typeof sections }>>(
    (groups, section) => {
      const existing = groups.find((group) => group.group === section.group);
      if (existing) existing.items.push(section);
      else groups.push({ group: section.group, items: [section] });
      return groups;
    },
    [],
  );

  return (
    <CompanyWorkspaceContext.Provider value={value}>
      <div className="company-workspace">
        <aside className="company-context-sidebar">
          <div className="company-context-identity">
            <Link href="/" className="company-back-link">
              <Icon name="arrow" size={14} />
              Portfolio
            </Link>
            <div className="company-context-title">
              <span className="company-monogram">{initial}</span>
              <div>
                {loading ? <div className="company-title-skeleton" /> : <h1>{competitor?.name ?? 'Company unavailable'}</h1>}
                <p>{competitor?.domain || 'Name-first identity'}</p>
              </div>
            </div>
          </div>

          <nav className="company-section-nav" aria-label="Company intelligence sections">
            {groupedSections.map((group) => (
              <div className="company-nav-group" key={group.group}>
                <p>{group.group}</p>
                {group.items.map((section) => {
                  const href = section.segment ? `${basePath}/${section.segment}` : basePath;
                  const active = section.segment === '' ? pathname === basePath : pathname.startsWith(href);
                  return (
                    <Link key={section.label} href={href} className={active ? 'active' : ''}>
                      <Icon name={section.icon} size={17} />
                      <span>
                        <strong>{section.label}</strong>
                        <small>{section.description}</small>
                      </span>
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>

          <div className="company-context-footer">
            <div className="company-pipeline-state">
              <span className={pipelineRunning ? 'status-pulse pulse-animated' : 'status-pulse'} />
              <div>
                <strong>{statusCopy(pipelineStatus)}</strong>
                <small>{pipelineStatus?.run_id ? `Run #${pipelineStatus.run_id}` : 'No active run'}</small>
              </div>
            </div>
            <button type="button" className="primary-button" onClick={() => void runCollection()} disabled={pipelineRunning || loading}>
              <Icon name={pipelineRunning ? 'refresh' : 'play'} size={15} />
              {pipelineRunning ? 'Collection running' : 'Run collection'}
            </button>
          </div>
        </aside>

        <section className="company-canvas">
          <header className="company-canvas-bar">
            <div>
              <span>{competitor?.industry || 'Company intelligence'}</span>
              {competitor?.hq ? <strong>{competitor.hq}</strong> : null}
            </div>
            <div className="company-canvas-actions">
              <span className={`identity-badge ${competitor?.domain_verified ? 'verified' : ''}`}>
                <Icon name={competitor?.domain_verified ? 'check' : 'search'} size={13} />
                {competitor?.domain_verified ? 'Verified identity' : 'Name-first identity'}
              </span>
              <Link href={`${basePath}/operations`} className="icon-button" aria-label="Open company settings" title="Company settings">
                <Icon name="settings" size={17} />
              </Link>
            </div>
          </header>

          {error || pipelineError ? (
            <div className="company-notice-wrap">
              <div className="feedback-banner error" role="alert">
                <Icon name="error" size={17} />
                <div>
                  <strong>{error ? 'Company profile error' : 'Collection error'}</strong>
                  <span>{error ?? pipelineError}</span>
                </div>
                <Link href={`${basePath}/operations`}>Open diagnostics</Link>
              </div>
            </div>
          ) : null}

          {children}
        </section>
      </div>
    </CompanyWorkspaceContext.Provider>
  );
}
