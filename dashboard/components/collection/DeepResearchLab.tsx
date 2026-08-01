'use client';

import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Icon } from '@/components/Icon';
import { EmptyState, ErrorState, LoadingState, MetricTile, PageHeading, Panel, formatDate } from '@/components/company/PagePrimitives';
import { cancelDeepResearchRun, createDeepResearchRun, getDeepResearchOverview, getDeepResearchRun, testTorConnection } from '@/lib/api';
import type { DeepResearchOverview, DeepResearchRun } from '@/lib/types';

const TERMINAL = new Set(['completed', 'partial', 'failed', 'cancelled']);

function label(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function DeepResearchLab({ competitorId, dataVersion, onIntelligenceChanged }: {
  competitorId: number; dataVersion: number; onIntelligenceChanged: () => void;
}) {
  const [overview, setOverview] = useState<DeepResearchOverview | null>(null);
  const [selectedRun, setSelectedRun] = useState<DeepResearchRun | null>(null);
  const [query, setQuery] = useState('');
  const [maxResults, setMaxResults] = useState(20);
  const [maxPages, setMaxPages] = useState(8);
  const [acknowledged, setAcknowledged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const next = await getDeepResearchOverview(competitorId);
    setOverview(next);
    setMaxResults((current) => Math.min(current, next.limits.max_results));
    setMaxPages((current) => Math.min(current, next.limits.max_pages));
    const active = next.runs.find((run) => !TERMINAL.has(run.status)) || next.latest_run;
    if (active) setSelectedRun(await getDeepResearchRun(competitorId, active.id));
  }, [competitorId]);

  useEffect(() => {
    let cancelled = false;
    getDeepResearchOverview(competitorId)
      .then(async (next) => {
        if (cancelled) return;
        setOverview(next);
        setMaxResults(Math.min(20, next.limits.max_results));
        setMaxPages(Math.min(8, next.limits.max_pages));
        if (next.latest_run) setSelectedRun(await getDeepResearchRun(competitorId, next.latest_run.id));
      })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Deep Research Lab is unavailable.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [competitorId, dataVersion]);

  const active = overview?.runs.find((run) => !TERMINAL.has(run.status));
  const activeRunId = active?.id;
  useEffect(() => {
    if (!activeRunId) return;
    const timer = window.setInterval(() => {
      refresh().then(() => onIntelligenceChanged()).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeRunId, refresh, onIntelligenceChanged]);

  const start = async (event: FormEvent) => {
    event.preventDefault();
    setBusy('start'); setError(null); setNotice(null);
    try {
      const run = await createDeepResearchRun(competitorId, { query: query.trim() || undefined, max_results: maxResults, max_pages: maxPages, acknowledge_authorized_use: acknowledged });
      setSelectedRun(run); setNotice('Deep Research run queued. Tor routing will be verified before any search starts.'); setAcknowledged(false);
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The run could not be started.'); }
    finally { setBusy(null); }
  };

  const testTor = async () => {
    setBusy('tor'); setError(null); setNotice(null);
    try { const result = await testTorConnection(competitorId); setNotice(result.message); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Tor routing test failed.'); }
    finally { setBusy(null); }
  };

  const cancel = async () => {
    if (!active) return;
    setBusy('cancel');
    try { await cancelDeepResearchRun(competitorId, active.id); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'The run could not be cancelled.'); }
    finally { setBusy(null); }
  };

  const stats = useMemo(() => ({
    runs: overview?.runs.length || 0,
    discovered: Number(selectedRun?.summary.discovered || selectedRun?.checkpoint.discovered || 0),
    collected: Number(selectedRun?.summary.collected || 0),
    failed: Number(selectedRun?.summary.failed || 0),
  }), [overview, selectedRun]);

  if (loading) return <LoadingState label="Loading Deep Research Lab" />;
  if (!overview) return <ErrorState message={error || 'Deep Research Lab is unavailable.'} onRetry={() => refresh().catch(() => undefined)} />;

  return (
    <div className="deep-research-lab">
      <PageHeading eyebrow="Experimental collection" title="Deep Research Lab" description="Search publicly reachable Tor hidden services for company mentions, then preserve bounded results as low-trust evidence for review." actions={<button type="button" className="secondary-button" onClick={testTor} disabled={!overview.enabled || busy === 'tor'}><Icon name="activity" size={15} />{busy === 'tor' ? 'Testing Tor' : 'Test Tor route'}</button>} />

      <div className="deep-policy-banner"><Icon name="shield" size={20} /><div><strong>Experimental pre-alpha · explicit content warning</strong><p>Hidden-service results may be graphic, sexual, violent, hateful, unlawful, malicious, or false. No logins, forms, downloads, recursive crawling, or arbitrary URLs are permitted. Every result is unverified and must be corroborated.</p></div><span>PRE-ALPHA</span></div>
      {error ? <div className="social-run-diagnostic error"><Icon name="error" size={17} /><div><strong>Deep Research error</strong><p>{error}</p></div></div> : null}
      {notice ? <div className="social-run-diagnostic info"><Icon name="check" size={17} /><div><strong>Lab status</strong><p>{notice}</p></div></div> : null}

      <section className="metric-grid compact-grid">
        <MetricTile label="Runs" value={stats.runs} note="Local investigations" icon="archive" />
        <MetricTile label="Discovered" value={stats.discovered} note="Unique onion results" icon="search" />
        <MetricTile label="Evidence" value={stats.collected} note="Review required" icon="database" tone="good" />
        <MetricTile label="Failed" value={stats.failed} note="Unavailable or rejected" icon="error" tone={stats.failed ? 'warning' : 'neutral'} />
      </section>

      <div className="deep-lab-grid">
        <Panel title="Launch bounded research" eyebrow="Query builder">
          {!overview.enabled ? <div className="deep-disabled-state"><Icon name="settings" size={19} /><div><strong>Deep Research is disabled</strong><p>Enable it under Settings → Collection. The Tor service remains separate and optional.</p></div></div> : null}
          <form className="deep-query-form" onSubmit={start}>
            <label><span>Research query</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Leave blank to use the company name" disabled={!overview.enabled || Boolean(active)} /><small>Use a company, brand, product, executive, or incident phrase. Scope does not accept direct target URLs.</small></label>
            <div><label><span>Results to discover</span><input type="number" min={1} max={overview.limits.max_results} value={maxResults} onChange={(event) => setMaxResults(Number(event.target.value))} /></label><label><span>Pages to preserve</span><input type="number" min={1} max={overview.limits.max_pages} value={maxPages} onChange={(event) => setMaxPages(Number(event.target.value))} /></label></div>
            <label className="deep-ack"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>I confirm this research is lawful, authorized, and limited to public information.</span></label>
            <button type="submit" className="primary-button" disabled={!overview.enabled || !acknowledged || Boolean(active) || busy === 'start'}><Icon name="search" size={15} />{busy === 'start' ? 'Queuing research' : active ? 'Run in progress' : 'Start deep research'}</button>
          </form>
        </Panel>

        <Panel title="Run console" eyebrow={selectedRun ? `Run #${selectedRun.id}` : 'No run selected'}>
          {selectedRun ? <div className="deep-run-console"><header><span className={`social-run-status ${selectedRun.status}`}><i />{label(selectedRun.status)}</span><strong>{selectedRun.query}</strong></header><div className="deep-run-progress"><span>{label(selectedRun.checkpoint.stage || selectedRun.status)}</span><strong>{Number(selectedRun.checkpoint.current || 0)} / {Number(selectedRun.checkpoint.total || 0)}</strong></div>{selectedRun.error ? <div className="deep-console-error">{selectedRun.error}<small>{String(selectedRun.summary.suggested_action || '')}</small></div> : null}{active?.id === selectedRun.id ? <button type="button" className="danger-button" onClick={cancel} disabled={busy === 'cancel'}>{busy === 'cancel' ? 'Cancelling' : 'Cancel run'}</button> : null}<div className="deep-engine-list">{(selectedRun.checkpoint.engines || []).map((engine) => <span key={engine.engine} className={engine.ok ? 'ok' : 'failed'}><i />{engine.engine}<small>{engine.ok ? `${engine.results || 0} results` : label(engine.code || 'Unavailable')}</small></span>)}</div></div> : <EmptyState title="No deep research runs" description="Your first bounded run will show live engine diagnostics here." />}
        </Panel>
      </div>

      <Panel title="Evidence candidates" eyebrow="Unverified hidden-service sources" action={selectedRun ? <span className="panel-count">{selectedRun.results?.length || 0} results</span> : undefined}>
        {selectedRun?.results?.length ? <div className="deep-result-list">{selectedRun.results.map((result) => <article key={result.id}><div><span className={`deep-result-state ${result.fetch_status}`}>{label(result.fetch_status)}</span><small>{result.engine} · {formatDate(result.collected_at || result.discovered_at, true)}</small></div><h3>{result.title || 'Untitled hidden-service result'}</h3><p>{result.excerpt || 'Discovered by a search engine; readable evidence was not collected.'}</p><footer><span>{result.evidence_id ? `Evidence #${result.evidence_id}` : 'No evidence record'}</span><a href={result.source_url} target="_blank" rel="noreferrer">Open via Tor browser <Icon name="arrow" size={12} /></a></footer></article>)}</div> : <EmptyState title="No evidence candidates yet" description="Discovered and collected results will appear here with provenance and review status." />}
      </Panel>
    </div>
  );
}
