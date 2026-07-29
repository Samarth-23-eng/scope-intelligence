import Link from 'next/link';
import { Icon } from '@/components/Icon';
import type { DashboardCompetitor } from '@/lib/types';

export function CompetitorCard({ competitor }: { competitor: DashboardCompetitor }) {
  const cleanSummary = competitor.latest_summary
    ?.replace(/[#*_`>-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const summary = cleanSummary
    ? cleanSummary.length > 150
      ? `${cleanSummary.slice(0, 150)}…`
      : cleanSummary
    : 'No assessment has been generated. Run collection to build the first decision brief.';
  const updated = competitor.last_updated
    ? new Date(competitor.last_updated).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : 'Not analyzed';

  return (
    <Link href={`/competitors/${competitor.id}`} className="company-card">
      <article>
        <header>
          <span className="company-card-monogram">{competitor.name.slice(0, 1).toUpperCase()}</span>
          <div><h3>{competitor.name}</h3><p>{competitor.domain || 'Name-first identity'}</p></div>
          <span className={competitor.latest_summary ? 'dossier-state analyzed' : 'dossier-state'}>
            {competitor.latest_summary ? 'Analyzed' : 'Pending'}
          </span>
          <Icon name="arrow" size={17} />
        </header>
        <p className="company-card-summary">{summary}</p>
        <footer>
          <div><strong>{competitor.signal_count}</strong><span>Signals</span></div>
          <div><strong>{competitor.prediction_count}</strong><span>Forecasts</span></div>
          <time>{updated}</time>
        </footer>
      </article>
    </Link>
  );
}
