import { useCallback, useEffect, useState } from "react";
import { ApiError, devPath, request } from "./lib/api";
import { RunConsole } from "./screens/RunConsole";
import { Status } from "./screens/Status";
import { Tools } from "./screens/Tools";
import { Settings } from "./screens/Settings";
import { LayoutProvider } from "./layout-context";
import { canonicalize, type Layout, type ScreenName } from "./lib/layout";
import type { Agent, LocalConfig, RunRecord } from "./types";

interface LayoutResponse {
  path: string;
  layout: Layout;
  editing?: boolean;
  exists?: boolean;
}

const TABS = ["Run", "Status", "Tools", "Settings"] as const;

export function App() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Run");
  const [cfg, setCfg] = useState<LocalConfig | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentsErr, setAgentsErr] = useState<RunRecord["error"] | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [layoutEditing, setLayoutEditing] = useState(() => new URLSearchParams(window.location.search).get("layout") === "1");
  const [layoutNote, setLayoutNote] = useState<string | null>(null);

  const setScreen = useCallback((screen: ScreenName, items: Layout["screens"][ScreenName]) => {
    setLayout((current) => {
      if (!current) return current;
      return canonicalize({ ...current, screens: { ...current.screens, [screen]: items } });
    });
    setLayoutNote(null);
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      const data = await request<Agent[] | { agents: Agent[] }>("GET", devPath("/agents"));
      setAgents(Array.isArray(data) ? data : data.agents ?? []);
      setAgentsErr(null);
    } catch (e) {
      if (e instanceof ApiError) setAgentsErr({ status: e.status, method: e.method, url: e.url, body: e.body, hint: e.hint });
    }
  }, []);

  useEffect(() => {
    request<LocalConfig>("GET", "/local/config").then(setCfg).catch(() => setCfg(null));
    request<LayoutResponse>("GET", "/local/layout")
      .then((res) => {
        setLayout(res.layout);
        if (res.editing) setLayoutEditing(true);
      })
      .catch(() => setLayout(null));
    loadAgents();
  }, [loadAgents]);

  async function saveLayout() {
    if (!layout) return;
    try {
      const saved = await request<LayoutResponse>("PUT", "/local/layout", layout);
      setLayout(saved.layout);
      setLayoutNote(`Saved ${saved.path}`);
    } catch (e) {
      setLayoutNote(e instanceof Error ? e.message : "Could not save the layout.");
    }
  }

  const onRun = (r: RunRecord) => setRuns((prev) => [r, ...prev.filter((p) => p.id !== r.id)]);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <img src="/brand/aifluxx-horizontal-dark.svg" alt="AIFluxx" />
          <span>Starter Console</span>
        </div>
        <nav>
          <p className="nav-group">Console</p>
          {TABS.map((t) => <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}
        </nav>
        <footer>AIFluxx Starter Console v1.1.0 · Questions: <a href="mailto:developer@aifluxx.com">developer@aifluxx.com</a></footer>
      </aside>
      <div className="content">
        <header className="topbar">
          <span>Starter Console</span><span className="sep">/</span><span className="here">{tab}</span>
          <button
            type="button"
            className={layoutEditing ? "layout-toggle on" : "layout-toggle"}
            aria-pressed={layoutEditing}
            onClick={() => setLayoutEditing((on) => !on)}
          >
            Layout edit
          </button>
          {layoutEditing && (
            <button type="button" className="layout-save" onClick={saveLayout} disabled={!layout}>
              Save layout
            </button>
          )}
          {cfg?.mock && <span className="mock">MOCK</span>}
        </header>
        {layoutNote && <p className="layout-note">{layoutNote}</p>}
        <main>
          {!cfg && <div className="error">Local proxy not reachable. Start it with <code>npm run dev</code>.</div>}
          <LayoutProvider value={{ layout, editing: layoutEditing, setScreen }}>
            {tab === "Run" && <RunConsole agents={agents} runs={runs} onRun={onRun} mock={!!cfg?.mock} />}
            {tab === "Status" && <Status agents={agents} runs={runs} error={agentsErr} reload={loadAgents} />}
            {tab === "Tools" && <Tools />}
            {tab === "Settings" && cfg && <Settings cfg={cfg} />}
          </LayoutProvider>
        </main>
      </div>
    </div>
  );
}
