import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ChartCard, HorizontalBarChart } from './DashboardCharts';
import { COLORS } from './chartTheme';

export default function DatasetProfileSection({ profile }) {
  const distributions = [
    ...(profile?.categorical_distributions || []).map((item) => ({ ...item, type: 'categorical' })),
    ...(profile?.numeric_distributions || []).map((item) => ({ ...item, type: 'numeric' })),
  ];
  const [selectedColumn, setSelectedColumn] = useState('');
  const selected = distributions.find((item) => item.column === selectedColumn) || distributions[0];

  return <section className="mt-8"><div className="mb-4"><h2 className="text-2xl font-semibold">Dataset Overview</h2><p className="mt-1 text-sm text-gray-500">Data quality and a compact explorer for the active CSV.</p></div><div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
    <ChartCard title="Missing Values by Column" subtitle="Top 15 columns by missing percentage."><HorizontalBarChart data={profile?.missing_by_column || []} categoryKey="column" valueKey="percentage" color={COLORS.orange} categoryWidth={130} /></ChartCard>
    <ChartCard title="Explore a Column" subtitle="Choose one column instead of rendering repeated distribution charts."><div className="mb-3"><select value={selected?.column || ''} onChange={(event) => setSelectedColumn(event.target.value)} className="w-full rounded-lg border border-gray-300 p-2 text-sm">{distributions.map((item) => <option key={`${item.type}-${item.column}`} value={item.column}>{item.column} ({item.type})</option>)}</select></div><div className="h-[250px]">{selected?.type === 'categorical' ? <HorizontalBarChart data={selected.values} categoryKey="category" valueKey="percentage" color={COLORS.blue} categoryWidth={135} /> : selected ? <ResponsiveContainer width="100%" height="100%"><BarChart data={selected.values}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="range" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={55} /><YAxis /><Tooltip /><Bar dataKey="count" fill={COLORS.green} /></BarChart></ResponsiveContainer> : <p className="text-sm text-gray-500">No suitable columns were found.</p>}</div></ChartCard>
    <ChartCard title="Strongest Numeric Correlations" subtitle="Pearson correlations; association does not imply causation." height="h-80"><div className="h-full overflow-auto"><table className="w-full text-sm"><thead className="sticky top-0 bg-gray-50"><tr><th className="p-2 text-left">Column A</th><th className="p-2 text-left">Column B</th><th className="p-2 text-right">Correlation</th></tr></thead><tbody>{(profile?.correlations || []).map((row) => <tr key={`${row.left}-${row.right}`} className="border-t"><td className="p-2">{row.left}</td><td className="p-2">{row.right}</td><td className="p-2 text-right font-medium">{Number(row.correlation).toFixed(3)}</td></tr>)}</tbody></table></div></ChartCard>
  </div></section>;
}
