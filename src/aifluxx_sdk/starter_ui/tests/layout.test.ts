import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { createApp } from "../server/app";
import { canonicalize, defaultLayout, reorderScreen, resizeItem, serializeLayout } from "../src/lib/layout";

const mock = { mock: true, apiRoot: "https://api.example", apiKey: null, keySource: null } as const;

describe("layout serialization", () => {
  it("matches the Python default fixture", () => {
    expect(serializeLayout(defaultLayout())).toBe(readFileSync("tests/fixtures/default-layout.json", "utf8"));
  });

  it("matches the Python side-by-side fixture", () => {
    const layout = defaultLayout();
    const screens = {
      ...layout.screens,
      Run: layout.screens.Run.map((item) =>
        item.id === "agent-picker" || item.id === "prompt" ? { id: item.id, w: 6, h: item.h } : { id: item.id, w: item.w, h: item.h },
      ),
    };
    expect(serializeLayout(canonicalize({ screens }))).toBe(readFileSync("tests/fixtures/resized-layout.json", "utf8"));
  });

  it("reorders and resizes with the same packer", () => {
    const run = defaultLayout().screens.Run;
    const moved = reorderScreen(run, "history", "agent-picker");
    expect(moved[0]?.id).toBe("history");
    expect(moved[0]?.col).toBe(1);
    expect(moved[0]?.row).toBe(1);
    const sized = resizeItem(run, "prompt", 6, 3);
    const prompt = sized.find((item) => item.id === "prompt");
    expect(prompt).toMatchObject({ col: 1, row: 3, w: 6, h: 3 });
  });
});

describe("layout file", () => {
  it("saves canonical JSON inside the project and does not echo a key", async () => {
    const dir = mkdtempSync(join(tmpdir(), "aifluxx-layout-"));
    const app = createApp({
      config: { ...mock, apiKey: "afx_dev_testkey_abcd" },
      projectDir: dir,
    });
    const empty = await (await app.request("/local/layout")).json();
    expect(empty.exists).toBe(false);
    expect(empty.path).toBe(join(dir, "aifluxx.layout.json"));
    const saved = await app.request("/local/layout", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        screens: {
          Run: [
            { id: "prompt", w: 6, h: 3 },
            { id: "agent-picker", w: 6, h: 2 },
          ],
        },
      }),
    });
    expect(saved.status).toBe(200);
    const text = readFileSync(join(dir, "aifluxx.layout.json"), "utf8");
    expect(text).toBe(serializeLayout(canonicalize(JSON.parse(text))));
    expect(text).not.toContain("testkey");
    const body = await saved.json();
    expect(body.layout.screens.Run.map((item: { id: string }) => item.id)[0]).toBe("prompt");
    expect(body.layout.screens.Run.map((item: { id: string }) => item.id)[1]).toBe("agent-picker");
  });
});
