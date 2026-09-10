import { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, Marker, Popup, Polyline, TileLayer } from 'react-leaflet';
import polyline from '@mapbox/polyline';
import L from 'leaflet';
import { Navigation } from 'lucide-react';
import '../fix-leaflet';
import { MapUpdater } from './MapUpdater';
import { API_BASE } from '../staticConfig';

const INITIAL_START = [21.0177, 105.789];
const INITIAL_END = [20.9919, 105.806];
const ELECTRICITY_PRICE_VND_PER_KWH = 2500;
const EV_KWH_PER_100KM = 3.0;
const WEEKS_PER_MONTH = 4.33;

const createMarkerIcon = (color, letter) =>
  new L.DivIcon({
    className: '',
    html: `
      <div style="
        width: 18px;
        height: 18px;
        border-radius: 9999px;
        background: ${color};
        border: 2px solid #ffffff;
        box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.08), 0 3px 10px rgba(0,0,0,0.2);
        display: flex;
        align-items: center;
        justify-content: center;
        color: #ffffff;
        font-size: 10px;
        font-weight: 700;
        line-height: 1;
        user-select: none;
      ">${letter}</div>
    `,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -10],
  });

const startMarkerIcon = createMarkerIcon('#22c55e', 'S');
const endMarkerIcon = createMarkerIcon('#ef4444', 'D');

