import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { reorderScreen, resizeItem, type LayoutBox, type ScreenName } from "./lib/layout";
import { useLayout } from "./layout-context";

export function LayoutBlocks({ screen, blocks }: { screen: ScreenName; blocks: Record<string, ReactNode> }) {
  const ctx = useLayout();
  const items = ctx?.layout?.screens[screen];
  if (!items) {
    return <>{Object.values(blocks)}</>;
  }
  if (!ctx?.editing) {
    return (
      <div className="layout-flow">
        {items.map((item) =>
          blocks[item.id] ? (
            <div key={item.id} data-component={item.id}>
              {blocks[item.id]}
            </div>
          ) : null,
        )}
      </div>
    );
  }
  return (
    <div className="layout-grid" data-screen={screen}>
      {items.map((item) => (
        <article
          key={item.id}
          className="layout-card"
          data-component={item.id}
          style={{ gridColumn: `${item.col} / span ${item.w}`, gridRow: `${item.row} / span ${item.h}` }}
        >
          <header
            className="layout-handle"
            onPointerDown={(event) => startReorder(event, items, item.id, (next) => ctx.setScreen(screen, next))}
          >
            {item.id}
          </header>
          <div className="layout-body">{blocks[item.id]}</div>
          <button
            type="button"
            className="layout-resize"
            aria-label={`Resize ${item.id}`}
            onPointerDown={(event) => startResize(event, items, item, (next) => ctx.setScreen(screen, next))}
          />
        </article>
      ))}
    </div>
  );
}

function startReorder(
  event: ReactPointerEvent<HTMLElement>,
  items: LayoutBox[],
  id: string,
  commit: (next: LayoutBox[]) => void,
) {
  if (event.button !== 0) return;
  event.preventDefault();
  let target = id;
  const move = (ev: PointerEvent) => {
    const hit = document.elementFromPoint(ev.clientX, ev.clientY);
    const card = hit instanceof Element ? hit.closest("[data-component]") : null;
    const next = card?.getAttribute("data-component");
    if (next) target = next;
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    if (target !== id) commit(reorderScreen(items, id, target));
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function startResize(
  event: ReactPointerEvent<HTMLButtonElement>,
  items: LayoutBox[],
  item: LayoutBox,
  commit: (next: LayoutBox[]) => void,
) {
  event.preventDefault();
  event.stopPropagation();
  const startX = event.clientX;
  const startY = event.clientY;
  const startW = item.w;
  const startH = item.h;
  const move = (ev: PointerEvent) => {
    const dw = Math.round((ev.clientX - startX) / 48);
    const dh = Math.round((ev.clientY - startY) / 36);
    commit(resizeItem(items, item.id, startW + dw, startH + dh));
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
