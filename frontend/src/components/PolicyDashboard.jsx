import { useEffect, useState } from 'react';
import { API_BASE } from '../staticConfig';
import DatasetProfileSection from './DatasetProfileSection';
import { SummaryCard } from './DashboardCharts';
import ModelInsightsSection from './ModelInsightsSection';
import PolicyEdaCharts from './PolicyEdaCharts';

export default function PolicyDashboard() {
  const [dataset, setDataset] = useState(null);
  const [insights, setInsights] = useState(null);
  const [error, setError] = useState('');
  const [insightError, setInsightError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [generating, setGenerating] = useState(false);

  const loadDataset = async (file) => {
    setUploading(true);
    setError('');
    try {
      const options = {};
      if (file) {
        const body = new FormData();
        body.append('file', file);
        options.method = 'POST';
        options.body = body;
      }
      const response = await fetch(`${API_BASE}/api/analytics/dataset-insights`, options);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Could not analyze the dataset');
      setDataset(payload);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setUploading(false);
    }
  };

  const loadInsights = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/analytics/model-insights`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Model insights are unavailable');
      setInsights(payload);
      setInsightError('');
    } catch (requestError) {
      setInsightError(requestError.message);
    }
  };

  const generateInsights = async () => {
    setGenerating(true);
    setInsightError('');
    try {
      const response = await fetch(`${API_BASE}/api/analytics/model-insights/generate`, { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail?.message || payload.detail || 'Could not generate insights');
      setInsights(payload);
    } catch (requestError) {
      setInsightError(requestError.message);
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => {
    // These functions start external data synchronization on initial mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadDataset();
    loadInsights();
  }, []);

  const profile = dataset?.profile ?? {};
  const summary = profile.summary ?? {};
  const policy = dataset?.policy_eda;
  const policySummary = policy?.summary ?? {};

  return <div className="h-full min-w-0 overflow-auto p-3 sm:p-5"><div className="mx-auto max-w-7xl">
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-2xl font-bold">Policy Dashboard</h1><p className="mt-1 text-sm text-gray-500">Analyze the baseline survey or upload another CSV.</p></div><label className="cursor-pointer rounded-lg bg-[#1a73e8] px-4 py-2.5 text-sm font-medium text-white"><input type="file" accept=".csv,text/csv" className="hidden" disabled={uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) loadDataset(file); event.target.value = ''; }} />{uploading ? 'Analyzing...' : 'Analyze CSV'}</label></div>
    {error && <div className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
    {!dataset && !error && <div className="rounded-xl border bg-white p-6 text-sm text-gray-500">Loading dataset analysis...</div>}
    {dataset && <><div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><SummaryCard label="Rows" value={Number(summary.rows || 0).toLocaleString()} /><SummaryCard label="Columns" value={summary.columns || 0} /><SummaryCard label="Motorbike users" value={Number(policySummary.motorbike_users || 0).toLocaleString()} /><SummaryCard label="Motorbike share" value={policySummary.motorbike_share || 0} suffix="%" /></div><DatasetProfileSection profile={profile} /><section className="mt-10"><h2 className="text-2xl font-semibold">Mobility Policy EDA</h2><p className="mb-4 mt-1 text-sm text-gray-500">Transport analysis for {dataset.source || 'the active dataset'}.</p><PolicyEdaCharts data={policy} /></section></>}
    <div className="mt-10 flex justify-end"><button type="button" onClick={generateInsights} disabled={generating} className="rounded-lg border border-[#1a73e8] px-4 py-2 text-sm font-medium text-[#1a73e8] disabled:opacity-50">{generating ? 'Generating...' : 'Generate model insights'}</button></div>
    <ModelInsightsSection insights={insights} error={insightError} />
  </div></div>;
}
