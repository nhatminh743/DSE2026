import { Fragment, useEffect, useMemo, useState } from 'react';
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer } from 'react-leaflet';
import { API_BASE } from '../staticConfig';

export default function KMedianTab() {
  const [modelData, setModelData] = useState(null);
  const [k, setK] = useState(20);
  const [samplePercent, setSamplePercent] = useState(2);
  const [runId, setRunId] = useState('');
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const running = ['queued', 'running', 'stopping'].includes(status?.state);

  useEffect(() => {
    fetch(`${API_BASE}/api/kmedian-runs/default`).then((response) => response.json().then((payload) => ({ response, payload }))).then(({ response, payload }) => {
      if (!response.ok) throw new Error(payload.detail || 'Could not load the default solution');
      setModelData(payload.solution);
    }).catch((requestError) => setError(requestError.message)).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!runId || !running) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/api/kmedian-runs/${runId}`);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'Could not read solver status');
        setStatus(payload);
        if (payload.state === 'completed') {
          const resultResponse = await fetch(`${API_BASE}/api/kmedian-runs/${runId}/results`);
          const result = await resultResponse.json();
          if (!resultResponse.ok) throw new Error(result.detail || 'Could not load solver results');
          setModelData(result.solution);
        }
        if (payload.state === 'failed') setError(payload.error || payload.message || 'Solver failed');
      } catch (requestError) {
        setError(requestError.message);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [runId, running]);

  const start = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/api/kmedian-runs?k=${encodeURIComponent(k)}&sample_percent=${encodeURIComponent(samplePercent)}`, { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Could not start solver');
      setRunId(payload.run_id);
      setStatus(payload);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  const stop = async () => {
    const response = await fetch(`${API_BASE}/api/kmedian-runs/${runId}/stop`, { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Could not stop solver');
    setStatus(payload);
  };

  const palette = useMemo(() => ['#dc2626', '#2563eb', '#16a34a', '#9333ea', '#ea580c', '#0891b2', '#4f46e5'], []);
  const colors = useMemo(() => (modelData?.stations || []).reduce((output, station, index) => ({ ...output, [station.station_index]: palette[index % palette.length] }), {}), [modelData, palette]);

  return <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)]">
    <aside className="overflow-y-auto border-r bg-white p-5"><h1 className="text-xl font-semibold">K-Median Station Model</h1><p className="mb-5 mt-2 text-sm text-gray-500">Run exact station-placement optimization or inspect the saved default solution.</p>
      <label className="mb-3 block text-sm">Number of stations<input type="number" min="1" max="5000" value={k} onChange={(event) => setK(Number(event.target.value) || 1)} className="mt-1 w-full rounded-lg border p-2.5" /></label>
      <label className="mb-4 block text-sm">Sample percentage<input type="number" min="1" max="100" value={samplePercent} onChange={(event) => setSamplePercent(Number(event.target.value) || 1)} className="mt-1 w-full rounded-lg border p-2.5" /></label>
      <div className="flex gap-2"><button type="button" onClick={start} disabled={loading || running} className="rounded-lg bg-[#1a73e8] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50">{running ? 'Solving...' : 'Run solver'}</button>{running && <button type="button" onClick={() => stop().catch((err) => setError(err.message))} className="rounded-lg border border-red-300 px-4 py-2.5 text-sm text-red-700">Stop</button>}</div>
      {runId && <p className="mt-3 break-all text-xs text-gray-500">Run {runId} · {status?.state}</p>}{error && <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{typeof error === 'string' ? error : JSON.stringify(error)}</div>}
      {modelData && <div className="mt-5 space-y-3"><div className="rounded-xl border p-3"><div className="text-xs text-gray-500">People modeled</div><div className="text-xl font-semibold">{modelData.num_people}</div></div><div className="rounded-xl border p-3"><div className="text-xs text-gray-500">Selected stations</div><div className="text-xl font-semibold">{modelData.num_stations}</div></div><div className="rounded-xl border p-3"><div className="text-xs text-gray-500">Objective weighted km</div><div className="text-xl font-semibold">{Number(modelData.objective_weighted_km || 0).toFixed(3)}</div></div></div>}
    </aside>
    <section className="min-h-[520px]"><MapContainer center={[21.0285, 105.8542]} zoom={11} className="h-full min-h-[520px] w-full"><TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />{(modelData?.stations || []).map((station, index) => <CircleMarker key={station.station_index} center={[station.lat, station.lon]} radius={8} pathOptions={{ color: colors[station.station_index] || palette[index % palette.length], fillOpacity: 0.9 }}><Popup><strong>Station {station.station_index}</strong><div>Assigned people: {station.assigned_people}</div></Popup></CircleMarker>)}{(modelData?.assignments || []).map((assignment, index) => <Fragment key={`${assignment.person_index}-${index}`}><CircleMarker center={[assignment.person_lat, assignment.person_lon]} radius={3} pathOptions={{ color: colors[assignment.station_index] || '#2563eb', fillOpacity: 0.5 }}><Popup>Person {assignment.person_index}<br />Distance: {assignment.distance_km} km</Popup></CircleMarker><Polyline positions={[[assignment.person_lat, assignment.person_lon], [assignment.station_lat, assignment.station_lon]]} color={colors[assignment.station_index] || '#2563eb'} weight={1} opacity={0.25} /></Fragment>)}</MapContainer></section>
  </div>;
}
