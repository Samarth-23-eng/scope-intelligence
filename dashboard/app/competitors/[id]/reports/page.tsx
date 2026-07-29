'use client';

import { useCallback, useEffect, useState } from 'react';
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
} from '@/components/company/PagePrimitives';
import { generateReport, listReports, sendReport } from '@/lib/api';

interface ReportInfo {
  filename: string;
  competitor_id: number;
  size: number;
  created_at: string;
}

function sizeLabel(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ReportsPage() {
  const { competitorId, competitor, dataVersion } = useCompanyWorkspace();
  const [reports, setReports] = useState<ReportInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReports(await listReports(competitorId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Generated reports are unavailable.');
    } finally {
      setLoading(false);
    }
  }, [competitorId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, dataVersion]);

  const generate = async () => {
    setGenerating(true);
    setError(null);
    setNotice(null);
    try {
      const blob = await generateReport(competitorId);
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.download = `${(competitor?.name || 'company').replaceAll(' ', '_')}_intelligence_report.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
      setNotice('A fresh intelligence report was generated and downloaded.');
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Report generation failed.');
    } finally {
      setGenerating(false);
    }
  };

  const send = async () => {
    setSending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await sendReport(competitorId);
      setNotice(`Latest report sent successfully. ${result.alerts_triggered} alert${result.alerts_triggered === 1 ? '' : 's'} included.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Report delivery failed.');
    } finally {
      setSending(false);
    }
  };

  const latest = reports[0] ?? null;
  const totalSize = reports.reduce((sum, report) => sum + report.size, 0);

  return (
    <main className="company-page">
      <PageHeading
        eyebrow="REPORTING"
        title="Intelligence briefings"
        description="Generate a decision-ready PDF from the current evidence, preserve report history, and deliver the latest briefing through the configured channel."
        actions={
          <>
            <button type="button" className="secondary-button" onClick={() => void send()} disabled={sending || !reports.length}>
              <Icon name="arrow" size={15} />
              {sending ? 'Sending report' : 'Send latest'}
            </button>
            <button type="button" className="primary-button" onClick={() => void generate()} disabled={generating}>
              <Icon name="download" size={15} />
              {generating ? 'Generating report' : 'Generate PDF'}
            </button>
          </>
        }
      />

      <section className="workspace-metric-grid">
        <MetricTile label="Generated reports" value={reports.length} note="Preserved briefing history" icon="document" />
        <MetricTile label="Latest report" value={latest ? formatDate(latest.created_at) : 'None'} note={latest?.filename || 'Generate the first briefing'} icon="archive" />
        <MetricTile label="Stored output" value={sizeLabel(totalSize)} note="Local report storage" icon="database" />
        <MetricTile label="Delivery" value={reports.length ? 'Ready' : 'Waiting'} note={reports.length ? 'Latest report can be sent' : 'A report is required first'} icon="arrow" tone={reports.length ? 'good' : 'warning'} />
      </section>

      {notice ? <div className="feedback-banner success"><Icon name="check" size={16} /><div><strong>Report operation complete</strong><span>{notice}</span></div></div> : null}
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingState label="Loading report history" /> : null}

      {!loading ? (
        <div className="reports-layout">
          <Panel eyebrow="REPORT HISTORY" title="Generated briefings">
            {reports.length ? (
              <div className="report-list">
                {reports.map((report, index) => (
                  <article key={`${report.filename}-${report.created_at}`}>
                    <span><Icon name="document" size={18} /></span>
                    <div><strong>{report.filename}</strong><p>Stored in the protected report workspace</p></div>
                    {index === 0 ? <em>Latest</em> : <span />}
                    <div><strong>{sizeLabel(report.size)}</strong><time>{formatDate(report.created_at, true)}</time></div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                icon="document"
                title="No reports generated"
                description="Create the first PDF briefing from the latest evidence, claims, signals, relationships, and forecasts."
                action={<button type="button" className="primary-button" onClick={() => void generate()} disabled={generating}><Icon name="download" size={15} />Generate first report</button>}
              />
            )}
          </Panel>

          <Panel eyebrow="BRIEFING STANDARD" title="What the report includes">
            <div className="report-inclusions">
              {[
                ['Executive assessment', 'A concise decision brief based on the latest grounded analysis.'],
                ['Signals and forecasts', 'Priority developments and confidence-scored forward assessments.'],
                ['Evidence and claims', 'Auditable claims linked to their collected sources.'],
                ['Relationship intelligence', 'Strategic people, companies, products, and influence paths.'],
              ].map(([title, description], index) => (
                <article key={title}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{title}</strong><p>{description}</p></div></article>
              ))}
            </div>
          </Panel>
        </div>
      ) : null}
    </main>
  );
}
