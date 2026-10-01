import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

interface Status { stage: string; runtime: string; features: { phase: string; title: string; state: string; detail: string }[] }
function App() {
  const [status, setStatus] = useState<Status>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState('M1');
  async function refresh() {
    setBusy(true); setError('');
    try { const response = await fetch('/api/status'); if (!response.ok) throw new Error(`API returned ${response.status}`); setStatus(await response.json() as Status); }
    catch (e) { setError(e instanceof Error ? e.message : 'API unavailable'); }
    finally { setBusy(false); }
  }
  useEffect(() => { void refresh(); }, []);
  const active = status?.features.find(item => item.phase === phase);
  return <div className="shell">
    <aside><div className="brand"><span className="mark" aria-hidden="true">af</span><strong>Agent Factory</strong></div><p className="aside-note">Department research workspace</p><nav aria-label="Implementation phases">{['M1','M2','M3','M4'].map((id, i) => <button key={id} aria-current={phase === id ? 'page' : undefined} onClick={() => setPhase(id)}><span>{id}</span>{['Foundation','Factory core','Auto-Research','Acceptance'][i]}</button>)}</nav><div className="aside-bottom">Public source · MIT license<br/>Full feature delivery in stages</div></aside>
    <main><header><span>Project initialization</span><span className="state">Local development</span></header><div className="content"><h1>A foundation for<br/>departmental research.</h1><p className="intro">Reusable agents. Scoped connections. Research with evidence. The development environment is the first acceptance checkpoint.</p>
      <section className="health" aria-label="Development environment"><div><span className={`dot ${error ? 'error' : ''}`}/><strong>{busy ? 'Checking local API…' : error ? 'Local API unavailable' : status ? 'Local API connected' : 'Waiting for local API'}</strong><p>{error ? `${error}. Start the API, then try again.` : `${status?.runtime ?? 'Node runtime'} · Model calls disabled`}</p></div><button className="secondary" disabled={busy} onClick={() => void refresh()}>Check again</button></section>
      <section className="phase" aria-labelledby="phase-title"><div className="phase-caption">{phase} acceptance checkpoint <span>{active?.state ?? 'Loading'}</span></div><h2 id="phase-title">{active?.title ?? phase}</h2><p>{active?.detail ?? 'Connect the local API to view this checkpoint.'}</p>{phase === 'M1' ? <div className="commands"><div><span>Verify environment</span><code>npm run check</code></div><div><span>Build and start</span><code>npm run build<br/>npm start</code></div><div><span>Frontend development</span><code>npm run dev:web</code></div></div> : <p className="planned">This checkpoint is planned. Its features are recorded in the acceptance matrix and are not enabled in this initialization build.</p>}</section>
      <footer><span>20 users is a capacity target, not 20 concurrent workers.</span><span>Proposed worker limit: 2</span></footer>
    </div></main>
  </div>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
