'use client';

import { useEffect, useState } from 'react';
import { Icon } from '@/components/Icon';
import { getWorkspaceSettings, saveWorkspaceSettings, testWorkspaceIntegration } from '@/lib/api';
import type { WorkspaceSecretState, WorkspaceSettings } from '@/lib/types';

type IntegrationId = 'youtube' | 'github' | 'newsapi';
type SecretField = 'youtube_api_key' | 'github_token' | 'newsapi_key';

const integrations: Array<{
  id: IntegrationId; field: SecretField; title: string; eyebrow: string; description: string; placeholder: string;
}> = [
  { id: 'youtube', field: 'youtube_api_key', title: 'YouTube Data API', eyebrow: 'Video intelligence', description: 'Channel, video, and public comment metadata with higher and more predictable limits.', placeholder: 'Paste YouTube API key' },
  { id: 'github', field: 'github_token', title: 'GitHub', eyebrow: 'Developer intelligence', description: 'Higher API limits for repositories, releases, organization activity, and public engineering signals.', placeholder: 'Paste fine-grained token' },
  { id: 'newsapi', field: 'newsapi_key', title: 'NewsAPI', eyebrow: 'News discovery', description: 'Broader article discovery to complement RSS feeds and direct publisher crawling.', placeholder: 'Paste NewsAPI key' },
];

function sourceLabel(state?: WorkspaceSecretState) {
  if (!state?.configured) return 'Not connected';
  return state.source === 'saved' ? 'Encrypted workspace credential' : 'Local environment credential';
}

export default function IntegrationsSettingsPage() {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [secrets, setSecrets] = useState<Record<SecretField, string>>({ youtube_api_key: '', github_token: '', newsapi_key: '' });
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<Record<string, string>>({});
  const [error, setError] = useState<Record<string, string>>({});

  const refresh = async () => setSettings(await getWorkspaceSettings());
  useEffect(() => { refresh().catch((reason: unknown) => setError({ page: reason instanceof Error ? reason.message : 'Integrations are unavailable.' })); }, []);

  const save = async (field: SecretField) => {
    const secret = secrets[field].trim();
    if (!secret) { setError((current) => ({ ...current, [field]: 'Enter a credential before saving.' })); return; }
    setBusy(field); setError((current) => ({ ...current, [field]: '' })); setMessage((current) => ({ ...current, [field]: '' }));
    try {
      const result = await saveWorkspaceSettings({ [field]: secret });
      setSettings(result); setSecrets((current) => ({ ...current, [field]: '' }));
      setMessage((current) => ({ ...current, [field]: 'Credential encrypted and saved.' }));
    } catch (reason) {
      setError((current) => ({ ...current, [field]: reason instanceof Error ? reason.message : 'Credential could not be saved.' }));
    } finally { setBusy(null); }
  };

  const clear = async (field: SecretField) => {
    if (!window.confirm('Remove this saved workspace credential? A local environment credential, if present, will become active.')) return;
    setBusy(field); setError((current) => ({ ...current, [field]: '' })); setMessage((current) => ({ ...current, [field]: '' }));
    try {
      const clearField = `clear_${field}` as const;
      const result = await saveWorkspaceSettings({ [clearField]: true });
      setSettings(result); setMessage((current) => ({ ...current, [field]: 'Saved credential removed.' }));
    } catch (reason) {
      setError((current) => ({ ...current, [field]: reason instanceof Error ? reason.message : 'Credential could not be removed.' }));
    } finally { setBusy(null); }
  };

  const test = async (id: IntegrationId, field: SecretField) => {
    setBusy(`test-${field}`); setError((current) => ({ ...current, [field]: '' })); setMessage((current) => ({ ...current, [field]: '' }));
    try {
      const result = await testWorkspaceIntegration(id);
      setMessage((current) => ({ ...current, [field]: result.message }));
    } catch (reason) {
      setError((current) => ({ ...current, [field]: reason instanceof Error ? reason.message : 'Connection test failed.' }));
    } finally { setBusy(null); }
  };

  return (
    <main id="main-content" className="workspace-settings-page">
      <header className="settings-page-hero"><div><span className="eyebrow">External services</span><h1>Integrations</h1><p>Add optional service credentials without opening or editing environment files.</p></div><span className="settings-security-badge"><Icon name="shield" size={16} /> Write-only credentials</span></header>
      {error.page ? <div className="settings-feedback error"><Icon name="error" size={17} /><span>{error.page}</span></div> : null}
      <div className="integration-grid">
        {integrations.map((integration) => {
          const state = settings?.secrets[integration.field];
          const working = busy === integration.field || busy === `test-${integration.field}`;
          return (
            <section key={integration.id} className="integration-card">
              <header><div><span className="eyebrow">{integration.eyebrow}</span><h2>{integration.title}</h2></div><span className={state?.configured ? 'integration-state connected' : 'integration-state'}><span className="status-pulse" />{state?.configured ? 'Connected' : 'Not connected'}</span></header>
              <p>{integration.description}</p>
              <div className="integration-source"><span>Current source</span><strong>{sourceLabel(state)}</strong></div>
              <label className="integration-secret"><span>{state?.source === 'saved' ? 'Replace credential' : 'Credential'}</span><input type="password" value={secrets[integration.field]} onChange={(event) => setSecrets((current) => ({ ...current, [integration.field]: event.target.value }))} placeholder={integration.placeholder} autoComplete="new-password" /><small>For security, saved values are never shown again.</small></label>
              {error[integration.field] ? <div className="integration-message error"><Icon name="error" size={15} />{error[integration.field]}</div> : null}
              {message[integration.field] ? <div className="integration-message success"><Icon name="check" size={15} />{message[integration.field]}</div> : null}
              <div className="integration-actions"><button type="button" className="primary-action" disabled={working || !secrets[integration.field].trim()} onClick={() => save(integration.field)}>{busy === integration.field ? 'Saving…' : 'Save credential'}</button><button type="button" className="secondary-action" disabled={working || !state?.configured} onClick={() => test(integration.id, integration.field)}>{busy === `test-${integration.field}` ? 'Testing…' : 'Test connection'}</button>{state?.source === 'saved' ? <button type="button" className="text-danger-action" disabled={working} onClick={() => clear(integration.field)}>Remove</button> : null}</div>
            </section>
          );
        })}
      </div>
      <section className="settings-privacy-panel compact"><Icon name="shield" size={20} /><div><h2>Encrypted credential vault</h2><p>Credentials are encrypted using the same private vault as the shared AI connection. Scope never returns plaintext secrets through its API or dashboard.</p></div></section>
    </main>
  );
}
