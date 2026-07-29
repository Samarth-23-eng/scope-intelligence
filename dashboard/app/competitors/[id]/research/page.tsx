'use client';

import { useState } from 'react';
import { InvestigationWorkbench } from '@/components/InvestigationWorkbench';
import { VerificationCenter } from '@/components/VerificationCenter';
import { Icon } from '@/components/Icon';
import { useCompanyWorkspace } from '@/components/company/CompanyWorkspace';
import { PageHeading } from '@/components/company/PagePrimitives';

type ResearchView = 'investigations' | 'verification';

export default function ResearchPage() {
  const { competitorId, dataVersion } = useCompanyWorkspace();
  const [view, setView] = useState<ResearchView>('investigations');

  return (
    <main className="company-page">
      <PageHeading
        eyebrow="RESEARCH DESK"
        title="Agent investigations"
        description="Turn a business question into a structured research plan, evidence-backed findings, and an auditable answer."
      />

      <section className="research-intro">
        <div className="research-intro-icon"><Icon name="spark" size={24} /></div>
        <div>
          <span>RESEARCH WORKFLOW</span>
          <h3>From question to defensible conclusion</h3>
          <p>
            The research agent decomposes complex questions, searches the evidence index,
            records citations, identifies gaps, and separates supported facts from inference.
          </p>
        </div>
        <ol>
          <li><span>01</span> Define the question</li>
          <li><span>02</span> Gather evidence</li>
          <li><span>03</span> Verify the claims</li>
        </ol>
      </section>

      <div className="view-switcher research-switcher" role="tablist" aria-label="Research workspace views">
        <button type="button" role="tab" aria-selected={view === 'investigations'} className={view === 'investigations' ? 'active' : ''} onClick={() => setView('investigations')}>
          <Icon name="spark" size={15} />
          Investigations
        </button>
        <button type="button" role="tab" aria-selected={view === 'verification'} className={view === 'verification' ? 'active' : ''} onClick={() => setView('verification')}>
          <Icon name="shield" size={15} />
          Verification queue
        </button>
      </div>

      {view === 'investigations' ? (
        <InvestigationWorkbench competitorId={competitorId} dataVersion={dataVersion} />
      ) : (
        <VerificationCenter competitorId={competitorId} />
      )}
    </main>
  );
}
