'use client';

import { type FormEvent, useCallback, useEffect, useState } from 'react';
import { Icon } from '@/components/Icon';
import { useCompanyWorkspace } from '@/components/company/CompanyWorkspace';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricTile,
  PageHeading,
  Panel,
  formatDate,
  hostname,
  percent,
} from '@/components/company/PagePrimitives';
import {
  getEvidenceDocuments,
  getEvidenceOverview,
  getIntelligenceClaims,
  getSourceHealth,
  searchEvidence,
} from '@/lib/api';
import type {
  EvidenceDocument,
  EvidenceOverview,
  EvidenceSearchHit,
  IntelligenceClaim,
  SourceHealth,
} from '@/lib/types';

type View = 'search' | 'documents' | 'claims' | 'sources';

export default function EvidencePage() {
  const { competitorId, dataVersion } = useCompanyWorkspace();
  const [overview, setOverview] = useState<EvidenceOverview | null>(null);
  const [documents, setDocuments] = useState<EvidenceDocument[]>([]);
  const [claims, setClaims] = useState<IntelligenceClaim[]>([]);
  const [sources, setSources] = useState<SourceHealth[]>([]);
  const [hits, setHits] = useState<EvidenceSearchHit[]>([]);
  const [query, setQuery] = useState('');
  const [view, setView] = useState<View>('search');
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [overviewData, documentRows, claimRows, sourceRows] = await Promise.all([
        getEvidenceOverview(competitorId),
        getEvidenceDocuments(competitorId),
        getIntelligenceClaims(competitorId),
        getSourceHealth(competitorId),
      ]);
      setOverview(overviewData);
      setDocuments(documentRows);
      setClaims(claimRows);
      setSources(sourceRows);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Evidence library is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [competitorId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, dataVersion]);

  const handleSearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = query.trim();
    if (!normalized) return;
    setSearching(true);
    setError(null);
    try {
      setHits(await searchEvidence(competitorId, normalized, 30));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Evidence search failed.');
    } finally {
      setSearching(false);
    }
  };

  const healthySources = sources.filter((source) => source.status === 'healthy').length;
  const confirmedClaims = claims.filter((claim) => claim.status === 'confirmed').length;

  return (
    <main className="company-page">
      <PageHeading
        eyebrow="EVIDENCE LIBRARY"
        title="Sources and claims"
        description="Search the collected corpus, trace claims to original sources, and audit the health of every collection adapter."
        actions={
          <button type="button" className="secondary-button" onClick={() => void load()} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh library
          </button>
        }
      />

      <section className="workspace-metric-grid">
        <MetricTile label="Documents" value={overview?.documents ?? 0} note={`${overview?.document_versions ?? 0} preserved versions`} icon="document" />
        <MetricTile label="Searchable passages" value={overview?.indexed_chunks ?? 0} note={`${overview?.chunks ?? 0} total passages`} icon="search" tone={(overview?.indexed_chunks ?? 0) ? 'good' : 'warning'} />
        <MetricTile label="Citation coverage" value={percent(overview?.citation_coverage)} note={`${confirmedClaims} confirmed claims`} icon="link" tone={(overview?.citation_coverage ?? 0) >= 0.7 ? 'good' : 'warning'} />
        <MetricTile label="Healthy adapters" value={`${healthySources}/${sources.length}`} note="Collection source status" icon="shield" tone={sources.length && healthySources === sources.length ? 'good' : 'warning'} />
      </section>

      <div className="view-switcher" role="tablist" aria-label="Evidence library views">
        {([
          ['search', 'Search corpus', null],
          ['documents', 'Documents', documents.length],
          ['claims', 'Claims', claims.length],
          ['sources', 'Source health', sources.length],
        ] as const).map(([id, label, count]) => (
          <button key={id} type="button" role="tab" aria-selected={view === id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>
            {label}{count !== null ? <span>{count}</span> : null}
          </button>
        ))}
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingState label="Indexing evidence library" /> : null}

      {!loading && view === 'search' ? (
        <Panel className="evidence-search-panel">
          <div className="evidence-search-hero">
            <span><Icon name="search" size={23} /></span>
            <div>
              <h3>Search across every collected source</h3>
              <p>Use names, products, events, technologies, or full research questions. Results remain tied to their original URL and collection record.</p>
            </div>
          </div>
          <form onSubmit={handleSearch} className="evidence-search-form">
            <label>
              <Icon name="search" size={18} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. recent hiring expansion in India" />
            </label>
            <button type="submit" className="primary-button" disabled={searching || !query.trim()}>
              {searching ? 'Searching corpus' : 'Search evidence'}
            </button>
          </form>

          {hits.length ? (
            <div className="evidence-results">
              <div className="results-heading"><strong>{hits.length} relevant passages</strong><span>Ranked by hybrid retrieval</span></div>
              {hits.map((hit) => (
                <article key={hit.chunk_id}>
                  <div className="evidence-result-top">
                    <div>
                      <span className="type-label">{hit.source_type.replaceAll('_', ' ')}</span>
                      <strong>{hit.title || hostname(hit.source_url)}</strong>
                    </div>
                    <span className="confidence-pill">{Math.round(hit.score * 100)} relevance</span>
                  </div>
                  <p>{hit.content}</p>
                  <footer>
                    <a href={hit.source_url} target="_blank" rel="noreferrer">Open original source <Icon name="arrow" size={13} /></a>
                    <span>{hit.retrieval_methods.join(' + ')}</span>
                    <time>{formatDate(hit.published_at || hit.collected_at)}</time>
                  </footer>
                </article>
              ))}
            </div>
          ) : query && !searching ? (
            <EmptyState icon="search" title="No search results yet" description="Submit the query to search the indexed evidence corpus." />
          ) : (
            <div className="search-suggestions">
              <span>Suggested searches</span>
              {['Leadership changes', 'New product launches', 'Strategic partnerships', 'Hiring expansion'].map((item) => (
                <button key={item} type="button" onClick={() => setQuery(item)}>{item}</button>
              ))}
            </div>
          )}
        </Panel>
      ) : null}

      {!loading && view === 'documents' ? (
        <Panel>
          {documents.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>Document</th><th>Source</th><th>Coverage</th><th>Last seen</th><th /></tr></thead>
                <tbody>
                  {documents.map((document) => (
                    <tr key={document.id}>
                      <td><strong>{document.title || 'Untitled source'}</strong><small>{hostname(document.canonical_url)}</small></td>
                      <td><span className="type-label">{document.source_type.replaceAll('_', ' ')}</span></td>
                      <td><strong>{document.chunk_count}</strong><small>{document.indexed_chunk_count} indexed · v{document.version_count}</small></td>
                      <td>{formatDate(document.last_seen_at)}</td>
                      <td><a href={document.canonical_url} target="_blank" rel="noreferrer" aria-label={`Open ${document.title || 'source'}`}><Icon name="arrow" size={16} /></a></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState title="No documents collected" description="Run collection to populate the evidence library with source documents." />}
        </Panel>
      ) : null}

      {!loading && view === 'claims' ? (
        <Panel>
          {claims.length ? (
            <div className="claim-list">
              {claims.map((claim) => (
                <article key={claim.id}>
                  <div className="claim-list-top">
                    <div><span className={`claim-status ${claim.status}`}>{claim.status}</span><span className="type-label">{claim.claim_type.replaceAll('_', ' ')}</span></div>
                    <strong>{percent(claim.confidence)}</strong>
                  </div>
                  <p>{claim.statement}</p>
                  <footer><span>{claim.evidence.length} citations</span><time>{formatDate(claim.occurred_at || claim.created_at)}</time></footer>
                </article>
              ))}
            </div>
          ) : <EmptyState title="No intelligence claims" description="Claims are created during analysis and remain linked to their supporting evidence." />}
        </Panel>
      ) : null}

      {!loading && view === 'sources' ? (
        <Panel>
          {sources.length ? (
            <div className="source-health-list">
              {sources.map((source) => (
                <article key={source.id}>
                  <span className={`source-status-dot ${source.status}`} />
                  <div><strong>{source.source_key}</strong><p>{source.adapter_name.replaceAll('_', ' ')}</p></div>
                  <div><strong>{source.total_items}</strong><span>items</span></div>
                  <div><strong>{source.total_attempts}</strong><span>attempts</span></div>
                  <div><span className={`source-status ${source.status}`}>{source.status}</span><small>{source.last_error || formatDate(source.last_success_at, true)}</small></div>
                </article>
              ))}
            </div>
          ) : <EmptyState title="No source activity" description="Source adapter health will appear after a collection campaign begins." />}
        </Panel>
      ) : null}
    </main>
  );
}
