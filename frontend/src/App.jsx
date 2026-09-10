import { useCallback, useState } from 'react';
import PolicyDashboard from './components/PolicyDashboard';
import OsmStationTab from './components/OsmStationTab';
import CitizenSurveyTab from './components/CitizenSurveyTab';
import KMedianTab from './components/KMedianTab';
import ModelLabTab from './components/ModelLabTab';
import { RouteCalculatorTab } from './components/RouteCalculatorTab';
import GoogleLogin from './components/GoogleLogin';
import './App.css';

const TABS = [
  { id: 'policy', label: 'Policy Dashboard' },
  { id: 'osm', label: 'District Map' },
  { id: 'models', label: 'Model Lab' },
  { id: 'survey', label: 'Citizen Survey' },
  { id: 'kmedian', label: 'K-Median Model' },
  { id: 'route', label: 'Route Calculator' },
];

export default function App() {
  const [activeTab, setActiveTab] = useState('policy');
  const [auth, setAuth] = useState(null);
  const updateAuth = useCallback((session) => setAuth(session), []);

  return <div className="flex h-dvh min-h-dvh w-full min-w-0 flex-col overflow-x-hidden bg-[#f1f3f4] text-[#202124]">
    <header className="shrink-0 border-b border-[#dadce0] bg-white shadow-sm"><div className="flex min-w-0 flex-col gap-2 px-3 py-2 sm:flex-row sm:items-center sm:gap-4 sm:px-5"><div className="shrink-0 text-lg font-semibold text-[#1a73e8]">Hanoi Mobility Policy Lab</div><nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" aria-label="Application tabs">{TABS.map((tab) => <button key={tab.id} type="button" onClick={() => setActiveTab(tab.id)} className={`shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium ${activeTab === tab.id ? 'bg-[#e8f0fe] text-[#1a73e8]' : 'text-[#5f6368] hover:bg-[#f1f3f4]'}`}>{tab.label}</button>)}</nav><GoogleLogin auth={auth} onAuthChange={updateAuth} /></div></header>
    <main className="min-h-0 min-w-0 flex-1 overflow-auto sm:overflow-hidden">{activeTab === 'policy' && <PolicyDashboard />}{activeTab === 'osm' && <OsmStationTab />}{activeTab === 'models' && <ModelLabTab />}{activeTab === 'survey' && <CitizenSurveyTab auth={auth} />}{activeTab === 'kmedian' && <KMedianTab />}{activeTab === 'route' && <RouteCalculatorTab />}</main>
  </div>;
}
