'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  cancelInvestigation,
  createInvestigation,
  getInvestigation,
  getInvestigations,
  runInvestigation,
} from '@/lib/api';
import { Investigation } from '@/lib/types';

interface InvestigationWorkbenchProps {
  competitorId: number;
  dataVersion: number;
}

const STATUS_STYLES: Record<string, string> = {
  draft: 'border-slate-500/30 bg-slate-500/10 text-slate-300',
  queued: 'border-amber-400/30 bg-amber-400/10 text-amber-200',
  running: 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200',
  completed: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200',
  partial: 'border-orange-400/30 bg-orange-400/10 text-orange-200',
  failed: 'border-rose-400/30 bg-rose-400/10 text-rose-200',
  cancelled: 'border-slate-500/30 bg-slate-500/10 text-slate-300',
};

function statusBadge(status: string) {
  return `inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${
    STATUS_STYLES[status] ?? STATUS_STYLES.draft
  }`;
}

function readableDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : 'Not completed';
}

export function InvestigationWorkbench({
  competitorId,
  dataVersion,
}: InvestigationWorkbenchProps) {
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [selected, setSelected] = useState<Investigation | null>(null);
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [maxSteps, setMaxSteps] = useState(5);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    const rows = await getInvestigations(competitorId);
    setInvestigations(rows);
    return rows;
  }, [competitorId]);

  const loadDetail = useCallback(
    async (investigationId: number) => {
      const detail = await getInvestigation(competitorId, investigationId);
      setSelected(detail);
      setInvestigations((current) =>
        current.map((item) => (item.id === detail.id ? detail : item))
      );
      return detail;
    },
    [competitorId]
  );

  useEffect(() => {
    let cancelled = false;
    const fetchInitial = async () => {
      try {
        const rows = await getInvestigations(competitorId);
        if (cancelled) return;
        setInvestigations(rows);
        if (rows.length === 0) {
          setSelected(null);
          return;
        }
        const preferred = selected && rows.some((item) => item.id === selected.id)
          ? selected.id
          : rows[0].id;
        const detail = await getInvestigation(competitorId, preferred);
        if (!cancelled) setSelected(detail);
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : 'Failed to load investigations');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void fetchInitial();
    return () => {
      cancelled = true;
    };
    // selected is intentionally omitted so refreshing data does not loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [competitorId, dataVersion]);

  useEffect(() => {
    if (!selected || !['queued', 'running'].includes(selected.status)) return;
    const timer = setInterval(() => {
      loadDetail(selected.id)
        .then((detail) => {
          if (!['queued', 'running'].includes(detail.status)) {
            loadList().catch(() => undefined);
          }
        })
        .catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : 'Investigation polling failed');
        });
    }, 2500);
    return () => clearInterval(timer);
  }, [selected, loadDetail, loadList]);

  const handleCreate = async () => {
    if (question.trim().length < 8) return;
    setCreating(true);
    setError(null);
    try {
      const created = await createInvestigation(competitorId, {
        title: title.trim() || undefined,
        question: question.trim(),
        max_steps: maxSteps,
      });
      await runInvestigation(competitorId, created.id);
      const queued = await getInvestigation(competitorId, created.id);
      setSelected(queued);
      setInvestigations((current) => [
        queued,
        ...current.filter((item) => item.id !== queued.id),
      ]);
      setTitle('');
      setQuestion('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Failed to start investigation');
    } finally {
      setCreating(false);
    }
  };

  const handleRun = async () => {
    if (!selected) return;
    setActionPending(true);
    setError(null);
    try {
      await runInvestigation(competitorId, selected.id);
      await loadDetail(selected.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Failed to run investigation');
    } finally {
      setActionPending(false);
    }
  };

  const handleCancel = async () => {
    if (!selected) return;
    setActionPending(true);
    setError(null);
    try {
      await cancelInvestigation(competitorId, selected.id);
      await loadDetail(selected.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Failed to cancel investigation');
    } finally {
      setActionPending(false);
    }
  };

  const citationsByFinding = useMemo(() => {
    const grouped = new Map<number, NonNullable<Investigation['citations']>>();
    for (const citation of selected?.citations ?? []) {
      if (citation.finding_id === null) continue;
      const current = grouped.get(citation.finding_id) ?? [];
      current.push(citation);
      grouped.set(citation.finding_id, current);
    }
    return grouped;
  }, [selected]);

  const progress = selected?.max_steps
    ? Math.min((selected.completed_steps / selected.max_steps) * 100, 100)
    : 0;

  return (
    <div className="space-y-5">
      <section className="panel p-5">
        <div className="grid gap-5 xl:grid-cols-[1fr_1.7fr]">
          <div>
            <p className="eyebrow">RESEARCH AGENT</p>
            <h2 className="mt-2 text-xl font-semibold text-white">Launch an investigation</h2>
            <p className="mt-2 text-sm leading-6 text-[#8f96a8]">
              The agent plans research steps, searches stored evidence, validates citations,
              and reports unresolved intelligence gaps.
            </p>
          </div>
          <div className="grid gap-3">
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="field"
              placeholder="Optional investigation title"
              maxLength={500}
            />
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              className="field min-h-28 resize-y"
              placeholder="Example: What evidence indicates MosChip is expanding its industrial AI strategy, and which partners or products support that assessment?"
              maxLength={10000}
            />
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <label className="text-xs text-[#8f96a8]">
                Research steps: {maxSteps}
                <input
                  type="range"
                  min="2"
                  max="8"
                  value={maxSteps}
                  onChange={(event) => setMaxSteps(Number(event.target.value))}
                  className="mt-2 block w-52 accent-blue-400"
                />
              </label>
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating || question.trim().length < 8}
                className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating ? 'Starting research…' : 'Create & run investigation'}
              </button>
            </div>
          </div>
        </div>
      </section>

      {error && (
        <div className="rounded-lg border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[330px_minmax(0,1fr)]">
        <aside className="panel overflow-hidden">
          <div className="border-b border-[#262832] px-5 py-4">
            <p className="eyebrow">INVESTIGATION HISTORY</p>
          </div>
          <div className="max-h-[760px] divide-y divide-[#22242d] overflow-y-auto">
            {loading ? (
              <p className="p-5 text-sm text-[#7f8799]">Loading investigations…</p>
            ) : investigations.length === 0 ? (
              <p className="p-5 text-sm leading-6 text-[#7f8799]">
                No investigations yet. Ask a focused intelligence question above.
              </p>
            ) : (
              investigations.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => loadDetail(item.id).catch(() => undefined)}
                  className={`w-full px-5 py-4 text-left transition ${
                    selected?.id === item.id ? 'bg-blue-400/8' : 'hover:bg-white/[0.025]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="line-clamp-2 text-sm font-medium text-white">{item.title}</p>
                    <span className={statusBadge(item.status)}>{item.status}</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs leading-5 text-[#727a8d]">
                    {item.question}
                  </p>
                  <div className="mt-3 flex gap-3 font-mono text-[10px] text-[#5f687a]">
                    <span>{item.completed_steps}/{item.max_steps} steps</span>
                    <span>{item.evidence_count} citations</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </aside>

        <main className="panel min-h-[560px] p-5">
          {!selected ? (
            <div className="grid min-h-[480px] place-items-center text-center">
              <div>
                <div className="text-3xl text-blue-300">âŒ•</div>
                <p className="mt-3 text-sm text-[#7f8799]">
                  Select or create an investigation to inspect its research trail.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              <header>
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={statusBadge(selected.status)}>{selected.status}</span>
                      <span className="font-mono text-[10px] text-[#687185]">
                        {selected.model ?? 'shared model'}
                      </span>
                    </div>
                    <h2 className="mt-3 text-2xl font-semibold text-white">{selected.title}</h2>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-[#a3aabc]">
                      {selected.question}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {['queued', 'running'].includes(selected.status) ? (
                      <button
                        type="button"
                        onClick={handleCancel}
                        disabled={actionPending || Boolean(selected.cancel_requested_at)}
                        className="btn-secondary disabled:opacity-50"
                      >
                        {selected.cancel_requested_at ? 'Cancelling…' : 'Cancel'}
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={handleRun}
                        disabled={actionPending}
                        className="btn-secondary disabled:opacity-50"
                      >
                        {actionPending ? 'Queuing…' : 'Run again'}
                      </button>
                    )}
                  </div>
                </div>

                <div className="mt-5 h-1.5 overflow-hidden rounded-full bg-[#171921]">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
                  {[
                    ['Completed steps', `${selected.completed_steps}/${selected.max_steps}`],
                    ['Evidence', selected.evidence_count],
                    ['Source domains', selected.source_diversity],
                    ['Confidence', `${Math.round(selected.confidence * 100)}%`],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-lg border border-[#272934] bg-[#0a0b0f] p-3">
                      <div className="font-mono text-lg text-white">{value}</div>
                      <div className="mt-1 text-[10px] uppercase tracking-wide text-[#697185]">
                        {label}
                      </div>
                    </div>
                  ))}
                </div>
              </header>

              {selected.executive_summary && (
                <section className="rounded-xl border border-blue-400/20 bg-blue-400/[0.04] p-5">
                  <p className="eyebrow">EXECUTIVE ASSESSMENT</p>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-[#d4d8e2]">
                    {selected.executive_summary}
                  </p>
                </section>
              )}

              {selected.answer && (
                <section>
                  <p className="eyebrow">INTELLIGENCE BRIEF</p>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-[#b7bdca]">
                    {selected.answer}
                  </p>
                </section>
              )}

              {(selected.steps?.length ?? 0) > 0 && (
                <section>
                  <p className="eyebrow">RESEARCH TRAIL</p>
                  <div className="mt-3 space-y-3">
                    {selected.steps?.map((step) => (
                      <article key={step.id} className="rounded-lg border border-[#272934] bg-[#0a0b0f] p-4">
                        <div className="flex items-start gap-3">
                          <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-blue-400/10 font-mono text-xs text-blue-300">
                            {step.step_index}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <h3 className="text-sm font-medium text-white">{step.question}</h3>
                              <span className={statusBadge(step.status)}>{step.status}</span>
                            </div>
                            {step.rationale && (
                              <p className="mt-1 text-xs leading-5 text-[#6f778a]">{step.rationale}</p>
                            )}
                            {step.answer && (
                              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-[#aeb5c4]">
                                {step.answer}
                              </p>
                            )}
                            <div className="mt-3 flex flex-wrap gap-3 font-mono text-[10px] text-[#626b7e]">
                              <span>{step.evidence_count} evidence chunks</span>
                              <span>{step.source_diversity} source domains</span>
                              <span>{step.search_query}</span>
                            </div>
                            {step.error && <p className="mt-2 text-xs text-rose-300">{step.error}</p>}
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              {(selected.findings?.length ?? 0) > 0 && (
                <section>
                  <p className="eyebrow">ATOMIC FINDINGS</p>
                  <div className="mt-3 grid gap-3 lg:grid-cols-2">
                    {selected.findings?.map((finding) => (
                      <article key={finding.id} className="rounded-lg border border-[#272934] bg-[#0a0b0f] p-4">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-cyan-300">
                            {finding.finding_type}
                          </span>
                          <span className="font-mono text-xs text-[#8992a5]">
                            {Math.round(finding.confidence * 100)}%
                          </span>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-[#c7ccd7]">{finding.statement}</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(citationsByFinding.get(finding.id) ?? []).map((citation, index) => (
                            <a
                              key={citation.id}
                              href={citation.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded-full border border-[#30333e] px-2.5 py-1 text-[10px] text-[#949daf] hover:border-blue-400/40 hover:text-blue-200"
                              title={citation.excerpt ?? citation.title ?? citation.source_url}
                            >
                              Source {index + 1} · {citation.source_type.replaceAll('_', ' ')}
                            </a>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              {selected.gaps.length > 0 && (
                <section className="rounded-xl border border-amber-400/20 bg-amber-400/[0.035] p-5">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-200">
                    Intelligence gaps
                  </p>
                  <ul className="mt-3 space-y-2">
                    {selected.gaps.map((gap, index) => (
                      <li key={`${gap}-${index}`} className="flex gap-2 text-sm leading-6 text-[#c6bfae]">
                        <span className="text-amber-300" aria-hidden="true">•</span>
                        <span>{gap}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {selected.error && (
                <div className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-4 text-sm text-rose-200">
                  {selected.error}
                </div>
              )}

              <footer className="border-t border-[#242630] pt-4 font-mono text-[10px] text-[#5f687a]">
                Started {readableDate(selected.started_at)} · completed {readableDate(selected.completed_at)}
              </footer>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
