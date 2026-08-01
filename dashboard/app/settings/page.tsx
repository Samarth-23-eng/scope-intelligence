'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Icon, type IconName } from '@/components/Icon';
import { getHealth, getLLMConnection, getWorkspaceSettings } from '@/lib/api';
import type { HealthResponse, LLMConnection, WorkspaceSettings } from '@/lib/types';

const destinations: Array<{ href: string; icon: IconName; eyebrow: string; title: string; copy: string }> = [
  { href: '/settings/models', icon: 'spark', eyebrow: 'AI runtime', title: 'AI & agents', copy: 'Choose the single model and provider used by every intelligence agent.' },
  { href: '/settings/collection', icon: 'layers', eyebrow: 'Acquisition', title: 'Collection controls', copy: 'Tune crawler depth, source budgets, social collection, and job research.' },
  { href: '/settings/integrations', icon: 'link', eyebrow: 'Credentials', title: 'Integrations', copy: 'Connect YouTube, GitHub, and NewsAPI without editing configuration files.' },
];

export default function SettingsOverviewPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [model, setModel] = useState<LLMConnection | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getHealth(), getLLMConnection(), getWorkspaceSettings()])
      .then(([nextHealth, nextModel, nextWorkspace]) => {
        if (cancelled) return;
        setHealth(nextHealth);
        setModel(nextModel);
        setWorkspace(nextWorkspace);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Settings are unavailable.');
      });
    return () => { cancelled = true; };
  }, []);

  const connectedIntegrations = workspace
    ? Object.values(workspace.secrets).filter((item) => item.configured).length
    : 0;

  return (
    <main id="main-content" className="settings-overview-page">
      <header className="settings-page-hero">
        <div><span className="eyebrow">Workspace control center</span><h1>Settings</h1><p>Manage the services, collection behavior, and AI runtime behind Scope from one place.</p></div>
        <span className="settings-security-badge"><Icon name="shield" size={16} /> Private & encrypted</span>
      </header>

      {error ? <div className="settings-feedback error"><Icon name="error" size={17} /><span>{error}</span></div> : null}

      <section className="settings-status-strip" aria-label="Workspace status">
        <div><span className="status-pulse" /><small>Platform</small><strong>{health?.status === 'healthy' ? 'Operational' : health ? health.status : 'Checking…'}</strong></div>
        <div><Icon name="spark" size={18} /><small>AI route</small><strong>{model?.configured ? model.display_name : 'Needs setup'}</strong></div>
        <div><Icon name="link" size={18} /><small>Integrations</small><strong>{workspace ? `${connectedIntegrations} of 3 connected` : 'Checking…'}</strong></div>
        <div><Icon name="layers" size={18} /><small>Collection</small><strong>{workspace?.preferences.enable_social_collection ? 'Web + social' : 'Web collection'}</strong></div>
      </section>

      <section className="settings-destination-grid">
        {destinations.map((item) => (
          <Link key={item.href} href={item.href} className="settings-destination-card">
            <span className="settings-destination-icon"><Icon name={item.icon} size={21} /></span>
            <span className="eyebrow">{item.eyebrow}</span>
            <h2>{item.title}</h2>
            <p>{item.copy}</p>
            <span className="settings-card-link">Open settings <Icon name="arrow" size={14} /></span>
          </Link>
        ))}
      </section>

      <section className="settings-privacy-panel">
        <div className="settings-section-heading"><span className="settings-icon"><Icon name="shield" size={19} /></span><div><span className="eyebrow">Security boundary</span><h2>Your secrets stay private</h2></div></div>
        <p>Connector credentials are encrypted before storage and are never returned to the browser. Saved settings apply to future collection runs immediately.</p>
      </section>
    </main>
  );
}