export function RouteCalculatorTab() {
  const [startPos, setStartPos] = useState(INITIAL_START);
  const [endPos, setEndPos] = useState(INITIAL_END);
  const [routeMode, setRouteMode] = useState('public_transport');
  const [tripsPerWeek, setTripsPerWeek] = useState(10);
  const [evPrice, setEvPrice] = useState(30000000);
  const [compactTable, setCompactTable] = useState(false);
  const [compactPanel, setCompactPanel] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [resultsByMode, setResultsByMode] = useState({});
  const [startSearch, setStartSearch] = useState('');
  const [endSearch, setEndSearch] = useState('');
  const [startSuggestions, setStartSuggestions] = useState([]);
  const [endSuggestions, setEndSuggestions] = useState([]);
  const [startSearchLoading, setStartSearchLoading] = useState(false);
  const [endSearchLoading, setEndSearchLoading] = useState(false);

  const [inputMode, setInputMode] = useState('search');
  const skipStartAutocompleteRef = useRef(false);
  const skipEndAutocompleteRef = useRef(false);

  const startMarkerRef = useRef(null);
  const endMarkerRef = useRef(null);

  const startHandlers = useMemo(
    () => ({
      dragend() {
        const marker = startMarkerRef.current;
        if (marker) {
          const latlng = marker.getLatLng();
          setStartPos([latlng.lat, latlng.lng]);
        }
      },
    }),
    []
  );

  const endHandlers = useMemo(
    () => ({
      dragend() {
        const marker = endMarkerRef.current;
        if (marker) {
          const latlng = marker.getLatLng();
          setEndPos([latlng.lat, latlng.lng]);
        }
      },
    }),
    []
  );

  const activeRoute = resultsByMode[routeMode] || null;

  const routeCoordinates = useMemo(() => {
    const encoded = activeRoute?.polyline;
    if (!encoded) return [];
    return polyline.decode(encoded);
  }, [activeRoute]);

  const stripHtml = (html) => {
    if (!html) return '';
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const raw = doc.body.textContent || '';
    return raw
      .replace(/([a-z0-9)])(Pass by|Destination will be on|Slight|Turn|Keep|Continue|Merge|Take the)/g, '$1. $2')
      .replace(/\s+/g, ' ')
      .trim();
  };

  const updateStartCoord = (index, value) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    setStartPos((prev) => (index === 0 ? [parsed, prev[1]] : [prev[0], parsed]));
  };

  const updateEndCoord = (index, value) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    setEndPos((prev) => (index === 0 ? [parsed, prev[1]] : [prev[0], parsed]));
  };

  const fetchAutocomplete = async (queryText, signal) => {
    const res = await fetch(
      `${API_BASE}/api/maps/autocomplete?input=${encodeURIComponent(queryText)}`,
      { signal }
    );
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(errorText || 'Failed to fetch suggestions');
    }
    const data = await res.json();
    return data.suggestions || [];
  };

  const fetchPlaceDetails = async (placeId) => {
    const res = await fetch(`${API_BASE}/api/maps/place-details?place_id=${encodeURIComponent(placeId)}`);
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(errorText || 'Failed to fetch place details');
    }
    return await res.json();
  };

  useEffect(() => {
    if (skipStartAutocompleteRef.current) {
      skipStartAutocompleteRef.current = false;
      setStartSuggestions([]);
      return;
    }

    if (startSearch.trim().length < 2) {
      return;
    }

    const controller = new AbortController();

    const timeoutId = setTimeout(async () => {
      setStartSearchLoading(true);

      try {
        const suggestions = await fetchAutocomplete(
          startSearch.trim(),
          controller.signal
        );

        if (!controller.signal.aborted) {
          setStartSuggestions(suggestions);
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          setStartSuggestions([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          setStartSearchLoading(false);
        }
      }
    }, 300);

    return () => {
      clearTimeout(timeoutId);
      controller.abort();
    };
  }, [startSearch]);

  useEffect(() => {
    if (skipEndAutocompleteRef.current) {
      skipEndAutocompleteRef.current = false;
      setEndSuggestions([]);
      return;
    }

    if (endSearch.trim().length < 2) {
      return;
    }

    const controller = new AbortController();

    const timeoutId = setTimeout(async () => {
      setEndSearchLoading(true);

      try {
        const suggestions = await fetchAutocomplete(
          endSearch.trim(),
          controller.signal
        );

        if (!controller.signal.aborted) {
          setEndSuggestions(suggestions);
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          setEndSuggestions([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          setEndSearchLoading(false);
        }
      }
    }, 300);

    return () => {
      clearTimeout(timeoutId);
      controller.abort();
    };
  }, [endSearch]);

  const pickStartSuggestion = async (suggestion) => {
    try {
      const place = await fetchPlaceDetails(suggestion.place_id);

      setStartPos([place.lat, place.lng]);

      skipStartAutocompleteRef.current = true;
      setStartSearch(suggestion.description);
      setStartSuggestions([]);
    } catch (err) {
      setError(err.message);
    }
  };

  const pickEndSuggestion = async (suggestion) => {
    try {
      const place = await fetchPlaceDetails(suggestion.place_id);

      setEndPos([place.lat, place.lng]);

      skipEndAutocompleteRef.current = true;
      setEndSearch(suggestion.description);
      setEndSuggestions([]);
    } catch (err) {
      setError(err.message);
    }
  };

  const fetchMode = async (mode, payloadBase) => {
    const res = await fetch(`${API_BASE}/api/calculator/public_transport`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payloadBase, transport_mode: mode }),
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(errorText || `Failed to fetch ${mode}`);
    }

    const data = await res.json();
    if (!data.success) {
      throw new Error(data.error_reason || `Routing failed for ${mode}`);
    }

    return data;
  };

  const handleCalculate = async () => {
    setLoading(true);
    setError('');

    const payloadBase = {
      orig_lat: startPos[0],
      orig_lon: startPos[1],
      dest_lat: endPos[0],
      dest_lon: endPos[1],
    };

    try {
      const [publicTransport, motorbike, car] = await Promise.all([
        fetchMode('public_transport', payloadBase),
        fetchMode('motorbike', payloadBase),
        fetchMode('car', payloadBase),
      ]);

      setResultsByMode({
        public_transport: publicTransport,
        motorbike,
        car,
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const comparisonData = useMemo(() => {
    if (!resultsByMode.public_transport || !resultsByMode.motorbike || !resultsByMode.car) {
      return null;
    }

    const monthlyTrips = Number(tripsPerWeek) * WEEKS_PER_MONTH;

    const pt = resultsByMode.public_transport;
    const mb = resultsByMode.motorbike;
    const car = resultsByMode.car;

    const evDistanceKm = mb.distance_km || 0;
    const evFarePerTrip = evDistanceKm * (EV_KWH_PER_100KM / 100) * ELECTRICITY_PRICE_VND_PER_KWH;
    const evMonthlyElectricity = evFarePerTrip * monthlyTrips;
    const evMonthlyVehiclePayment = Number(evPrice) / 12;
    const evMonthlyTotal = evMonthlyElectricity + evMonthlyVehiclePayment;

    const motorbikeMonthlyFuel = (mb.fare_vnd || 0) * monthlyTrips;
    const monthlySavingVsMotorbike = motorbikeMonthlyFuel - evMonthlyElectricity;

    const evRecommendation = monthlySavingVsMotorbike > 0
      ? `EV outplays motorbike in about ${(Number(evPrice) / monthlySavingVsMotorbike).toFixed(1)} months (fuel + electricity comparison).`
      : 'No break-even with current route and prices.';

    return [
      {
        method: 'Public transport',
        timeMins: pt.duration_mins,
        farePerTrip: pt.fare_vnd,
        monthlyCost: (pt.fare_vnd || 0) * monthlyTrips,
        recommendation: ' ',
      },
      {
        method: 'Motorbike',
        timeMins: mb.duration_mins,
        farePerTrip: mb.fare_vnd,
        monthlyCost: (mb.fare_vnd || 0) * monthlyTrips,
        recommendation: ' ',
      },
      {
        method: 'Car',
        timeMins: car.duration_mins,
        farePerTrip: car.fare_vnd,
        monthlyCost: (car.fare_vnd || 0) * monthlyTrips,
        recommendation: ' ',
      },
      {
        method: 'EV',
        timeMins: mb.duration_mins,
        farePerTrip: evFarePerTrip,
        monthlyCost: evMonthlyTotal,
        recommendation: evRecommendation,
      },
    ];
  }, [resultsByMode, tripsPerWeek, evPrice]);

  const getMethodLabel = (method) => {
    if (!compactTable) return method;
    if (method === 'Public transport') return 'PT';
    if (method === 'Motorbike') return 'MB';
    return method;
  };

  return (
    <div className="h-full w-full flex bg-[#f1f3f4] text-[#202124]">
      <aside
        className={`${
          compactPanel ? 'w-full md:w-[300px] lg:w-[320px]' : 'w-full md:w-[430px] lg:w-[460px]'
        } bg-white border-r border-[#dadce0] p-4 overflow-y-auto shadow-[0_1px_3px_rgba(60,64,67,0.3),0_4px_8px_3px_rgba(60,64,67,0.15)] z-[1000] transition-all duration-200`}
      >
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <Navigation className="w-5 h-5 text-[#1a73e8]" />
            <h1 className="text-[20px] font-semibold tracking-tight">Route Options</h1>
          </div>
          <button
            type="button"
            onClick={() => setCompactPanel((prev) => !prev)}
            className="text-[11px] text-[#1a73e8] border border-[#d2e3fc] bg-[#e8f0fe] rounded-full px-2 py-1 whitespace-nowrap"
          >
            {compactPanel ? 'Expand panel' : 'Compact panel'}
          </button>
        </div>

        <p className="text-xs text-[#5f6368] mb-4">
          Choose Search places or Coordinates, then click Calculate.
        </p>

        <div className="mb-4">
          <div className="flex border-b border-[#dadce0]">
            <button
              type="button"
              onClick={() => setInputMode('search')}
              className={`flex-1 py-2 text-sm font-medium border-b-2 transition ${
                inputMode === 'search'
                  ? 'text-[#1a73e8] border-[#1a73e8]'
                  : 'text-[#5f6368] border-transparent'
              }`}
            >
              Search places
            </button>

            <button
              type="button"
              onClick={() => setInputMode('coordinates')}
              className={`flex-1 py-2 text-sm font-medium border-b-2 transition ${
                inputMode === 'coordinates'
                  ? 'text-[#1a73e8] border-[#1a73e8]'
                  : 'text-[#5f6368] border-transparent'
              }`}
            >
              Coordinates
            </button>
          </div>
        </div>

        <div className="space-y-3 text-sm">
          {inputMode === 'search' ? (
            <>
              <div className="relative">
                <label className="block text-[#5f6368] mb-1">
                  Search Origin
                </label>

                <input
                  type="text"
                  value={startSearch}
                  onChange={(e) => {
                    setStartSearch(e.target.value);
                    setStartSuggestions([]);
                  }}
                  placeholder="Search starting point"
                  className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
                />

                {startSearchLoading && (
                  <div className="text-[11px] text-[#5f6368] mt-1">
                    Searching...
                  </div>
                )}

                {startSuggestions.length > 0 && (
                  <ul className="absolute left-0 right-0 top-[66px] bg-white border border-[#dadce0] rounded-lg shadow-md max-h-40 overflow-auto z-[1200]">
                    {startSuggestions.map((item) => (
                      <li
                        key={item.place_id}
                        onMouseDown={() => pickStartSuggestion(item)}
                        className="px-3 py-2 text-xs hover:bg-[#f1f3f4] cursor-pointer"
                      >
                        {item.description}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="relative">
                <label className="block text-[#5f6368] mb-1">
                  Search Destination
                </label>

                <input
                  type="text"
                  value={endSearch}
                  onChange={(e) => {
                    setEndSearch(e.target.value);
                    setEndSuggestions([]);
                  }}
                  placeholder="Search destination"
                  className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
                />

                {endSearchLoading && (
                  <div className="text-[11px] text-[#5f6368] mt-1">
                    Searching...
                  </div>
                )}

                {endSuggestions.length > 0 && (
                  <ul className="absolute left-0 right-0 top-[66px] bg-white border border-[#dadce0] rounded-lg shadow-md max-h-40 overflow-auto z-[1200]">
                    {endSuggestions.map((item) => (
                      <li
                        key={item.place_id}
                        onMouseDown={() => pickEndSuggestion(item)}
                        className="px-3 py-2 text-xs hover:bg-[#f1f3f4] cursor-pointer"
                      >
                        {item.description}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[#5f6368] mb-1">
                    Origin Lat
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={startPos[0]}
                    onChange={(e) => updateStartCoord(0, e.target.value)}
                    className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
                  />
                </div>

                <div>
                  <label className="block text-[#5f6368] mb-1">
                    Origin Lon
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={startPos[1]}
                    onChange={(e) => updateStartCoord(1, e.target.value)}
                    className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[#5f6368] mb-1">
                    Destination Lat
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={endPos[0]}
                    onChange={(e) => updateEndCoord(0, e.target.value)}
                    className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
                  />
                </div>

                <div>
                  <label className="block text-[#5f6368] mb-1">
                    Destination Lon
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={endPos[1]}
                    onChange={(e) => updateEndCoord(1, e.target.value)}
                    className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
                  />
                </div>
              </div>
            </>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[#5f6368] mb-1">Trips / Week</label>
              <input
                type="number"
                min="1"
                value={tripsPerWeek}
                onChange={(e) => setTripsPerWeek(Number(e.target.value) || 1)}
                className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
              />
            </div>
            <div>
              <label className="block text-[#5f6368] mb-1">EV Price (VND)</label>
              <input
                type="number"
                min="0"
                value={evPrice}
                onChange={(e) => setEvPrice(Number(e.target.value) || 0)}
                className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
              />
            </div>
          </div>

          <div>
            <label className="block text-[#5f6368] mb-1">Route displayed on map</label>
            <select
              value={routeMode}
              onChange={(e) => setRouteMode(e.target.value)}
              className="w-full border border-[#dadce0] rounded-lg p-2.5 outline-none focus:border-[#1a73e8]"
            >
              <option value="public_transport">Public transport</option>
              <option value="motorbike">Motorbike</option>
              <option value="car">Car</option>
            </select>
          </div>

          <button
            onClick={handleCalculate}
            disabled={loading}
            className="w-full bg-[#1a73e8] hover:bg-[#185abc] text-white font-medium py-2.5 rounded-xl transition disabled:opacity-50"
          >
            {loading ? 'Calculating...' : 'Calculate'}
          </button>

          {error && (
            <div className="p-3 bg-red-50 text-red-700 text-xs rounded-lg border border-red-200">
              {error}
            </div>
          )}
        </div>

        <div className="mt-5">
          <div className="flex items-center justify-between mb-2 gap-2">
            <h2 className="text-sm font-semibold text-[#3c4043]">Comparison Table</h2>
            <button
              type="button"
              onClick={() => setCompactTable((prev) => !prev)}
              className="text-[11px] text-[#1a73e8] border border-[#d2e3fc] bg-[#e8f0fe] rounded-full px-2 py-1"
            >
              {compactTable ? 'Normal table' : 'Compact table'}
            </button>
          </div>
          <div className="overflow-auto border border-[#e8eaed] rounded-xl">
            <table className={`w-full ${compactTable ? 'text-[11px]' : 'text-xs'}`}>
              <thead className="bg-[#f8f9fa] text-[#5f6368]">
                <tr>
                  <th className={`text-left ${compactTable ? 'p-1.5' : 'p-2'}`}>Method</th>
                  <th className={`text-left ${compactTable ? 'p-1.5' : 'p-2'}`}>Time</th>
                  <th className={`text-left ${compactTable ? 'p-1.5' : 'p-2'}`}>Fare</th>
                  <th className={`text-left ${compactTable ? 'p-1.5' : 'p-2'}`}>Monthly</th>
                  {!compactTable && <th className="text-left p-2">Recommendation</th>}
                </tr>
              </thead>
              <tbody>
                {comparisonData ? (
                  comparisonData.map((row) => (
                    <tr key={row.method} className="border-t border-[#f1f3f4] align-top">
                      <td className={`${compactTable ? 'p-1.5' : 'p-2'} font-medium`}>{getMethodLabel(row.method)}</td>
                      <td className={compactTable ? 'p-1.5' : 'p-2'}>{Number(row.timeMins).toFixed(1)} min</td>
                      <td className={compactTable ? 'p-1.5' : 'p-2'}>{Math.round(row.farePerTrip || 0).toLocaleString()} VND</td>
                      <td className={compactTable ? 'p-1.5' : 'p-2'}>{Math.round(row.monthlyCost || 0).toLocaleString()} VND</td>
                      {!compactTable && <td className="p-2 text-[#5f6368]">{row.recommendation}</td>}
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={compactTable ? 4 : 5} className="p-3 text-[#5f6368]">
                      No data yet. Click Calculate.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="mt-4 border border-[#e8eaed] rounded-xl p-3 bg-[#f8f9fa]">
          <h3 className="text-xs font-semibold text-[#3c4043] mb-1">Recommendation</h3>
          <p className="text-xs text-[#5f6368]">
            {comparisonData ? comparisonData.find((row) => row.method === 'EV')?.recommendation : ' '}
          </p>
        </div>

        {activeRoute && (
          <div className="mt-4 border-t border-[#e8eaed] pt-3">
            <h3 className="text-sm font-semibold text-[#3c4043] mb-2">Route Steps ({routeMode.replace('_', ' ')})</h3>
            {Array.isArray(activeRoute.steps) && activeRoute.steps.length > 0 ? (
              <ol className="space-y-1 text-xs text-[#3c4043] list-decimal list-inside">
                {activeRoute.steps.map((step, idx) => {
                  if (step.type === 'TRANSIT') {
                    return (
                      <li key={`transit-${idx}`}>
                        Take {step.vehicle || 'TRANSIT'} line {step.line || 'N/A'} from {step.from_stop || 'Unknown stop'} to {step.to_stop || 'Unknown stop'} ({step.num_stops || 0} stops)
                      </li>
                    );
                  }

                  if (step.type === 'WALKING') {
                    return <li key={`walk-${idx}`}>Walk {step.distance_m || 0} m</li>;
                  }

                  if (step.type === 'DRIVING' || step.type === 'TWO_WHEELER') {
                    return (
                      <li key={`route-${idx}`}>
                        {stripHtml(step.instructions) || 'Continue on route'}
                      </li>
                    );
                  }

                  return (
                    <li key={`route-${idx}`}>
                      {step.type || 'ROUTE'}: {stripHtml(step.instructions) || 'Continue on route'}
                    </li>
                  );
                })}
              </ol>
            ) : (
              <div className="text-xs text-[#5f6368]">No route steps available.</div>
            )}
          </div>
        )}
      </aside>

      <section className="flex-1 relative">
        <MapContainer center={INITIAL_START} zoom={13} className="h-full w-full" zoomControl>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          <Marker icon={startMarkerIcon} draggable eventHandlers={startHandlers} position={startPos} ref={startMarkerRef}>
            <Popup>Origin</Popup>
          </Marker>

          <Marker icon={endMarkerIcon} draggable eventHandlers={endHandlers} position={endPos} ref={endMarkerRef}>
            <Popup>Destination</Popup>
          </Marker>

          {routeCoordinates.length > 0 && (
            <>
              <Polyline positions={routeCoordinates} color="#1a73e8" weight={6} opacity={0.9} />
              <MapUpdater bounds={routeCoordinates} />
            </>
          )}
        </MapContainer>
      </section>
    </div>
  );
}
