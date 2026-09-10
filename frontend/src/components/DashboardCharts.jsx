import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { COLORS, percentTooltip } from './chartTheme';

export function ChartCard({ title, subtitle, action, children, height = 'h-80' }) {
  return <section className="min-w-0 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
    <div className="flex items-start justify-between gap-3"><div><h2 className="text-base font-semibold text-gray-900 sm:text-lg">{title}</h2>{subtitle && <p className="mt-1 text-sm text-gray-500">{subtitle}</p>}</div>{action}</div>
    <div className={`mt-4 min-w-0 ${height}`}>{children}</div>
  </section>;
}

export function SummaryCard({ label, value, suffix = '' }) {
  return <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm"><div className="text-sm text-gray-500">{label}</div><div className="mt-1 text-2xl font-bold text-gray-900">{value}{suffix}</div></div>;
}

export function HorizontalBarChart({ data = [], categoryKey, valueKey, color = COLORS.blue, formatter = percentTooltip, tickFormatter = (value) => `${value}%`, categoryWidth = 105 }) {
  return <ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ top: 5, right: 35, bottom: 5, left: 30 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tickFormatter={tickFormatter} /><YAxis type="category" dataKey={categoryKey} width={categoryWidth} tick={{ fontSize: 12 }} /><Tooltip formatter={(value) => formatter(value)} /><Bar dataKey={valueKey} fill={color} radius={[0, 5, 5, 0]} /></BarChart></ResponsiveContainer>;
}

export function Heatmap({ heatmap = { columns: [], rows: [] } }) {
  const values = heatmap.rows.flatMap((row) => row.values.filter((value) => value !== null));
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 100;
  const color = (value) => {
    if (value === null) return '#f3f4f6';
    const normalized = maximum > minimum ? (value - minimum) / (maximum - minimum) : 0.5;
    return `rgb(${Math.round(238 - normalized * 30)}, ${Math.round(242 - normalized * 150)}, ${Math.round(255 - normalized * 150)})`;
  };
  return <div className="h-full overflow-auto"><table className="w-full min-w-[650px] border-collapse text-sm"><thead><tr><th className="border p-2 text-left">Occupation</th>{heatmap.columns.map((column) => <th key={column} className="border p-2 text-center">{column}</th>)}</tr></thead><tbody>{heatmap.rows.map((row) => <tr key={row.occupation}><th className="border p-2 text-left font-medium">{row.occupation}</th>{row.values.map((value, index) => <td key={`${row.occupation}-${heatmap.columns[index]}`} className="border p-3 text-center font-semibold" style={{ backgroundColor: color(value) }}>{value === null ? '-' : `${value.toFixed(1)}%`}</td>)}</tr>)}</tbody></table></div>;
}
