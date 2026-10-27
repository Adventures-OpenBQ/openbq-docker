// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
// SPDX-License-Identifier: BUSL-1.1
/**
 * The snapshot renderer's page (spec §5, S11): one chart card, the real one,
 * opened on `?chart_id=` exactly as a BDOBB card on that document opens --
 * through `chartsFetch` and the step 1b sync. Every request it makes is
 * same-origin; the server's headless Chromium answers each one from the
 * arts-charts app in-process, so the page reaches nothing else.
 *
 * Query: chart_id, symbol and interval (so the first render is already the
 * document's instrument), theme (`dark` | `light`).
 */
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ArtsChartsRenderer, configureArtsCharts, type ArtsChartsHost, type WidgetDef } from "../src";
import "../src/arts-charts.css";
import "../../dev/tokens.css";

const page = new URLSearchParams(location.search);
const theme = page.get("theme") === "light" ? "light" : "dark";
const query = (params: Record<string, string>) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "")).toString();
const nothing = async () => { throw new Error("the snapshot page has no files"); };

const host: ArtsChartsHost = {
  async fetchWidgetPath(_backend, path, params) {
    const response = await fetch(`/${path}?${query(params)}`);
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    return response.json();
  },
  buildWidgetWsUrl(_backend, widget, params = {}) {
    if (!widget.wsEndpoint) return null;
    return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/${widget.wsEndpoint}?${query(params)}`;
  },
  chartsFetch: (path, init) => fetch(path, init),
  fs: {
    exists: async () => false, readTextFile: nothing, writeTextFile: async () => {}, readDir: async () => [],
    rename: async () => {}, remove: async () => {}, mkdir: async () => {}, stat: async () => ({ size: 0 }),
  },
  dialog: { open: async () => null, confirm: async () => false },
  saveTextFile: async () => false,
  saveBinaryFile: async () => false,
  openUrl: async () => {},
  log: (level, message) => { (level === "error" ? console.error : console.info)(message); },
  useResolvedTheme: () => theme,
  groups: { createGroup: async () => null, joinGroup: async () => {}, dropUngroupable: async () => {} },
  components: { DatetimePicker: () => null, RelativeTab: () => null, AnchorChips: () => null, GroupLink: () => null },
};
configureArtsCharts(host);
document.documentElement.dataset.theme = theme;

const backend = { id: "arts-charts", name: "Art's Charts", baseUrl: location.origin };
const widget: WidgetDef = {
  id: "arts_charts", wsEndpoint: "ta_series_ws",
  params: [
    { paramName: "symbol", label: "Symbol", type: "text" },
    { paramName: "interval", label: "Interval", type: "text" },
  ],
};

function Snapshot() {
  const [params, setParams] = useState<Record<string, string>>({
    chart_id: page.get("chart_id") ?? "", symbol: page.get("symbol") ?? "", interval: page.get("interval") ?? "",
  });
  const [state, setState] = useState({});
  return (
    <div style={{ height: "100vh" }}>
      <ArtsChartsRenderer
        backend={backend} widget={widget} params={params} state={state}
        onPatch={(patch) => setState((s) => ({ ...s, ...patch }))}
        onParam={(patch) => setParams((p) => ({ ...p, ...patch }))}
        onClear={() => {}} refreshKey={0}
      />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Snapshot />);
