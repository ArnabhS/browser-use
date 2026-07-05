// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";

import { collectInteractables } from "./collector";

// jsdom/happy-dom do no layout, so getBoundingClientRect returns zeros — stub per element.
function stubRect(el: Element, r: { left: number; top: number; width: number; height: number }): void {
  (el as any).getBoundingClientRect = () => ({
    x: r.left,
    y: r.top,
    left: r.left,
    top: r.top,
    right: r.left + r.width,
    bottom: r.top + r.height,
    width: r.width,
    height: r.height,
    toJSON() {},
  });
}

beforeEach(() => {
  (window as any).innerWidth = 1000;
  (window as any).innerHeight = 800;
  document.body.innerHTML = "";
});

describe("collectInteractables", () => {
  it("collects visible interactables with role, name, and centered coords", () => {
    document.body.innerHTML = `
      <button id="b">Search</button>
      <a id="a" href="/x">Home</a>
      <input id="i" type="text" placeholder="Query" />
      <div id="d">not interactive</div>
    `;
    stubRect(document.getElementById("b")!, { left: 10, top: 20, width: 100, height: 40 });
    stubRect(document.getElementById("a")!, { left: 0, top: 100, width: 50, height: 20 });
    stubRect(document.getElementById("i")!, { left: 200, top: 300, width: 300, height: 30 });

    const snap = collectInteractables(document, window);

    expect(snap.items.map((it) => it.role)).toEqual(["button", "link", "textbox"]);
    expect(snap.items[0].name).toBe("Search");
    expect(snap.items[2].name).toBe("Query"); // placeholder used as the name
    expect(snap.items[0]).toMatchObject({ centerX: 60, centerY: 40 }); // (10+100/2, 20+40/2)
    expect(snap.viewport).toMatchObject({ width: 1000, height: 800 });
  });

  it("drops zero-size and off-screen elements", () => {
    document.body.innerHTML = `
      <button id="z">Zero</button>
      <button id="off">Off</button>
      <button id="ok">Ok</button>`;
    stubRect(document.getElementById("z")!, { left: 0, top: 0, width: 0, height: 0 });
    stubRect(document.getElementById("off")!, { left: 0, top: 2000, width: 80, height: 30 });
    stubRect(document.getElementById("ok")!, { left: 0, top: 0, width: 80, height: 30 });

    const snap = collectInteractables(document, window);
    expect(snap.items.map((it) => it.name)).toEqual(["Ok"]);
  });

  it("drops display:none elements", () => {
    document.body.innerHTML = `
      <button id="hid" style="display:none">Hidden</button>
      <button id="vis">Visible</button>`;
    stubRect(document.getElementById("hid")!, { left: 0, top: 0, width: 80, height: 30 });
    stubRect(document.getElementById("vis")!, { left: 0, top: 0, width: 80, height: 30 });

    const snap = collectInteractables(document, window);
    expect(snap.items.map((it) => it.name)).toEqual(["Visible"]);
  });

  it("builds a stable 0..N index order matching document order", () => {
    document.body.innerHTML = `<a id="a1" href="/1">One</a><a id="a2" href="/2">Two</a>`;
    stubRect(document.getElementById("a1")!, { left: 0, top: 0, width: 40, height: 20 });
    stubRect(document.getElementById("a2")!, { left: 0, top: 40, width: 40, height: 20 });

    const snap = collectInteractables(document, window);
    expect(snap.items.map((it) => it.name)).toEqual(["One", "Two"]);
  });
});
