'use client';

import { useEffect, useState, type FormEvent } from 'react';
import { Icon } from '@/components/Icon';
import { getWorkspaceSettings, resetWorkspaceSettings, saveWorkspaceSettings } from '@/lib/api';
import type { WorkspacePreferences } from '@/lib/types';

type NumberKey = {
  [K in keyof WorkspacePreferences]: WorkspacePreferences[K] extends number ? K : never
}[keyof WorkspacePreferences];
type BooleanKey = {
  [K in keyof WorkspacePreferences]: WorkspacePreferences[K] extends boolean ? K : never
}[keyof WorkspacePreferences];

function NumberControl({ label, hint, field, value, setValue, min = 0, max, step = 1 }: {
  label: string; hint: string; field: NumberKey; value: number;
  setValue: (field: NumberKey, value: number) => void; min?: number; max?: number; step?: number;
}) {
  return <label className="settings-control"><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => setValue(field, Number(event.target.value))} /><small>{hint}</small></label>;
}

function ToggleControl({ label, hint, field, checked, setValue, warning }: {
  label: string; hint: string; field: BooleanKey; checked: boolean;
  setValue: (field: BooleanKey, value: boolean) => void; warning?: boolean;
}) {
  return <label className={warning ? 'settings-toggle warning' : 'settings-toggle'}><span><strong>{label}</strong><small>{hint}</small></span><input type="checkbox" checked={checked} onChange={(event) => setValue(field, event.target.checked)} /><i aria-hidden="true" /></label>;
}

