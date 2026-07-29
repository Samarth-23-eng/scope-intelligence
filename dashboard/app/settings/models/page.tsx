'use client';

import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Icon } from '@/components/Icon';
import {
  getLLMConnection,
  getLLMProviderPresets,
  resetLLMConnection,
  saveLLMConnection,
  testLLMConnection,
} from '@/lib/api';
import type {
  LLMConnection,
  LLMConnectionUpdate,
  LLMProviderPresets,
} from '@/lib/types';

const EMPTY_FORM: LLMConnectionUpdate = {
  provider: 'openai_compatible',
  display_name: 'Custom endpoint',
  base_url: 'http://localhost:8001/v1',
  model: '',
  auth_mode: 'api_key',
  enabled: true,
};

export default function ModelConnectionsPage() {
  const [connection, setConnection] = useState<LLMConnection | null>(null);
  const [presets, setPresets] = useState<LLMProviderPresets | null>(null);
  const [form, setForm] = useState<LLMConnectionUpdate>(EMPTY_FORM);
  const [secret, setSecret] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currentPreset = useMemo(
    () => presets?.providers.find((item) => item.id === form.provider),
    [form.provider, presets],
  );

  const applyConnection = (value: LLMConnection) => {
    setConnection(value);
    setForm({
      provider: value.provider,
      display_name: value.display_name,
      base_url: value.base_url,
      model: value.model,
      auth_mode: value.auth_mode,
      enabled: value.enabled,
    });
    setSecret('');
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([getLLMConnection(), getLLMProviderPresets()])
      .then(([current, providerPresets]) => {
        if (cancelled) return;
        setPresets(providerPresets);
        applyConnection(current);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : 'Model settings are unavailable.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectProvider = (provider: string) => {
    const preset = presets?.providers.find((item) => item.id === provider);
    setForm((current) => ({
      ...current,
      provider,
      display_name: preset?.label ?? current.display_name,
      base_url: preset?.base_url ?? current.base_url,
      auth_mode: preset?.default_auth_mode ?? current.auth_mode,
    }));
    setSecret('');
    setMessage(null);
    setError(null);
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      if (
        form.auth_mode !== 'none' &&
        !secret &&
        (!connection?.has_secret || connection.source === 'environment')
      ) {
        throw new Error('Enter the provider key or access token before saving this connection.');
      }
      const saved = await saveLLMConnection({
        ...form,
        api_key: secret || undefined,
      });
      applyConnection(saved);
      setMessage('Connection saved. Every AI agent will now use this provider and model.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The connection could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setMessage(null);
    setError(null);
    try {
      const result = await testLLMConnection();
      setMessage(result.message);
      setConnection(await getLLMConnection());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The provider test failed.');
      setConnection(await getLLMConnection().catch(() => connection));
    } finally {
      setTesting(false);
    }
  };

  const reset = async () => {
    if (!window.confirm('Remove the saved model connection and return to the local environment configuration?')) {
      return;
    }
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const result = await resetLLMConnection();
      applyConnection(result.connection);
      setMessage('Saved credentials removed. Environment settings are active again.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The saved connection could not be removed.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <main id="main-content" className="model-settings-page">
        <div className="model-settings-loading">Loading secure model settings…</div>
      </main>
    );
  }

  return (
    <main id="main-content" className="model-settings-page">
      <header className="model-settings-hero">
        <div>
          <span className="eyebrow">AI infrastructure</span>
          <h1>Model connections</h1>
          <p>Connect one model once. Every research, analysis, relationship, and reporting agent uses it.</p>
        </div>
        <div className={`connection-state ${connection?.last_status ?? 'untested'}`}>
          <span className="status-pulse" />
          <div>
            <small>Active connection</small>
            <strong>{connection?.display_name ?? 'Not configured'}</strong>
          </div>
          <span>{connection?.last_status === 'connected' ? 'Verified' : connection?.configured ? 'Ready to test' : 'Needs setup'}</span>
        </div>
      </header>

      <section className="model-settings-grid">
        <form className="model-connection-form" onSubmit={save}>
          <div className="settings-section-heading">
            <span className="settings-icon"><Icon name="link" size={19} /></span>
            <div>
              <span className="eyebrow">Shared agent gateway</span>
              <h2>Provider configuration</h2>
            </div>
          </div>

          <div className="provider-picker" role="radiogroup" aria-label="Model provider">
            {presets?.providers.map((provider) => (
              <button
                type="button"
                role="radio"
                aria-checked={form.provider === provider.id}
                className={form.provider === provider.id ? 'selected' : ''}
                key={provider.id}
                onClick={() => selectProvider(provider.id)}
              >
                <span>{provider.label}</span>
                <small>{provider.id === 'openai_compatible' ? 'Any compatible API' : provider.id}</small>
              </button>
            ))}
          </div>

          <div className="settings-fields">
            <label>
              <span>Connection name</span>
              <input
                value={form.display_name ?? ''}
                onChange={(event) => setForm({ ...form, display_name: event.target.value })}
                placeholder={currentPreset?.label}
              />
            </label>
            <label>
              <span>Model ID</span>
              <input
                required
                value={form.model}
                onChange={(event) => setForm({ ...form, model: event.target.value })}
                placeholder="e.g. gpt-5, claude-sonnet-4, llama3.2"
                spellCheck={false}
              />
            </label>
            <label className="full-field">
              <span>Provider URL</span>
              <input
                required
                type="url"
                value={form.base_url ?? ''}
                onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                spellCheck={false}
              />
              <small>Local Ollama and LM Studio addresses are translated automatically when the app runs in Docker.</small>
            </label>
            <label>
              <span>Authentication</span>
              <select
                value={form.auth_mode}
                onChange={(event) => setForm({
                  ...form,
                  auth_mode: event.target.value as LLMConnectionUpdate['auth_mode'],
                })}
              >
                {presets?.auth_modes.map((mode) => (
                  <option key={mode.id} value={mode.id}>{mode.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>{form.auth_mode === 'bearer' ? 'Access token' : 'API key'}</span>
              <input
                type="password"
                value={secret}
                disabled={form.auth_mode === 'none'}
                onChange={(event) => setSecret(event.target.value)}
                autoComplete="new-password"
                placeholder={
                  form.auth_mode === 'none'
                    ? 'Not required'
                    : connection?.has_secret && connection.source === 'saved'
                      ? 'Saved securely — enter only to replace'
                      : 'Enter credential'
                }
              />
            </label>
          </div>

          <div className="credential-note">
            <Icon name="shield" size={18} />
            <p><strong>Encrypted at rest.</strong> The credential is encrypted before database storage and is never sent back to this page.</p>
          </div>

          {error ? <div className="settings-feedback error"><Icon name="error" size={17} /><span>{error}</span></div> : null}
          {message ? <div className="settings-feedback success"><Icon name="check" size={17} /><span>{message}</span></div> : null}

          <div className="settings-actions">
            <button type="submit" className="primary-action" disabled={saving}>
              {saving ? 'Saving…' : 'Save connection'}
            </button>
            <button type="button" className="secondary-action" disabled={testing || !connection?.configured} onClick={test}>
              <Icon name="activity" size={17} />
              {testing ? 'Testing live model…' : 'Test connection'}
            </button>
          </div>
        </form>

        <aside className="model-settings-aside">
          <section>
            <span className="eyebrow">Runtime contract</span>
            <h2>One model, all agents</h2>
            <ul className="agent-route-list">
              {['Discovery & investigation', 'Evidence analysis', 'Signals & predictions', 'Entity resolution', 'Relationship intelligence', 'Executive reporting'].map((label) => (
                <li key={label}><Icon name="check" size={15} /><span>{label}</span></li>
              ))}
            </ul>
          </section>

          <section className="connection-details">
            <span className="eyebrow">Current route</span>
            <dl>
              <div><dt>Provider</dt><dd>{connection?.display_name ?? '—'}</dd></div>
              <div><dt>Model</dt><dd>{connection?.model ?? '—'}</dd></div>
              <div><dt>Source</dt><dd>{connection?.source === 'saved' ? 'Encrypted workspace setting' : 'Local environment file'}</dd></div>
              <div><dt>Credential</dt><dd>{connection?.has_secret ? 'Stored' : connection?.auth_mode === 'none' ? 'Not required' : 'Missing'}</dd></div>
              <div><dt>Last check</dt><dd>{connection?.last_tested_at ? new Date(connection.last_tested_at).toLocaleString() : 'Not tested'}</dd></div>
            </dl>
            {connection?.last_error ? (
              <div className="last-provider-error">
                <strong>Latest provider error</strong>
                <p>{connection.last_error}</p>
              </div>
            ) : null}
          </section>

          {connection?.source === 'saved' ? (
            <button type="button" className="reset-connection" onClick={reset} disabled={saving}>
              <Icon name="trash" size={16} />
              Remove saved connection
            </button>
          ) : null}
        </aside>
      </section>
    </main>
  );
}
