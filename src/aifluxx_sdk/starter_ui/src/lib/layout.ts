/** Canonical Starter UI layout.

Keep this in lockstep with ``aifluxx_sdk/layout.py``. The packer walks rows
from the top and takes the leftmost column that fits. Array order is the
user's order; coordinates are assigned. JSON key order is part of the format.
*/

export const LAYOUT_SCHEMA = "aifluxx/layout/v1";
export const SCREENS = ["Run", "Status", "Tools", "Settings"] as const;
export type ScreenName = (typeof SCREENS)[number];

export const SCREEN_COMPONENTS: Record<ScreenName, readonly string[]> = {
  Run: ["agent-picker", "prompt", "run-action", "output", "history"],
  Status: ["refresh", "agents", "logs"],
  Tools: ["read-tools", "write-tools", "connectors"],
  Settings: ["connection", "keys", "mcp"],
};

const DEFAULT_SIZE: Record<string, [number, number]> = {
  "agent-picker": [12, 2],
  prompt: [12, 3],
  "run-action": [12, 1],
  output: [12, 6],
  history: [12, 4],
  refresh: [12, 1],
  agents: [12, 5],
  logs: [12, 6],
  "read-tools": [12, 3],
  "write-tools": [12, 3],
  connectors: [12, 3],
  connection: [12, 4],
  keys: [12, 5],
  mcp: [12, 4],
};

const GRID_COLUMNS = 12;
const MIN_W = 1;
const MAX_W = 12;
const MIN_H = 1;
const MAX_H = 8;

export interface LayoutBox {
  id: string;
  col: number;
  row: number;
  w: number;
  h: number;
}

export interface Layout {
  schema: string;
  screens: Record<ScreenName, LayoutBox[]>;
}

interface LooseBox {
  id?: unknown;
  w?: unknown;
  h?: unknown;
}

function clamp(value: unknown, low: number, high: number, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || !Number.isInteger(value)) return fallback;
  return Math.min(high, Math.max(low, value));
}

function normalizeRows(screen: ScreenName, raw: unknown): { id: string; w: number; h: number }[] {
  const known = SCREEN_COMPONENTS[screen];
  const seen = new Set<string>();
  const ordered: { id: string; w: number; h: number }[] = [];
  if (Array.isArray(raw)) {
    for (const row of raw as LooseBox[]) {
      if (!row || typeof row !== "object") continue;
      const id = row.id;
      if (typeof id !== "string" || !known.includes(id) || seen.has(id)) continue;
      seen.add(id);
      const [dw, dh] = DEFAULT_SIZE[id];
      ordered.push({ id, w: clamp(row.w, MIN_W, MAX_W, dw), h: clamp(row.h, MIN_H, MAX_H, dh) });
    }
  }
  for (const id of known) {
    if (seen.has(id)) continue;
    const [w, h] = DEFAULT_SIZE[id];
    ordered.push({ id, w, h });
  }
  return ordered;
}

/** First fitting row, then the leftmost column. Same rules as layout.py. */
export function packItems(items: { id: string; w: number; h: number }[]): LayoutBox[] {
  const occupancy = new Map<number, number>();
  const fits = (row: number, col: number, width: number, height: number) => {
    if (col < 1 || col + width - 1 > GRID_COLUMNS) return false;
    for (let y = row; y < row + height; y += 1) {
      const mask = occupancy.get(y) ?? 0;
      for (let x = col; x < col + width; x += 1) {
        if (mask & (1 << (x - 1))) return false;
      }
    }
    return true;
  };
  const occupy = (row: number, col: number, width: number, height: number) => {
    for (let y = row; y < row + height; y += 1) {
      let mask = occupancy.get(y) ?? 0;
      for (let x = col; x < col + width; x += 1) mask |= 1 << (x - 1);
      occupancy.set(y, mask);
    }
  };
  const placed: LayoutBox[] = [];
  for (const item of items) {
    let found: [number, number] | null = null;
    for (let row = 1; row < 241 && !found; row += 1) {
      for (let col = 1; col <= GRID_COLUMNS; col += 1) {
        if (fits(row, col, item.w, item.h)) {
          found = [col, row];
          break;
        }
      }
    }
    if (!found) throw new Error(`No grid cell fits ${item.id}.`);
    const [col, row] = found;
    occupy(row, col, item.w, item.h);
    placed.push({ id: item.id, col, row, w: item.w, h: item.h });
  }
  return placed;
}

export function canonicalize(layout: { screens?: Partial<Record<ScreenName, LooseBox[]>> } | null | undefined): Layout {
  const incoming = layout && typeof layout === "object" ? layout.screens : undefined;
  const screens = {} as Record<ScreenName, LayoutBox[]>;
  for (const screen of SCREENS) {
    const raw = incoming && typeof incoming === "object" ? incoming[screen] : undefined;
    screens[screen] = packItems(normalizeRows(screen, raw));
  }
  return { schema: LAYOUT_SCHEMA, screens };
}

export function defaultLayout(): Layout {
  const screens = {} as Record<ScreenName, { id: string; w: number; h: number }[]>;
  for (const screen of SCREENS) {
    screens[screen] = SCREEN_COMPONENTS[screen].map((id) => {
      const [w, h] = DEFAULT_SIZE[id];
      return { id, w, h };
    });
  }
  return canonicalize({ screens });
}

function box(item: LayoutBox) {
  return { id: item.id, col: item.col, row: item.row, w: item.w, h: item.h };
}

/** Canonical JSON, including the trailing newline. */
export function serializeLayout(layout: Layout | null | undefined): string {
  const canon = canonicalize(layout);
  const payload = {
    schema: LAYOUT_SCHEMA,
    screens: {
      Run: canon.screens.Run.map(box),
      Status: canon.screens.Status.map(box),
      Tools: canon.screens.Tools.map(box),
      Settings: canon.screens.Settings.map(box),
    },
  };
  return `${JSON.stringify(payload, null, 2)}\n`;
}

export function reorderScreen(items: LayoutBox[], fromId: string, toId: string): LayoutBox[] {
  const from = items.findIndex((item) => item.id === fromId);
  const to = items.findIndex((item) => item.id === toId);
  if (from < 0 || to < 0 || from === to) return items;
  const next = items.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return packItems(next.map((item) => ({ id: item.id, w: item.w, h: item.h })));
}

export function resizeItem(items: LayoutBox[], id: string, w: number, h: number): LayoutBox[] {
  const next = items.map((item) =>
    item.id === id
      ? { id: item.id, w: clamp(w, MIN_W, MAX_W, item.w), h: clamp(h, MIN_H, MAX_H, item.h) }
      : { id: item.id, w: item.w, h: item.h },
  );
  return packItems(next);
}
