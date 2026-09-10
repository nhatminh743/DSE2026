import { useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../staticConfig';
import ModelInsightsSection from './ModelInsightsSection';

const MODEL_LABELS = { gradient_boosting: 'Gradient boosting', random_forest: 'Random forest', decision_tree: 'Decision tree' };
const MODEL_NAMES = Object.keys(MODEL_LABELS);

function Report({ report }) {
  const rows = Object.entries(report || {}).filter(([, value]) => value && typeof value === 'object' && 'precision' in value);
  if (!rows.length) return <p className="text-sm text-gray-500">No report available.</p>;
  return <div className="overflow-auto rounded-xl border"><table className="w-full text-xs"><thead className="bg-gray-50"><tr><th className="p-2 text-left">Class</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{rows.map(([name, value]) => <tr key={name} className="border-t"><td className="p-2">{name}</td><td className="text-center">{Number(value.precision || 0).toFixed(3)}</td><td className="text-center">{Number(value.recall || 0).toFixed(3)}</td><td className="text-center">{Number(value['f1-score'] || 0).toFixed(3)}</td></tr>)}</tbody></table></div>;
}

export default function ModelLabTab() {
  const [sourceType, setSourceType] = useState('csv');
  const [file, setFile] = useState(null);
  const [testSize, setTestSize] = useState(0.2);
  const [estimators, setEstimators] = useState(100);
  const [enabledModels, setEnabledModels] = useState(MODEL_NAMES);
  const [runId, setRunId] = useState('');
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [selectedModel, setSelectedModel] = useState('');
  const [insights, setInsights] = useState(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [llm, setLlm] = useState('');
  const running = ['queued', 'running', 'stopping'].includes(status?.state);

  const modelEntries = useMemo(() => Object.entries(results?.models || {}), [results]);

  const loadResults = async (id) => {
    const response = await fetch(`${API_BASE}/api/model-runs/${id}/results`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail?.message || payload.detail || 'Could not load results');
    setResults(payload);
    setSelectedModel(payload.selected_default_model || Object.keys(payload.models || {})[0] || '');
  };

  useEffect(() => {
    if (!runId || !running) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/api/model-runs/${runId}`);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'Could not read training status');
        setStatus(payload);
        if (payload.state === 'completed') await loadResults(runId);
        if (payload.state === 'failed') setError(payload.error || payload.message || 'Training failed');
      } catch (requestError) {
        setError(requestError.message);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [runId, running]);

  const startTraining = async () => {
    if (sourceType === 'csv' && !file) { setError('Choose a CSV file first.'); return; }
    if (!enabledModels.length) { setError('Select at least one model.'); return; }
    setStarting(true);
    setError('');
    setResults(null);
    setInsights(null);
    try {
      const body = new FormData();
      body.append('source_type', sourceType);
      body.append('test_size', String(testSize));
      body.append('n_estimators', String(estimators));
      body.append('models', enabledModels.join(','));
      if (file) body.append('file', file);
      const response = await fetch(`${API_BASE}/api/model-runs/train`, { method: 'POST', body });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Could not start training');
      setRunId(payload.run_id);
      setStatus(payload);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setStarting(false);
    }
  };

  const stopTraining = async () => {
    const response = await fetch(`${API_BASE}/api/model-runs/${runId}/stop`, { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Could not stop training');
    setStatus(payload);
  };

  const generateInsights = async () => {
    setGenerating(true);
    setError('');
    try {
      const body = new FormData();
      body.append('model_type', selectedModel);
      const response = await fetch(`${API_BASE}/api/model-runs/${runId}/insights/generate`, { method: 'POST', body });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail?.message || payload.detail || 'Could not generate insights');
      setInsights(payload);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setGenerating(false);
    }
  };

  const askGemini = async () => {
    setLlm('Loading Gemini analysis...');
    const body = new FormData();
    body.append('run_id', runId);
    try {
      const response = await fetch(`${API_BASE}/api/model-analysis/llm`, { method: 'POST', body });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Gemini analysis failed');
      setLlm(payload.analysis);
    } catch (requestError) {
      setLlm(requestError.message);
    }
  };

  const toggleModel = (name) => setEnabledModels((current) => current.includes(name) ? current.filter((item) => item !== name) : [...current, name]);

  return <div className="h-full overflow-y-auto p-4 sm:p-8"><div className="mx-auto max-w-7xl">
    <h1 className="text-3xl font-semibold">Transport Model Lab</h1><p className="mb-6 mt-2 text-sm text-gray-500">Train and compare Gradient Boosting, Random Forest, and Decision Tree models.</p>
    <section className="rounded-2xl border bg-white p-5"><div className="grid gap-4 md:grid-cols-4"><label className="text-sm">Data source<select value={sourceType} onChange={(event) => setSourceType(event.target.value)} className="mt-1 w-full rounded-lg border p-2.5"><option value="csv">CSV upload</option><option value="database">Configured database/baseline</option></select></label><label className="text-sm">Test size<input type="number" min="0.05" max="0.5" step="0.05" value={testSize} onChange={(event) => setTestSize(Number(event.target.value))} className="mt-1 w-full rounded-lg border p-2.5" /></label><label className="text-sm">Estimators<input type="number" min="10" max="1000" value={estimators} onChange={(event) => setEstimators(Number(event.target.value))} className="mt-1 w-full rounded-lg border p-2.5" /></label>{sourceType === 'csv' && <label className="text-sm">Training CSV<input type="file" accept=".csv" onChange={(event) => setFile(event.target.files?.[0] || null)} className="mt-1 block w-full text-xs" /></label>}</div>
      <div className="mt-4 flex flex-wrap gap-4">{MODEL_NAMES.map((name) => <label key={name} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabledModels.includes(name)} onChange={() => toggleModel(name)} />{MODEL_LABELS[name]}</label>)}</div>
      <div className="mt-5 flex flex-wrap gap-3"><button type="button" onClick={startTraining} disabled={starting || running} className="rounded-lg bg-[#1a73e8] px-5 py-2.5 font-medium text-white disabled:opacity-50">{starting ? 'Starting...' : running ? 'Training...' : 'Train models'}</button>{running && <button type="button" onClick={() => stopTraining().catch((err) => setError(err.message))} className="rounded-lg border border-red-300 px-5 py-2.5 text-red-700">Stop</button>}{runId && <span className="self-center text-xs text-gray-500">Run {runId} · {status?.state}</span>}</div>
    </section>
    {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{typeof error === 'string' ? error : JSON.stringify(error)}</div>}
    {modelEntries.length > 0 && <><div className="mt-6 space-y-5">{modelEntries.map(([name, output]) => <section key={name} className="rounded-2xl border bg-white p-5"><div className="mb-4 flex justify-between"><h2 className="text-lg font-semibold">{MODEL_LABELS[name] || name}</h2><span className="text-sm">Score {Number(output.score || 0).toFixed(3)}</span></div><div className="grid gap-5 lg:grid-cols-2"><Report report={output.metrics?.current_mode} /><Report report={output.metrics?.fallback_modes} /></div></section>)}</div>
      <section className="mt-6 rounded-2xl border bg-white p-5"><div className="flex flex-wrap items-center gap-3"><select value={selectedModel} onChange={(event) => { setSelectedModel(event.target.value); setInsights(null); }} className="rounded-lg border px-3 py-2">{modelEntries.map(([name]) => <option key={name} value={name}>{MODEL_LABELS[name] || name}</option>)}</select><button type="button" onClick={generateInsights} disabled={generating} className="rounded-lg bg-[#1a73e8] px-4 py-2 text-sm text-white disabled:opacity-50">{generating ? 'Generating...' : 'Generate charts and SHAP'}</button><button type="button" onClick={askGemini} className="rounded-lg border border-[#1a73e8] px-4 py-2 text-sm text-[#1a73e8]">Ask Gemini about results</button><a href={`${API_BASE}/api/model-runs/${runId}/download`} className="rounded-lg border px-4 py-2 text-sm">Download weights</a></div>{llm && <div className="mt-4 whitespace-pre-wrap rounded-xl bg-blue-50 p-4 text-sm">{llm}</div>}</section>
      <ModelInsightsSection insights={insights} runId={runId} selectedModel={selectedModel} models={modelEntries.map(([name]) => name)} onModelChange={(name) => { setSelectedModel(name); setInsights(null); }} />
    </>}
  </div></div>;
}
