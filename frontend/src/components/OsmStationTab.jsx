import { useEffect, useMemo, useState } from 'react';
import { GeoJSON, MapContainer, TileLayer, useMap } from 'react-leaflet';
import L from 'leaflet';
import { API_BASE } from '../staticConfig';

function formatPercent(value) { return value === null || value === undefined ? 'No data' : `${(Number(value) * 100).toFixed(1)}%`; }
function formatNumber(value) { return value === null || value === undefined ? 'No data' : Number(value).toLocaleString(); }
function formatDistance(value, unit) { return value === null || value === undefined ? 'No data' : `${Number(value).toFixed(1)} ${unit}`; }
function interpolateColor(start, end, amount) {
  const startColor = start.match(/\w\w/g).map((value) => parseInt(value, 16));
  const endColor = end.match(/\w\w/g).map((value) => parseInt(value, 16));
  const color = startColor.map((value, index) => Math.round(value + (endColor[index] - value) * amount));
  return `#${color.map((value) => value.toString(16).padStart(2, '0')).join('')}`;
}
function riskColor(value, minimum, maximum) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '#d1d5db';
  const range = maximum - minimum;
  const normalized = range > 0 ? Math.max(0, Math.min(1, (Number(value) - minimum) / range)) : 0.5;
  return normalized <= 0.5 ? interpolateColor('#2ca25f', '#fee08b', normalized * 2) : interpolateColor('#fee08b', '#d73027', (normalized - 0.5) * 2);
}
function FitGeoJson({ data }) {
  const map = useMap();
  useEffect(() => {
    if (!data?.features?.length) return;
    const bounds = L.geoJSON(data).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
  }, [data, map]);
  return null;
}
function MetricRow({ label, value }) {
  return <div className="flex items-start justify-between gap-4 border-b border-gray-100 py-2 last:border-0"><span className="text-sm text-gray-500">{label}</span><span className="text-right text-sm font-semibold text-gray-900">{value}</span></div>;
}

export default function OsmStationTab() {
  const [geoJson, setGeoJson] = useState(null);
  const [selectedDistrict, setSelectedDistrict] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    async function loadMap() {
      try {
        setLoading(true);
        const response = await fetch(`${API_BASE}/api/analytics/district-policy-map`, { signal: controller.signal });
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error(payload?.detail ?? 'Could not load district map');
        setGeoJson(payload);
        const firstWithData = payload.features?.find((feature) => feature.properties?.affected_respondents !== null);
        setSelectedDistrict(firstWithData?.properties ?? payload.features?.[0]?.properties ?? null);
      } catch (requestError) {
        if (requestError.name !== 'AbortError') setError(requestError.message);
      } finally { setLoading(false); }
    }
    loadMap();
    return () => controller.abort();
  }, []);

  const riskRange = useMemo(() => {
    const values = geoJson?.features?.map((feature) => feature.properties?.car_rebound_risk).filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value))).map(Number) ?? [];
    return { minimum: values.length ? Math.min(...values) : 0, maximum: values.length ? Math.max(...values) : 1 };
  }, [geoJson]);

  if (loading) return <div className="flex h-full items-center justify-center p-6 text-gray-500">Loading Hanoi district map...</div>;
  if (error) return <div className="p-4 sm:p-6"><div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">{error}</div></div>;

  const styleFeature = (feature) => ({ fillColor: riskColor(feature.properties?.car_rebound_risk, riskRange.minimum, riskRange.maximum), color: '#374151', weight: 1.25, fillOpacity: 0.68 });
  const onEachFeature = (feature, layer) => {
    const properties = feature.properties ?? {};
    layer.bindTooltip(`<div style="min-width: 180px"><strong>${properties.district_name}</strong><br />Car rebound: ${formatPercent(properties.car_rebound_risk)}<br />Affected: ${formatNumber(properties.affected_respondents)}</div>`, { sticky: true });
    layer.on({ mouseover: () => { layer.setStyle({ weight: 3, color: '#111827', fillOpacity: 0.82 }); layer.bringToFront(); }, mouseout: () => layer.setStyle(styleFeature(feature)), click: () => setSelectedDistrict(properties) });
  };

  return (
    <div className="grid h-full min-h-0 min-w-0 grid-cols-1 gap-3 overflow-auto p-3 lg:grid-cols-[minmax(0,1fr)_340px] lg:overflow-hidden">
      <section className="relative min-h-[520px] min-w-0 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm lg:min-h-0">
        <MapContainer center={[21.03, 105.84]} zoom={10} className="h-full min-h-[520px] w-full lg:min-h-0" preferCanvas>
          <TileLayer attribution="&copy; OpenStreetMap contributors &copy; CARTO" url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" />
          {geoJson && <><GeoJSON key={JSON.stringify(riskRange)} data={geoJson} style={styleFeature} onEachFeature={onEachFeature} /><FitGeoJson data={geoJson} /></>}
        </MapContainer>
        <div className="pointer-events-none absolute bottom-5 left-5 z-[500] rounded-lg border border-gray-200 bg-white/95 p-3 shadow-md"><div className="mb-2 text-xs font-semibold text-gray-700">Predicted car rebound risk</div><div className="h-3 w-48 rounded" style={{ background: 'linear-gradient(to right, #2ca25f, #fee08b, #d73027)' }} /><div className="mt-1 flex justify-between text-[11px] text-gray-500"><span>Lower</span><span>Higher</span></div></div>
      </section>
      <aside className="min-w-0 overflow-auto rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="text-lg font-semibold text-gray-900">District Policy Profile</h2>
        <p className="mt-1 text-xs text-gray-500">Survey source: {geoJson?.metadata?.survey_source}</p>
        {geoJson?.metadata?.metric_source === 'stated_alternatives' && <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">No model weight yet. Showing stated survey alternatives.</div>}
        {selectedDistrict ? <div className="mt-4"><h3 className="mb-3 text-xl font-bold text-blue-700">{selectedDistrict.district_name}</h3><MetricRow label="Affected respondents" value={formatNumber(selectedDistrict.affected_respondents)} /><MetricRow label="Sampled weekly trips" value={formatNumber(selectedDistrict.sampled_weekly_trips)} /><MetricRow label="Car rebound risk" value={formatPercent(selectedDistrict.car_rebound_risk)} /><MetricRow label="E-bike transition" value={formatPercent(selectedDistrict.ebike_propensity)} /><MetricRow label="Bus transition" value={formatPercent(selectedDistrict.bus_propensity)} /><MetricRow label="Rail transition" value={formatPercent(selectedDistrict.rail_propensity)} /><MetricRow label="No sustainable alternative" value={formatPercent(selectedDistrict.no_sustainable_alt_rate)} /><MetricRow label="Median PT distance" value={formatDistance(selectedDistrict.median_pt_distance, 'm')} /><MetricRow label="Median trip distance" value={formatDistance(selectedDistrict.median_od_distance, 'km')} /><MetricRow label="Average distance to assigned center" value={formatDistance(selectedDistrict.average_origin_center_distance, 'km')} /></div> : <div className="mt-4 text-sm text-gray-500">Select a district on the map.</div>}
      </aside>
    </div>
  );
}
