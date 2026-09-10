import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ChartCard, HorizontalBarChart, SummaryCard } from './DashboardCharts';
import ChartExplainButton from './ChartExplainButton';
import { COLORS } from './chartTheme';
import { API_BASE } from '../staticConfig';

const MODEL_LABELS = { random_forest: 'Random forest', decision_tree: 'Decision tree', gradient_boosting: 'Gradient boosting' };
const FALLBACK_LABELS = { alt_car: 'Car', alt_ebike: 'E-bike', alt_bike: 'Bike', alt_bus: 'Bus', alt_ltrain: 'Light rail', alt_taxi: 'Taxi', alt_walk: 'Walk' };
const FEATURE_IDS = { alt_car: 'feature_car', alt_ebike: 'feature_ebike', alt_bike: 'feature_bike', alt_bus: 'feature_bus', alt_ltrain: 'feature_ltrain', alt_taxi: 'feature_taxi', alt_walk: 'feature_walk' };
const FEATURE_COLORS = [COLORS.blue, COLORS.purple, COLORS.teal, COLORS.green, COLORS.orange, COLORS.red, '#7c3aed', '#0891b2'];

function Explain({ chartId, runId, modelType }) {
  return <ChartExplainButton chartId={chartId} runId={runId} modelType={modelType} />;
}

function FeatureChart({ title, rows, color, chartId, runId, modelType }) {
  return <ChartCard title={title} action={<Explain chartId={chartId} runId={runId} modelType={modelType} />}><HorizontalBarChart data={rows} categoryKey="feature" valueKey="importance" color={color} formatter={(value) => Number(value).toFixed(4)} tickFormatter={(value) => Number(value).toFixed(2)} categoryWidth={145} /></ChartCard>;
}

export default function ModelInsightsSection({ insights, error, models = [], selectedModel, onModelChange, runId }) {
  const monteCarlo = insights?.monte_carlo?.total_ice_ban;
  const activeModel = insights?.model_type || selectedModel;
  const featureGroups = insights ? [
    ['Current Mode Choice', insights.feature_importance?.current_mode || [], 'feature_current'],
    ...Object.entries(insights.feature_importance?.fallback_modes || {}).map(([mode, rows]) => [`Fallback: ${FALLBACK_LABELS[mode] || mode}`, rows, FEATURE_IDS[mode] || 'feature_ebike']),
  ] : [];
  const shapUrl = (value) => value?.startsWith('http') || value?.startsWith('/') ? value : value ? `${API_BASE}${value}` : '';

  return <section className="mt-8"><div className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><h2 className="text-2xl font-semibold">Model Insights</h2><p className="mt-1 text-sm text-gray-500">Use the question buttons to ask Gemini for a policy-oriented explanation.</p></div>{models.length > 0 && <label className="text-sm font-medium">Model<select value={selectedModel || ''} onChange={(event) => onModelChange(event.target.value)} className="ml-2 rounded-lg border bg-white px-3 py-2"><option value="" disabled>Select model</option>{models.map((model) => <option key={model} value={model}>{MODEL_LABELS[model] || model}</option>)}</select></label>}</div>
    {error && <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">{typeof error === 'string' ? error : JSON.stringify(error)}</div>}
    {!insights && !error && <div className="rounded-xl border bg-white p-5 text-sm text-gray-500">Generate or train a model to view insights.</div>}
    {insights && <><div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3"><SummaryCard label="Insight model" value={MODEL_LABELS[activeModel] || activeModel || 'Default'} /><SummaryCard label="Affected respondents" value={Number(insights.affected_respondents || 0).toLocaleString()} /><SummaryCard label="Source rows" value={Number(insights.source_rows || 0).toLocaleString()} /></div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">{featureGroups.map(([title, rows, chartId], index) => <FeatureChart key={title} title={title} rows={rows} chartId={chartId} runId={runId} modelType={activeModel} color={FEATURE_COLORS[index % FEATURE_COLORS.length]} />)}</div>
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Travel-Time Elasticity" action={<Explain chartId="elasticity" runId={runId} modelType={activeModel} />}><ResponsiveContainer width="100%" height="100%"><LineChart data={insights.elasticity || []}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="extra_delay_minutes" /><YAxis domain={[0, 1]} /><Tooltip /><Legend /><Line dataKey="car_probability" name="Retain car" stroke={COLORS.red} strokeWidth={3} /><Line dataKey="moto_probability" name="Retain motorbike" stroke={COLORS.orange} strokeWidth={3} /><Line dataKey="alternative_probability" name="Shift" stroke={COLORS.green} strokeWidth={3} /></LineChart></ResponsiveContainer></ChartCard>
        <ChartCard title="E-Bike Distance Partial Dependence" action={<Explain chartId="partial_dependence" runId={runId} modelType={activeModel} />}><ResponsiveContainer width="100%" height="100%"><LineChart data={insights.partial_dependence || []}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="distance_km" /><YAxis domain={[0, 1]} /><Tooltip /><Line dataKey="ebike_probability" stroke={COLORS.purple} strokeWidth={3} /></LineChart></ResponsiveContainer></ChartCard>
        <ChartCard title="Monte Carlo: Total ICE Ban" action={<Explain chartId="monte_carlo" runId={runId} modelType={activeModel} />}><ResponsiveContainer width="100%" height="100%"><BarChart data={monteCarlo?.modes || []}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="mode" /><YAxis /><Tooltip /><Bar dataKey="mean_users" fill={COLORS.green} /></BarChart></ResponsiveContainer></ChartCard>
        <ChartCard title="SHAP Summary" action={<Explain chartId="shap_summary" runId={runId} modelType={activeModel} />} height="h-auto">{shapUrl(insights.shap?.summary_url) ? <img src={shapUrl(insights.shap.summary_url)} alt="SHAP summary" className="w-full rounded-xl border" /> : <p className="text-sm text-gray-500">Unavailable</p>}</ChartCard>
        <ChartCard title="SHAP Distance Dependence" action={<Explain chartId="shap_distance" runId={runId} modelType={activeModel} />} height="h-auto">{shapUrl(insights.shap?.distance_dependence_url) ? <img src={shapUrl(insights.shap.distance_dependence_url)} alt="SHAP distance dependence" className="w-full rounded-xl border" /> : <p className="text-sm text-gray-500">Unavailable</p>}</ChartCard>
      </div></>}
  </section>;
}
