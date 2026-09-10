import { useState } from 'react';
import { API_BASE } from '../staticConfig';


export default function ChartExplainButton({ chartId, runId, modelType }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [analysis, setAnalysis] = useState('');
  const [analysisContext, setAnalysisContext] = useState('');
  const [error, setError] = useState('');

  const explain = async () => {
    const context = `${chartId}:${runId || 'default'}:${modelType || 'default'}`;
    setOpen(true);
    if ((analysis && analysisContext === context) || loading) return;
    setLoading(true);
    setError('');
    setAnalysis('');
    try {
      const body = new FormData();
      body.append('chart_id', chartId);
      if (runId) body.append('run_id', runId);
      if (modelType) body.append('model_type', modelType);
      const response = await fetch(`${API_BASE}/api/model-analysis/chart`, { method: 'POST', body });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Gemini could not explain this chart');
      setAnalysis(payload.analysis);
      setAnalysisContext(context);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  return <>
    <button type="button" onClick={explain} title="Ask Gemini to explain this chart" aria-label="Ask Gemini to explain this chart" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[#dadce0] bg-white text-sm font-bold text-[#1a73e8] hover:bg-[#e8f0fe]">?</button>
    {open && <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label="Gemini chart explanation"><div className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-6 shadow-xl"><div className="flex items-center justify-between gap-4"><h3 className="text-lg font-semibold">Gemini chart explanation</h3><button type="button" onClick={() => setOpen(false)} className="rounded-lg px-3 py-1 text-xl text-gray-500 hover:bg-gray-100" aria-label="Close explanation">×</button></div>{loading && <p className="mt-4 text-sm text-gray-500">Analyzing chart data with Gemini 3.1 Flash-Lite...</p>}{error && <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}{analysis && <div className="mt-4 whitespace-pre-wrap text-sm leading-6 text-gray-700">{analysis}</div>}</div></div>}
  </>;
}
