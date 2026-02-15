/** Settings page — manage API keys, integrations, and platform config. */

import { useEffect, useState } from 'react';
import {
  getSettings,
  updateSettings,
  listIntegrations,
  connectSlack,
  disconnectIntegration,
} from '../api/client';
import type { IntegrationStatus, PlatformSettings } from '../api/types';

export default function Settings() {
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [integrations, setIntegrations] = useState<IntegrationStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  // Form fields
  const [openaiKey, setOpenaiKey] = useState('');
  const [anthropicKey, setAnthropicKey] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('');
  const [defaultModel, setDefaultModel] = useState('');
  const [slackToken, setSlackToken] = useState('');

  useEffect(() => {
    Promise.all([getSettings(), listIntegrations()])
      .then(([s, i]) => {
        setSettings(s);
        setIntegrations(i);
        setOllamaUrl(s.ollama_base_url);
        setDefaultModel(s.default_model);
      })
      .finally(() => setLoading(false));
  }, []);

  async function handleSaveProviders() {
    setSaving(true);
    setMessage('');
    try {
      const updates: Partial<PlatformSettings> = {};
      if (openaiKey) updates.openai_api_key = openaiKey;
      if (anthropicKey) updates.anthropic_api_key = anthropicKey;
      if (ollamaUrl !== settings?.ollama_base_url) updates.ollama_base_url = ollamaUrl;
      if (defaultModel !== settings?.default_model) updates.default_model = defaultModel;

      const updated = await updateSettings(updates);
      setSettings(updated);
      setOpenaiKey('');
      setAnthropicKey('');
      setMessage('Settings saved');
    } catch (err) {
      setMessage(`Error: ${err}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleConnectSlack() {
    if (!slackToken.trim()) return;
    try {
      await connectSlack(slackToken);
      setSlackToken('');
      const updated = await listIntegrations();
      setIntegrations(updated);
      setMessage('Slack connected');
    } catch (err) {
      setMessage(`Error: ${err}`);
    }
  }

  async function handleDisconnect(name: string) {
    try {
      await disconnectIntegration(name);
      const updated = await listIntegrations();
      setIntegrations(updated);
      setMessage(`${name} disconnected`);
    } catch (err) {
      setMessage(`Error: ${err}`);
    }
  }

  if (loading) {
    return <div className="text-gray-400">Loading settings...</div>;
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold text-white mb-6">Settings</h2>

      {message && (
        <div
          className={`mb-4 px-4 py-2 rounded text-sm ${
            message.startsWith('Error') ? 'bg-red-900/50 text-red-300' : 'bg-green-900/50 text-green-300'
          }`}
        >
          {message}
        </div>
      )}

      {/* Model Providers */}
      <section className="mb-8">
        <h3 className="text-lg font-semibold text-white mb-4">Model Providers</h3>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">OpenAI API Key</label>
            <div className="flex gap-2">
              <input
                type="password"
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
                placeholder={settings?.openai_api_key ? 'Configured (masked)' : 'sk-...'}
                className="flex-1 px-3 py-2 text-sm bg-gray-800 border border-gray-700
                           rounded text-gray-200 placeholder-gray-600
                           focus:outline-none focus:border-blue-500"
              />
              {settings?.openai_api_key && (
                <span className="flex items-center text-xs text-green-500">Connected</span>
              )}
            </div>
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">Anthropic API Key</label>
            <input
              type="password"
              value={anthropicKey}
              onChange={(e) => setAnthropicKey(e.target.value)}
              placeholder={settings?.anthropic_api_key ? 'Configured (masked)' : 'sk-ant-...'}
              className="w-full px-3 py-2 text-sm bg-gray-800 border border-gray-700
                         rounded text-gray-200 placeholder-gray-600
                         focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">Ollama URL</label>
            <input
              type="text"
              value={ollamaUrl}
              onChange={(e) => setOllamaUrl(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-gray-800 border border-gray-700
                         rounded text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">Default Model</label>
            <input
              type="text"
              value={defaultModel}
              onChange={(e) => setDefaultModel(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-gray-800 border border-gray-700
                         rounded text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <button
            onClick={handleSaveProviders}
            disabled={saving}
            className="px-4 py-2 text-sm rounded bg-blue-600 text-white
                       hover:bg-blue-500 transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Provider Settings'}
          </button>
        </div>
      </section>

      {/* Integrations */}
      <section>
        <h3 className="text-lg font-semibold text-white mb-4">Integrations</h3>

        <div className="space-y-4">
          {integrations.map((integ) => (
            <div
              key={integ.name}
              className="flex items-center justify-between p-4 bg-gray-900 border border-gray-800 rounded-lg"
            >
              <div>
                <div className="text-sm font-medium text-gray-200">
                  {integ.display_name}
                </div>
                <div className={`text-xs ${integ.connected ? 'text-green-400' : 'text-gray-500'}`}>
                  {integ.connected ? 'Connected' : 'Not connected'}
                </div>
              </div>
              {integ.connected ? (
                <button
                  onClick={() => handleDisconnect(integ.name)}
                  className="px-3 py-1.5 text-xs rounded bg-gray-800 text-red-400
                             border border-gray-700 hover:border-red-500 transition-colors"
                >
                  Disconnect
                </button>
              ) : integ.name === 'slack' ? (
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={slackToken}
                    onChange={(e) => setSlackToken(e.target.value)}
                    placeholder="xoxb-..."
                    className="px-2 py-1 text-xs bg-gray-800 border border-gray-700
                               rounded text-gray-300 w-36 focus:outline-none focus:border-blue-500"
                  />
                  <button
                    onClick={handleConnectSlack}
                    className="px-3 py-1 text-xs rounded bg-blue-600 text-white
                               hover:bg-blue-500 transition-colors"
                  >
                    Connect
                  </button>
                </div>
              ) : (
                <span className="text-xs text-gray-600">OAuth required</span>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
