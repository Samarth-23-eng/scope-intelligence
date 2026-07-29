'use client';

import type { FormEvent } from 'react';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { CompetitorCard } from '@/components/CompetitorCard';
import { Icon } from '@/components/Icon';
import { createCompetitor, discoverCompany, getDashboard } from '@/lib/api';
import type { DashboardResponse } from '@/lib/types';

export default function HomePage() {
  const router = useRouter();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [domain, setDomain] = useState('');
  const [industry, setIndustry] = useState('');
  const [rssFeeds, setRssFeeds] = useState('');
  const [discoveryName, setDiscoveryName] = useState('');
  const [discovering, setDiscovering] = useState(false);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getDashboard());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Portfolio data is unavailable.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    getDashboard()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Portfolio data is unavailable.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleDiscover = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setDiscovering(true);
    setDiscoveryError(null);
    try {
      const result = await discoverCompany(discoveryName.trim());
      router.push(`/competitors/${result.competitor.id}`);
    } catch (reason) {
      setDiscoveryError(reason instanceof Error ? reason.message : 'Company discovery failed.');
    } finally {
      setDiscovering(false);
    }
  };

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      const competitor = await createCompetitor({
        name: name.trim(),
        domain: domain.trim(),
        industry: industry.trim() || undefined,
        rss_feeds: rssFeeds.split(/[\n,]/).map((feed) => feed.trim()).filter(Boolean),
      });
      router.push(`/competitors/${competitor.id}`);
    } catch (reason) {
      setCreateError(reason instanceof Error ? reason.message : 'Company profile could not be created.');
    } finally {
      setCreating(false);
    }
  };

  const competitors = data?.competitors ?? [];
  const totalSignals = competitors.reduce((total, item) => total + item.signal_count, 0);
  const totalPredictions = competitors.reduce((total, item) => total + item.prediction_count, 0);
  const analyzed = competitors.filter((item) => item.latest_summary).length;
  const signalLeaders = [...competitors]
    .sort((left, right) => right.signal_count - left.signal_count)
    .slice(0, 4);
  const maxSignals = Math.max(...signalLeaders.map((item) => item.signal_count), 1);

  return (
    <main id="main-content" className="portfolio-page">
      <header className="portfolio-heading">
        <div>
          <p className="page-kicker">Workspace overview</p>
          <h1>Intelligence portfolio</h1>
          <p>Monitor companies, launch focused research, and inspect the evidence behind every conclusion.</p>
        </div>
        <div>
          <button type="button" className="secondary-button" onClick={() => void fetchData()} disabled={loading}>
            <Icon name="refresh" size={15} /> Refresh
          </button>
          <button type="button" className="secondary-button" onClick={() => setShowManual((value) => !value)}>
            <Icon name={showManual ? 'close' : 'building'} size={15} />
            {showManual ? 'Close form' : 'Add manually'}
          </button>
        </div>
      </header>

      <section className="portfolio-stat-strip" aria-label="Portfolio summary">
        <div><span>Tracked companies</span><strong>{data?.total_count ?? '—'}</strong><small>Active dossiers</small></div>
        <div><span>Analyzed</span><strong>{analyzed}</strong><small>With current briefs</small></div>
        <div><span>Signals</span><strong>{totalSignals}</strong><small>Observed developments</small></div>
        <div><span>Forecasts</span><strong>{totalPredictions}</strong><small>Evidence-backed outlooks</small></div>
      </section>

      <section id="discovery" className="portfolio-command-grid">
        <div className="investigation-launcher">
          <div className="launcher-copy">
            <span className="launcher-icon"><Icon name="search" size={22} /></span>
            <div>
              <p className="page-kicker">New investigation</p>
              <h2>What company should we investigate?</h2>
              <p>
                Start with any company, subsidiary, regional office, brand, or business unit.
                A verified website is useful but not required.
              </p>
            </div>
          </div>
          <form onSubmit={handleDiscover} className="launcher-form">
            <label htmlFor="company-discovery">Company or organization name</label>
            <div>
              <input
                id="company-discovery"
                name="company"
                autoComplete="off"
                required
                minLength={2}
                value={discoveryName}
                onChange={(event) => setDiscoveryName(event.target.value)}
                placeholder="e.g. Nestlé IT Hub India"
              />
              <button type="submit" className="primary-button" disabled={discovering}>
                {discovering ? <Icon name="refresh" size={15} /> : <Icon name="arrow" size={15} />}
                {discovering ? 'Resolving identity' : 'Start investigation'}
              </button>
            </div>
          </form>
          <div aria-live="polite">
            {discoveryError ? <div className="inline-form-error"><Icon name="error" size={15} /><span>{discoveryError}</span></div> : null}
            {discovering ? <p className="launcher-progress">Searching organization identities, websites, public profiles, news, and source feeds…</p> : null}
          </div>
        </div>

        <aside className="collection-readiness">
          <div className="collection-readiness-header">
            <div><span className="status-pulse" /><strong>Collection ready</strong></div>
            <small>Private environment</small>
          </div>
          <div className="readiness-list">
            {[
              ['Web collection', 'Static and rendered pages', 'ready'],
              ['Evidence index', 'Hybrid retrieval and citations', 'ready'],
              ['Research agents', 'Structured multi-step analysis', 'ready'],
              ['Hard search', 'Optional access recovery', 'experimental'],
            ].map(([label, description, state]) => (
              <div key={label}>
                <span className={state === 'ready' ? 'readiness-state ready' : 'readiness-state'} />
                <div><strong>{label}</strong><p>{description}</p></div>
                <small>{state}</small>
              </div>
            ))}
          </div>
        </aside>
      </section>

      {showManual ? (
        <section className="manual-entry-panel">
          <header><div><p className="page-kicker">Manual profile</p><h2>Add a known company</h2></div><p>Use this when you already know the official domain and want to skip identity discovery.</p></header>
          <form onSubmit={handleCreate}>
            <label>Company Name<input name="manual-company-name" autoComplete="organization" required value={name} onChange={(event) => setName(event.target.value)} placeholder="Company name…" /></label>
            <label>Official Domain<input name="manual-company-domain" autoComplete="url" inputMode="url" required value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="company.com…" /></label>
            <label>Industry<input name="manual-company-industry" autoComplete="off" value={industry} onChange={(event) => setIndustry(event.target.value)} placeholder="Industry or market…" /></label>
            <label>RSS Feeds<textarea name="manual-company-feeds" autoComplete="off" value={rssFeeds} onChange={(event) => setRssFeeds(event.target.value)} placeholder="One feed URL per line…" rows={2} /></label>
            <div aria-live="polite">{createError ? <div className="inline-form-error"><Icon name="error" size={15} /><span>{createError}</span></div> : null}</div>
            <div className="manual-entry-actions"><button type="submit" className="primary-button" disabled={creating}>{creating ? 'Creating profile' : 'Create profile'}</button></div>
          </form>
        </section>
      ) : null}

      <section id="watchlist" className="watchlist-layout">
        <div className="watchlist-section">
          <header>
            <div><p className="page-kicker">Company dossiers</p><h2>Monitored Companies</h2></div>
            <span>{competitors.length} {competitors.length === 1 ? 'company' : 'companies'}</span>
          </header>

          {loading ? <div className="watchlist-loading"><span /><span /><span /></div> : null}
          {error ? <div className="portfolio-error"><Icon name="error" size={18} /><div><strong>Portfolio Data Is Unavailable</strong><p>{error}</p></div><button type="button" onClick={() => void fetchData()}>Retry</button></div> : null}
          {!loading && !error && !competitors.length ? <div className="watchlist-empty"><Icon name="building" size={22} /><strong>No Company Dossiers</strong><p>Start an investigation above to create the first monitored company.</p></div> : null}
          {!loading && !error && competitors.length ? <div className="company-grid">{competitors.map((competitor) => <CompetitorCard key={competitor.id} competitor={competitor} />)}</div> : null}
        </div>

        <aside className="portfolio-signal-map" aria-label="Signal distribution">
          <header>
            <div><p className="page-kicker">Portfolio Pulse</p><h2>Signal Distribution</h2></div>
            <Icon name="activity" size={18} />
          </header>
          <p className="signal-map-intro">Relative signal volume across the most active monitored organizations.</p>
          <div className="signal-map-list">
            {signalLeaders.map((competitor) => (
              <Link key={competitor.id} href={`/competitors/${competitor.id}/intelligence`}>
                <div><strong>{competitor.name}</strong><span>{competitor.signal_count} signals</span></div>
                <span className="signal-track" aria-hidden="true">
                  <i style={{ width: `${Math.max(4, (competitor.signal_count / maxSignals) * 100)}%` }} />
                </span>
              </Link>
            ))}
          </div>
          <footer>
            <span><i className="status-pulse" /> Live portfolio index</span>
            <strong>{totalSignals} observations</strong>
          </footer>
        </aside>
      </section>
    </main>
  );
}