export default function CollectionSettingsPage() {
  const [form, setForm] = useState<WorkspacePreferences | null>(null);
  const [source, setSource] = useState<'saved' | 'environment'>('environment');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getWorkspaceSettings()
      .then((result) => {
        if (cancelled) return;
        setForm(result.preferences);
        setSource(result.source);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Collection settings are unavailable.');
      });
    return () => { cancelled = true; };
  }, []);

  const setNumber = (field: NumberKey, value: number) => setForm((current) => current ? { ...current, [field]: value } : current);
  const setBoolean = (field: BooleanKey, value: boolean) => setForm((current) => current ? { ...current, [field]: value } : current);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setBusy(true); setError(null); setMessage(null);
    try {
      const result = await saveWorkspaceSettings(form);
      setForm(result.preferences); setSource(result.source);
      setMessage('Collection settings saved. New runs will use these controls immediately.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Collection settings could not be saved.');
    } finally { setBusy(false); }
  };

  const reset = async () => {
    if (!window.confirm('Restore all collection settings to the values in your local environment file?')) return;
    setBusy(true); setError(null); setMessage(null);
    try {
      const result = await resetWorkspaceSettings();
      setForm(result.settings.preferences); setSource(result.settings.source);
      setMessage('Saved overrides removed. Local environment defaults are active again.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Collection settings could not be reset.');
    } finally { setBusy(false); }
  };

  if (!form) return <main id="main-content" className="workspace-settings-page"><div className="model-settings-loading">Loading collection controls…</div></main>;

  return (
    <main id="main-content" className="workspace-settings-page">
      <header className="settings-page-hero"><div><span className="eyebrow">Acquisition engine</span><h1>Collection controls</h1><p>Set sensible research budgets and decide which collection layers Scope may use.</p></div><span className="settings-source-badge">{source === 'saved' ? 'Workspace overrides active' : 'Environment defaults'}</span></header>
      <form onSubmit={save} className="collection-settings-form">
        <section className="settings-panel">
          <div className="settings-section-heading"><span className="settings-icon"><Icon name="search" size={19} /></span><div><span className="eyebrow">Web acquisition</span><h2>Crawler budget</h2><p>Control crawl breadth, depth, speed, and document processing.</p></div></div>
          <div className="settings-control-grid">
            <NumberControl label="Maximum pages" hint="Pages allowed per crawl" field="crawler_max_pages" value={form.crawler_max_pages} setValue={setNumber} min={1} max={500} />
            <NumberControl label="Maximum depth" hint="Link levels from the starting page" field="crawler_max_depth" value={form.crawler_max_depth} setValue={setNumber} min={0} max={10} />
            <NumberControl label="Concurrency" hint="Pages fetched at the same time" field="crawler_concurrency" value={form.crawler_concurrency} setValue={setNumber} min={1} max={20} />
            <NumberControl label="Request timeout" hint="Seconds before a request is abandoned" field="crawler_request_timeout_seconds" value={form.crawler_request_timeout_seconds} setValue={setNumber} min={5} max={180} />
            <NumberControl label="Retry attempts" hint="Retries for temporary failures" field="crawler_retry_attempts" value={form.crawler_retry_attempts} setValue={setNumber} min={0} max={6} />
            <NumberControl label="Browser fallbacks" hint="Maximum rendered-page fallbacks" field="crawler_max_browser_fallbacks" value={form.crawler_max_browser_fallbacks} setValue={setNumber} min={0} max={50} />
            <NumberControl label="PDF page limit" hint="Maximum pages extracted per PDF" field="crawler_max_pdf_pages" value={form.crawler_max_pdf_pages} setValue={setNumber} min={1} max={500} />
            <NumberControl label="External profiles" hint="Maximum public profiles considered" field="crawler_max_external_profiles" value={form.crawler_max_external_profiles} setValue={setNumber} min={1} max={500} />
          </div>
          <ToggleControl label="Respect robots.txt" hint="Honor publisher crawl rules" field="crawler_respect_robots" checked={form.crawler_respect_robots} setValue={setBoolean} />
        </section>

        <section className="settings-panel">
          <div className="settings-section-heading"><span className="settings-icon"><Icon name="activity" size={19} /></span><div><span className="eyebrow">Public channels</span><h2>Social collection</h2><p>Bound public video, post, comment, and transcript acquisition.</p></div></div>
          <ToggleControl label="Enable social collection" hint="Allow configured social connectors to run" field="enable_social_collection" checked={form.enable_social_collection} setValue={setBoolean} />
          <ToggleControl label="Collect YouTube transcripts" hint="Use available public transcripts as evidence" field="enable_youtube_transcripts" checked={form.enable_youtube_transcripts} setValue={setBoolean} />
          <div className="settings-control-grid">
            <NumberControl label="Items per run" hint="Maximum social items per connector" field="social_max_items_per_run" value={form.social_max_items_per_run} setValue={setNumber} min={1} max={50} />
            <NumberControl label="Comments per item" hint="Maximum public comments per item" field="social_max_comments_per_item" value={form.social_max_comments_per_item} setValue={setNumber} min={0} max={200} />
            <NumberControl label="Request delay" hint="Seconds between social requests" field="social_request_delay_seconds" value={form.social_request_delay_seconds} setValue={setNumber} min={0} max={10} step={0.01} />
            <NumberControl label="Run timeout" hint="Seconds before stopping a social run" field="social_run_timeout_seconds" value={form.social_run_timeout_seconds} setValue={setNumber} min={30} max={3600} />
            <NumberControl label="YouTube videos" hint="Videos examined per target" field="youtube_max_videos" value={form.youtube_max_videos} setValue={setNumber} min={1} max={50} />
            <NumberControl label="YouTube comments" hint="Comments examined per video" field="youtube_comments_per_video" value={form.youtube_comments_per_video} setValue={setNumber} min={0} max={200} />
            <NumberControl label="YouTube retention" hint="Days before refresh is due" field="social_youtube_retention_days" value={form.social_youtube_retention_days} setValue={setNumber} min={1} max={30} />
          </div>
        </section>

        <section className="settings-panel">
          <div className="settings-section-heading"><span className="settings-icon"><Icon name="briefcase" size={19} /></span><div><span className="eyebrow">External intelligence</span><h2>Jobs & developer activity</h2><p>Configure hiring research and GitHub acquisition limits.</p></div></div>
          <ToggleControl label="Enable external sources" hint="Use public sources beyond official websites" field="enable_external_sources" checked={form.enable_external_sources} setValue={setBoolean} />
          <ToggleControl label="Enable job collection" hint="Search configured public job sources" field="enable_job_scraper" checked={form.enable_job_scraper} setValue={setBoolean} />
          <ToggleControl label="LinkedIn job search (experimental)" hint="May be unavailable or blocked; use carefully" field="enable_linkedin_scraper" checked={form.enable_linkedin_scraper} setValue={setBoolean} warning />
          <div className="settings-control-grid">
            <label className="settings-control wide"><span>Job sources</span><input value={form.job_sources} onChange={(event) => setForm({ ...form, job_sources: event.target.value })} /><small>Comma-separated: indeed, google, linkedin, glassdoor, zip_recruiter</small></label>
            <label className="settings-control"><span>Search location</span><input value={form.job_search_location} onChange={(event) => setForm({ ...form, job_search_location: event.target.value })} /><small>Geographic focus for hiring research</small></label>
            <NumberControl label="Job results" hint="Maximum job records requested" field="job_results_wanted" value={form.job_results_wanted} setValue={setNumber} min={1} max={200} />
            <NumberControl label="Job age window" hint="Maximum posting age in hours" field="job_hours_old" value={form.job_hours_old} setValue={setNumber} min={1} max={8760} />
            <NumberControl label="GitHub repositories" hint="Maximum repositories per target" field="github_max_repositories" value={form.github_max_repositories} setValue={setNumber} min={1} max={100} />
            <NumberControl label="Releases per repository" hint="Release records retained per repository" field="github_releases_per_repository" value={form.github_releases_per_repository} setValue={setNumber} min={0} max={20} />
          </div>
        </section>

        <section className="settings-panel deep-settings-panel">
          <div className="settings-section-heading"><span className="settings-icon"><Icon name="shield" size={19} /></span><div><span className="eyebrow">Experimental · local only</span><h2>Deep Research Lab</h2><p>Run bounded, GET-only searches over publicly reachable Tor hidden services.</p></div></div>
          <div className="deep-research-policy-note"><Icon name="error" size={17} /><p><strong>Disabled by default.</strong> Scope does not authenticate, submit forms, download files, or crawl arbitrary targets. Confirm local law and research authorization before each run.</p></div>
          <ToggleControl label="Enable Deep Research Lab" hint="Expose the experimental Tor research workflow" field="enable_deep_research" checked={form.enable_deep_research} setValue={setBoolean} warning />
          <div className="settings-control-grid">
            <NumberControl label="Search result budget" hint="Maximum unique results discovered" field="deep_research_max_results" value={form.deep_research_max_results} setValue={setNumber} min={1} max={100} />
            <NumberControl label="Page collection budget" hint="Maximum result pages collected as evidence" field="deep_research_max_pages" value={form.deep_research_max_pages} setValue={setNumber} min={1} max={50} />
            <NumberControl label="Request delay" hint="Seconds between hidden-service requests" field="deep_research_request_delay_seconds" value={form.deep_research_request_delay_seconds} setValue={setNumber} min={0.25} max={15} step={0.25} />
            <NumberControl label="Run timeout" hint="Maximum run duration in seconds" field="deep_research_timeout_seconds" value={form.deep_research_timeout_seconds} setValue={setNumber} min={60} max={3600} />
          </div>
        </section>

        {error ? <div className="settings-feedback error"><Icon name="error" size={17} /><span>{error}</span></div> : null}
        {message ? <div className="settings-feedback success"><Icon name="check" size={17} /><span>{message}</span></div> : null}
        <div className="settings-sticky-actions"><span>Changes affect new collection runs.</span><div><button type="button" className="secondary-action" disabled={busy || source !== 'saved'} onClick={reset}>Restore defaults</button><button type="submit" className="primary-action" disabled={busy}>{busy ? 'Saving…' : 'Save collection settings'}</button></div></div>
      </form>
    </main>
  );
}
