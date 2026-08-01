'use client';

import { SocialCollectionStudio } from '@/components/collection/SocialCollectionStudio';
import { DeepResearchLab } from '@/components/collection/DeepResearchLab';
import { useCompanyWorkspace } from '@/components/company/CompanyWorkspace';
import { useState } from 'react';

export default function CollectionStudioPage() {
  const { competitorId, dataVersion, refreshWorkspace } = useCompanyWorkspace();
  const [lab, setLab] = useState<'social' | 'deep'>('social');

  return (
    <div className="collection-workspace">
      <nav className="collection-lab-tabs" aria-label="Collection laboratories">
        <button type="button" className={lab === 'social' ? 'active' : ''} onClick={() => setLab('social')}><span>01</span>Social Collection</button>
        <button type="button" className={lab === 'deep' ? 'active experimental' : 'experimental'} onClick={() => setLab('deep')}><span>02</span>Deep Research <small>LAB</small></button>
      </nav>
      {lab === 'social' ? <SocialCollectionStudio competitorId={competitorId} dataVersion={dataVersion} onIntelligenceChanged={refreshWorkspace} /> : <DeepResearchLab competitorId={competitorId} dataVersion={dataVersion} onIntelligenceChanged={refreshWorkspace} />}
    </div>
  );
}
