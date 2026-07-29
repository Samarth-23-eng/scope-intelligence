'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  getVerificationOverview,
  reviewClaim,
  runClaimVerification,
  updateSourceReliability,
} from '@/lib/api';
import type {
  ClaimVerification,
  SourceReliabilityProfile,
  VerificationOverview,
} from '@/lib/types';

type View = 'queue' | 'claims' | 'sources' | 'reviews';
type Decision = 'supported' | 'confirmed' | 'disputed' | 'stale';

function percentage(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatDate(value: string | null) {
  if (!value) return 'Never';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function flagLabel(value: string) {
  return value.replaceAll('_', ' ');
}

function VerificationCard({
  claim,
  reviewing,
  reviewNote,
  pending,
  onBeginReview,
  onNoteChange,
  onReview,
  onCancel,
}: {
  claim: ClaimVerification;
  reviewing: boolean;
  reviewNote: string;
  pending: boolean;
  onBeginReview: () => void;
  onNoteChange: (value: string) => void;
  onReview: (decision: Decision) => void;
  onCancel: () => void;
}) {
  return (
    <article className={`verification-card status-${claim.status}`}>
      <div className="verification-card-top">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`verification-status ${claim.status}`}>{claim.status}</span>
          <span className="claim-type">{flagLabel(claim.claim_type)}</span>
          {claim.claim_metadata.human_review_locked ? (
            <span className="human-reviewed">Operator reviewed</span>
          ) : null}
        </div>
        <strong className="verification-score">{percentage(claim.final_confidence)}</strong>
      </div>

      <h3>{claim.statement}</h3>
      <p className="verification-rationale">{claim.rationale}</p>

      <div className="verification-bars">
        {[
          ['Corroboration', claim.corroboration_score],
          ['Source quality', claim.source_quality],
          ['Freshness', claim.freshness_score],
          ['Contradiction', claim.contradiction_score],
        ].map(([label, value]) => (
          <div key={label as string}>
            <span><b>{label}</b><em>{percentage(value as number)}</em></span>
            <div><i style={{ width: percentage(value as number) }} /></div>
          </div>
        ))}
      </div>

      <div className="verification-facts">
        <span><b>{claim.support_count}</b> supporting citations</span>
        <span><b>{claim.independent_sources}</b> independent domains</span>
        <span><b>{claim.contradiction_count}</b> contradictions</span>
      </div>

      {claim.risk_flags.length > 0 && (
        <div className="risk-flags">
          {claim.risk_flags.map((flag) => (
            <span key={flag}>{flagLabel(flag)}</span>
          ))}
        </div>
      )}

      {reviewing ? (
        <div className="claim-review-panel">
          <label>
            Operator note
            <textarea
              value={reviewNote}
              onChange={(event) => onNoteChange(event.target.value)}
              rows={2}
              maxLength={5000}
              placeholder="Explain what you verified or why the claim should be disputed."
            />
          </label>
          <div>
            <button disabled={pending} onClick={() => onReview('confirmed')} className="review-confirm">Confirm</button>
            <button disabled={pending} onClick={() => onReview('supported')}>Support</button>
            <button disabled={pending} onClick={() => onReview('disputed')} className="review-dispute">Dispute</button>
            <button disabled={pending} onClick={() => onReview('stale')}>Mark stale</button>
            <button disabled={pending} onClick={onCancel} className="review-cancel">Cancel</button>
          </div>
        </div>
      ) : (
        <div className="verification-card-footer">
          <span>Assessed {formatDate(claim.assessed_at)}</span>
          <button onClick={onBeginReview}>Review claim</button>
        </div>
      )}
    </article>
  );
}

export function VerificationCenter({ competitorId }: { competitorId: number }) {
  const [overview, setOverview] = useState<VerificationOverview | null>(null);
  const [view, setView] = useState<View>('queue');
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [reviewPending, setReviewPending] = useState(false);
  const [editingSource, setEditingSource] = useState<number | null>(null);
  const [sourceScore, setSourceScore] = useState(0.7);
  const [sourceBasis, setSourceBasis] = useState('');
  const [sourcePending, setSourcePending] = useState(false);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setOverview(await getVerificationOverview(competitorId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification data is unavailable');
    } finally {
      setLoading(false);
    }
  }, [competitorId]);

  useEffect(() => {
    let cancelled = false;
    getVerificationOverview(competitorId)
      .then((result) => {
        if (!cancelled) setOverview(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Verification data is unavailable');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [competitorId]);

  const runVerification = async () => {
    setRunning(true);
    setError(null);
    setMessage(null);
    try {
      const result = await runClaimVerification(competitorId);
      setOverview(result.overview);
      setMessage(
        `Assessed ${result.result.claims_assessed} claims across ${result.result.sources_assessed} sources.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification could not be completed');
    } finally {
      setRunning(false);
    }
  };

  const submitReview = async (claimId: number, decision: Decision) => {
    setReviewPending(true);
    setError(null);
    try {
      await reviewClaim(competitorId, claimId, decision, reviewNote);
      await refresh();
      setReviewingId(null);
      setReviewNote('');
      setMessage(`Claim marked ${decision}. This operator decision is now protected.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Claim review failed');
    } finally {
      setReviewPending(false);
    }
  };

  const beginSourceEdit = (source: SourceReliabilityProfile) => {
    setEditingSource(source.id);
    setSourceScore(source.reliability);
    setSourceBasis(source.basis);
  };

  const saveSource = async (sourceId: number) => {
    setSourcePending(true);
    setError(null);
    try {
      const result = await updateSourceReliability(
        competitorId,
        sourceId,
        sourceScore,
        sourceBasis,
      );
      setOverview(result.overview);
      setEditingSource(null);
      setMessage('Source reliability updated and every affected claim was rescored.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Source update failed');
    } finally {
      setSourcePending(false);
    }
  };

  if (loading) {
    return <div className="panel h-72 animate-pulse bg-[#11141e]" />;
  }

  if (!overview) {
    return (
      <div className="panel p-10 text-center">
        <strong className="text-rose-300">Verification Center unavailable</strong>
        <p className="mt-2 text-sm text-rose-400">{error}</p>
        <button onClick={() => void refresh()} className="secondary-button mt-5">Try again</button>
      </div>
    );
  }

  const claims = view === 'queue' ? overview.queue : overview.verifications;

  return (
    <div className="verification-shell">
      <section className="verification-hero">
        <div>
          <p className="eyebrow">CLAIM VERIFICATION</p>
          <h2>Verification Center</h2>
          <p>
            Separate repeated reporting from independent corroboration. Every claim is
            rescored against source reliability, evidence freshness, and contradictions,
            with uncertain findings routed to human review.
          </p>
        </div>
        <button onClick={() => void runVerification()} disabled={running} className="primary-button">
          {running ? 'Verifying claims…' : 'Run verification'}
        </button>
      </section>

      {(error || message) && (
        <div className={error ? 'feedback-banner error' : 'feedback-banner success'}>
          <strong>{error ? 'Verification issue' : 'Complete'}</strong>
          <span>{error || message}</span>
        </div>
      )}

      <section className="verification-metrics">
        {[
          ['Claims assessed', overview.summary.total_claims, `${overview.summary.source_count} source profiles`],
          ['Confirmed', overview.summary.confirmed, `${overview.summary.supported} supported`],
          ['Needs review', overview.summary.needs_review, 'Single-source, stale, or weak'],
          ['Disputed', overview.summary.disputed, `${percentage(overview.summary.average_confidence)} average confidence`],
        ].map(([label, value, note]) => (
          <article key={label}>
            <p>{label}</p>
            <strong>{value}</strong>
            <span>{note}</span>
          </article>
        ))}
      </section>

      <div className="verification-view-tabs" role="tablist" aria-label="Verification views">
        {[
          ['queue', 'Review queue', overview.queue.length],
          ['claims', 'All claims', overview.verifications.length],
          ['sources', 'Source reliability', overview.sources.length],
          ['reviews', 'Operator reviews', overview.reviews.length],
        ].map(([id, label, count]) => (
          <button
            key={id}
            role="tab"
            aria-selected={view === id}
            onClick={() => setView(id as View)}
            className={view === id ? 'active' : ''}
          >
            {label}<span>{count}</span>
          </button>
        ))}
      </div>

      {(view === 'queue' || view === 'claims') && (
        claims.length ? (
          <section className="verification-list">
            {claims.map((claim) => (
              <VerificationCard
                key={claim.id}
                claim={claim}
                reviewing={reviewingId === claim.claim_id}
                reviewNote={reviewingId === claim.claim_id ? reviewNote : ''}
                pending={reviewPending}
                onBeginReview={() => {
                  setReviewingId(claim.claim_id);
                  setReviewNote('');
                }}
                onNoteChange={setReviewNote}
                onReview={(decision) => void submitReview(claim.claim_id, decision)}
                onCancel={() => {
                  setReviewingId(null);
                  setReviewNote('');
                }}
              />
            ))}
          </section>
        ) : (
          <section className="verification-empty panel">
            <span>V</span>
            <h3>{overview.verifications.length ? 'Review queue is clear' : 'No verified claims yet'}</h3>
            <p>
              {overview.verifications.length
                ? 'Every assessed claim currently meets its evidence requirements.'
                : 'Run the pipeline to create evidence-bound claims, then verify them here.'}
            </p>
            {!overview.verifications.length && (
              <button onClick={() => void runVerification()} disabled={running} className="secondary-button">
                Check for claims
              </button>
            )}
          </section>
        )
      )}

      {view === 'sources' && (
        overview.sources.length ? (
          <section className="source-reliability-grid">
            {overview.sources.map((source) => (
              <article key={source.id} className="source-reliability-card">
                <div className="source-card-head">
                  <div>
                    <span className={`source-tier ${source.tier}`}>{source.tier}</span>
                    <h3>{source.source_domain}</h3>
                    <p>{flagLabel(source.source_type)} · {source.evidence_count} citations</p>
                  </div>
                  <strong>{percentage(source.reliability)}</strong>
                </div>
                <div className="source-score-track"><i style={{ width: percentage(source.reliability) }} /></div>
                {editingSource === source.id ? (
                  <div className="source-edit-panel">
                    <label>
                      Reliability: {percentage(sourceScore)}
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.01"
                        value={sourceScore}
                        onChange={(event) => setSourceScore(Number(event.target.value))}
                      />
                    </label>
                    <label>
                      Assessment basis
                      <textarea
                        rows={2}
                        value={sourceBasis}
                        onChange={(event) => setSourceBasis(event.target.value)}
                      />
                    </label>
                    <div>
                      <button
                        disabled={sourcePending || sourceBasis.trim().length < 3}
                        onClick={() => void saveSource(source.id)}
                      >
                        {sourcePending ? 'Rescoring…' : 'Save and rescore'}
                      </button>
                      <button onClick={() => setEditingSource(null)}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="source-basis">{source.basis}</p>
                    <div className="source-card-footer">
                      <span>{source.is_override ? 'Operator override' : 'Automatic assessment'}</span>
                      <button onClick={() => beginSourceEdit(source)}>Adjust reliability</button>
                    </div>
                  </>
                )}
              </article>
            ))}
          </section>
        ) : (
          <section className="verification-empty panel">
            <span>S</span>
            <h3>No source profiles yet</h3>
            <p>Run verification after evidence-bound claims have been generated.</p>
          </section>
        )
      )}

      {view === 'reviews' && (
        overview.reviews.length ? (
          <section className="review-history panel">
            {overview.reviews.map((review) => (
              <article key={review.id}>
                <span className={`verification-status ${review.decision}`}>{review.decision}</span>
                <div>
                  <strong>{review.statement}</strong>
                  <p>{review.note || 'No operator note supplied.'}</p>
                  <small>{review.previous_status} → {review.decision} · {formatDate(review.created_at)}</small>
                </div>
              </article>
            ))}
          </section>
        ) : (
          <section className="verification-empty panel">
            <span>R</span>
            <h3>No operator decisions yet</h3>
            <p>Reviewed claims and their notes will appear here as a permanent audit trail.</p>
          </section>
        )
      )}
    </div>
  );
}
