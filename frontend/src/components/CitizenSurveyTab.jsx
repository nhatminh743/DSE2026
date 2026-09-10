import { useEffect, useState } from 'react';
import { SURVEY_FIELDS } from '../surveyFields';
import { firebaseAuthorizedFetch } from '../firebaseApi';
import { API_BASE } from '../staticConfig';

const QUESTION_FIELDS = SURVEY_FIELDS.filter((field) => !field.location);

function LocationPicker({ label, latName, lonName, form, errors, onChange }) {
  const [mode, setMode] = useState('search');
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState('');

  const search = async () => {
    if (query.trim().length < 2) { setSearchError('Enter at least two characters'); return; }
    setLoading(true);
    setSearchError('');
    try {
      const response = await fetch(`${API_BASE}/api/maps/autocomplete?input=${encodeURIComponent(query.trim())}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Location search failed');
      setSuggestions(payload.suggestions || []);
    } catch (requestError) {
      setSearchError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  const choose = async (suggestion) => {
    setLoading(true);
    setSearchError('');
    try {
      const response = await fetch(`${API_BASE}/api/maps/place-details?place_id=${encodeURIComponent(suggestion.place_id)}`);
      const place = await response.json();
      if (!response.ok) throw new Error(place.detail || 'Could not load coordinates');
      onChange(latName, String(place.lat));
      onChange(lonName, String(place.lng));
      setQuery(place.address || suggestion.description);
      setSuggestions([]);
    } catch (requestError) {
      setSearchError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  return <fieldset className="rounded-xl border border-gray-200 p-4"><legend className="px-1 text-sm font-semibold">{label}</legend><div className="mb-3 flex gap-2"><button type="button" onClick={() => setMode('search')} className={`rounded-lg px-3 py-1.5 text-sm ${mode === 'search' ? 'bg-[#e8f0fe] text-[#1a73e8]' : 'border border-gray-300 text-gray-600'}`}>Search location</button><button type="button" onClick={() => setMode('coordinates')} className={`rounded-lg px-3 py-1.5 text-sm ${mode === 'coordinates' ? 'bg-[#e8f0fe] text-[#1a73e8]' : 'border border-gray-300 text-gray-600'}`}>Enter coordinates</button></div>
    {mode === 'search' ? <div><div className="flex gap-2"><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); search(); } }} placeholder={`Search ${label.toLowerCase()}`} className="min-w-0 flex-1 rounded-lg border border-gray-300 p-2.5 text-sm" /><button type="button" onClick={search} disabled={loading} className="rounded-lg bg-[#1a73e8] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{loading ? 'Searching...' : 'Search'}</button></div>{suggestions.length > 0 && <div className="mt-2 overflow-hidden rounded-lg border border-gray-200">{suggestions.map((item) => <button key={item.place_id} type="button" onClick={() => choose(item)} className="block w-full border-b border-gray-100 px-3 py-2 text-left text-sm last:border-0 hover:bg-gray-50">{item.description}</button>)}</div>}</div> : <div className="grid grid-cols-2 gap-3"><label className="text-sm"><span className="mb-1 block text-gray-500">Latitude (Vietnam: 8–24)</span><input type="number" min="8" max="24" step="any" value={form[latName] || ''} onChange={(event) => onChange(latName, event.target.value)} className="w-full rounded-lg border border-gray-300 p-2.5" /></label><label className="text-sm"><span className="mb-1 block text-gray-500">Longitude (Vietnam: 102–110)</span><input type="number" min="102" max="110" step="any" value={form[lonName] || ''} onChange={(event) => onChange(lonName, event.target.value)} className="w-full rounded-lg border border-gray-300 p-2.5" /></label></div>}
    {(form[latName] || form[lonName]) && <div className="mt-2 text-xs text-gray-500">Selected coordinates: {form[latName] || '—'}, {form[lonName] || '—'}</div>}{(searchError || errors[latName] || errors[lonName]) && <div className="mt-2 text-xs text-red-600">{searchError || errors[latName] || errors[lonName]}</div>}
  </fieldset>;
}

function validate(form) {
  const errors = {};
  for (const field of SURVEY_FIELDS) {
    const value = form[field.name];
    if (field.required && (value === undefined || value === '')) errors[field.name] = 'This field is required';
    if (value !== undefined && value !== '' && field.options && !field.options.some((item) => item.value === value)) errors[field.name] = 'Select one of the available options';
    if (value !== undefined && value !== '' && field.type === 'number') {
      const number = Number(value);
      if (!Number.isFinite(number)) errors[field.name] = 'Enter a valid number';
      else if ((field.min !== undefined && number < field.min) || (field.max !== undefined && number > field.max)) errors[field.name] = `Enter a value from ${field.min} to ${field.max}`;
    }
  }
  return errors;
}

export default function CitizenSurveyTab({ auth }) {
  const [form, setForm] = useState({});
  const [errors, setErrors] = useState({});
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [responses, setResponses] = useState([]);
  const [responsesLoading, setResponsesLoading] = useState(Boolean(auth?.session_token));
  const [responsesError, setResponsesError] = useState('');
  const token = auth?.session_token;

  useEffect(() => {
    if (!token) return undefined;
    const controller = new AbortController();
    firebaseAuthorizedFetch(`${API_BASE}/api/survey/responses/mine`, { signal: controller.signal })
      .then(async (response) => { const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || 'Could not load your responses'); return payload; })
      .then((payload) => setResponses(payload.responses || []))
      .catch((requestError) => { if (requestError.name !== 'AbortError') setResponsesError(requestError.message); })
      .finally(() => { if (!controller.signal.aborted) setResponsesLoading(false); });
    return () => controller.abort();
  }, [token]);

  const updateField = (name, value) => { setForm((previous) => ({ ...previous, [name]: value })); setErrors((previous) => ({ ...previous, [name]: undefined })); };
  const refreshResponses = async () => { if (!token) return; const response = await firebaseAuthorizedFetch(`${API_BASE}/api/survey/responses/mine`); const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || 'Could not load your responses'); setResponses(payload.responses || []); };

  const submitSurvey = async (event) => {
    event.preventDefault();
    if (!token) { setStatus('Sign in with Google before submitting a response.'); return; }
    const validationErrors = validate(form);
    if (Object.keys(validationErrors).length) { setErrors(validationErrors); setStatus('Check the highlighted fields before submitting.'); return; }
    setStatus(''); setLoading(true);
    try {
      const payload = { ...form };
      const alternatives = [['alt_car', 'car'], ['alt_ebike', 'ebike'], ['alt_bike', 'bike'], ['alt_bus', 'bus'], ['alt_ltrain', 'lighttrain'], ['alt_taxi', 'taxi'], ['alt_walk', 'walk']].filter(([field]) => form[field] === '1').map(([, mode]) => mode);
      if (alternatives.length) payload.alt_veh = alternatives.join(' ');
      const response = await firebaseAuthorizedFetch(`${API_BASE}/api/survey/responses`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ payload }) });
      const result = await response.json();
      if (!response.ok) { if (result.detail?.errors) setErrors(result.detail.errors); throw new Error(typeof result.detail === 'string' ? result.detail : result.detail?.message || 'Submission failed'); }
      setStatus(`Thank you. Your response was submitted (ID: ${result.id}).`); setForm({}); setErrors({}); await refreshResponses();
    } catch (requestError) { setStatus(`Error: ${requestError.message}`); } finally { setLoading(false); }
  };

  const deleteResponse = async (responseId) => {
    if (!token || !window.confirm(`Delete survey response ${responseId}? This cannot be undone.`)) return;
    setResponsesError('');
    try { const response = await firebaseAuthorizedFetch(`${API_BASE}/api/survey/responses/${responseId}`, { method: 'DELETE' }); const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || 'Could not delete response'); setResponses((current) => current.filter((item) => item.id !== responseId)); } catch (requestError) { setResponsesError(requestError.message); }
  };

  const filledCount = Object.values(form).filter((value) => value !== '').length;
  return <div className="h-full overflow-y-auto p-4 sm:p-8"><div className="mx-auto max-w-4xl space-y-6"><section className="rounded-2xl border border-[#e8eaed] bg-white p-5 sm:p-8"><h1 className="text-2xl font-semibold">Hanoi Mobility Survey</h1><p className="mb-6 mt-2 text-sm text-[#5f6368]">Select values from the same categories and bins used by the baseline survey. Required fields and numeric limits are checked before submission.</p>
    {!auth?.user && <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">Sign in with Google in the header to submit, view, or delete your survey responses.</div>}{auth?.user && <div className="mb-6 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">Submitting as {auth.user.email}</div>}
    <div className="mb-6"><div className="mb-2 flex justify-between text-xs"><span className="font-medium text-gray-500">Completed fields</span><span className="font-medium text-[#1a73e8]">{filledCount} / {SURVEY_FIELDS.length}</span></div><div className="h-2 rounded-full bg-gray-200"><div className="h-full rounded-full bg-[#1a73e8]" style={{ width: `${Math.round(filledCount / SURVEY_FIELDS.length * 100)}%` }} /></div></div>
    <form onSubmit={submitSurvey} className="space-y-5"><div className="grid grid-cols-1 gap-4 md:grid-cols-2"><LocationPicker label="Origin" latName="origlat" lonName="origlon" form={form} errors={errors} onChange={updateField} /><LocationPicker label="Destination" latName="destlat" lonName="destlon" form={form} errors={errors} onChange={updateField} /></div><div className="grid grid-cols-1 gap-4 md:grid-cols-2">{QUESTION_FIELDS.map((field) => <label key={field.name} className="text-sm"><span className="mb-1.5 block font-medium text-[#5f6368]">{field.label}{field.required && <span className="text-red-600"> *</span>}</span>{field.options ? <select value={form[field.name] || ''} onChange={(event) => updateField(field.name, event.target.value)} className={`w-full rounded-lg border p-2.5 text-sm ${errors[field.name] ? 'border-red-500' : 'border-[#dadce0]'}`}><option value="">Select an option</option>{field.options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select> : <input type={field.type || 'text'} min={field.min} max={field.max} step={field.step} value={form[field.name] || ''} onChange={(event) => updateField(field.name, event.target.value)} className={`w-full rounded-lg border p-2.5 text-sm ${errors[field.name] ? 'border-red-500' : 'border-[#dadce0]'}`} />}{errors[field.name] && <span className="mt-1 block text-xs text-red-600">{errors[field.name]}</span>}</label>)}</div><div className="flex gap-3"><button type="submit" disabled={loading || !token} className="flex-1 rounded-lg bg-[#1a73e8] px-5 py-2.5 font-medium text-white disabled:opacity-50">{loading ? 'Checking and submitting...' : 'Check and submit response'}</button><button type="button" onClick={() => { setForm({}); setErrors({}); setStatus(''); }} className="rounded-lg border border-gray-300 px-5 py-2.5 font-medium text-gray-600">Clear</button></div></form>{status && <div className={`mt-4 rounded-lg p-4 text-sm ${status.startsWith('Thank') ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>{status}</div>}</section>
    <section className="rounded-2xl border border-[#e8eaed] bg-white p-5 sm:p-8"><div className="mb-4 flex items-center justify-between gap-3"><div><h2 className="text-xl font-semibold">Your Survey Responses</h2><p className="mt-1 text-sm text-gray-500">Only responses submitted by this Google account appear here.</p></div>{token && <button type="button" onClick={() => refreshResponses().catch((requestError) => setResponsesError(requestError.message))} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">Refresh</button>}</div>{!token && <p className="text-sm text-gray-500">Sign in to view your responses.</p>}{responsesLoading && <p className="text-sm text-gray-500">Loading your responses...</p>}{responsesError && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{responsesError}</div>}{token && !responsesLoading && responses.length === 0 && <p className="text-sm text-gray-500">You have not submitted any responses yet.</p>}<div className="space-y-3">{responses.map((response) => <article key={response.id} className="rounded-xl border border-gray-200 p-4"><div className="flex justify-between gap-3"><div><div className="font-medium">Response #{response.id}</div><div className="mt-1 text-xs text-gray-500">{new Date(response.created_at).toLocaleString()}</div></div><button type="button" onClick={() => deleteResponse(response.id)} className="rounded-lg border border-red-200 px-3 py-1.5 text-sm text-red-700">Delete</button></div><details className="mt-3"><summary className="cursor-pointer text-sm font-medium text-[#1a73e8]">View submitted fields</summary><dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">{Object.entries(response.payload || {}).map(([key, value]) => <div key={key} className="rounded-lg bg-gray-50 p-2"><dt className="text-xs text-gray-500">{key}</dt><dd>{String(value)}</dd></div>)}</dl></details></article>)}</div></section>
  </div></div>;
}
