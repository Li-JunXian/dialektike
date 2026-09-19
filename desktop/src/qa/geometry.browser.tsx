/// <reference types="@vitest/browser/providers/playwright" />

import { page } from "@vitest/browser/context";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterAll, beforeAll, expect, it } from "vitest";

import { App } from "../App";
import { SIDEBAR_VISIBILITY_STORAGE_KEY } from "../state/sidebarPreference";
import "../styles.css";
import {
  evaluateWorkspaceGeometry,
  geometryAcceptanceViewports,
  measureWorkspaceGeometry,
  type GeometryViewport,
} from "./geometry";

let applicationRoot: ReturnType<typeof createRoot>;

beforeAll(async () => {
  localStorage.removeItem(SIDEBAR_VISIBILITY_STORAGE_KEY);
  document.body.replaceChildren();
  const host = document.createElement("div");
  host.id = "root";
  document.body.append(host);
  applicationRoot = createRoot(host);
  await act(async () => applicationRoot.render(<App />));
  await settleLayout();
});

afterAll(async () => {
  await act(async () => applicationRoot.unmount());
});

it("keeps the real rendered workspace centered across the complete viewport matrix", async () => {
  const viewports = geometryAcceptanceViewports();
  expect(viewports).toHaveLength(164);
  expect(new Set(viewports.map(({ width }) => width))).toHaveLength(162);

  for (const viewport of viewports) {
    await assertRenderedGeometry(viewport, "ordinary");
  }

  addStressContent();
  const scroll = document.querySelector<HTMLElement>(".conversation-scroll");
  expect(scroll, "the stress fixture requires the real conversation scroller").not.toBeNull();
  expect(scroll!.scrollHeight, "the stress fixture must activate the internal scrollbar").toBeGreaterThan(scroll!.clientHeight);

  for (const viewport of viewports) {
    await assertRenderedGeometry(viewport, "long-content");
  }
}, 120_000);

it("does not reset overflow-menu keyboard focus when its parent rerenders", async () => {
  const trigger = document.querySelector<HTMLButtonElement>('.topic-item__menu-button[aria-label^="Actions for"]');
  expect(trigger).not.toBeNull();
  await act(async () => trigger!.click());
  await settleLayout();

  const items = Array.from(document.querySelectorAll<HTMLButtonElement>('.topic-menu [role="menuitem"]'));
  expect(items.length).toBeGreaterThan(1);
  const target = items.at(-1)!;
  target.focus();
  expect(document.activeElement).toBe(target);

  await act(async () => applicationRoot.render(<App />));
  await settleLayout();
  expect(document.activeElement).toBe(target);
});

it("keeps the Context and latest-evidence controls clickable through the composer overlay", async () => {
  const context = document.querySelector<HTMLDetailsElement>(".checkpoint-control");
  const evidence = document.querySelector<HTMLDetailsElement>(".evidence-drawer");
  expect(context).not.toBeNull();
  expect(evidence).not.toBeNull();
  const contextSummary = context!.querySelector("summary");
  const evidenceSummary = evidence!.querySelector("summary");
  expect(contextSummary).not.toBeNull();
  expect(evidenceSummary).not.toBeNull();

  await page.elementLocator(contextSummary!).click();
  await settleLayout();
  expect(context!.open).toBe(true);
  expect(context!.textContent).toContain(
    "Context checkpoints are available in the native Dialektikḗ app.",
  );

  await page.elementLocator(contextSummary!).click();
  await page.elementLocator(evidenceSummary!).click();
  await settleLayout();
  expect(evidence!.open).toBe(true);
  expect(evidence!.textContent).toContain("Bounded, read-only projection");
});

it("keeps the workspace centered and primary controls reachable through sidebar collapse and expansion", async () => {
  await page.viewport(1180, 820);
  await settleLayout();

  const shell = document.querySelector<HTMLElement>(".app-shell");
  const sidebar = document.querySelector<HTMLElement>(".topic-sidebar");
  const collapse = document.querySelector<HTMLButtonElement>('[aria-label="Collapse topic sidebar"]');
  expect(shell).not.toBeNull();
  expect(sidebar).not.toBeNull();
  expect(collapse).not.toBeNull();
  const expandedWidth = sidebar!.getBoundingClientRect().width;

  await page.elementLocator(collapse!).click();
  await settleLayout();

  expect(shell!.dataset.sidebarCollapsed).toBe("true");
  expect(sidebar!.getBoundingClientRect().width).toBeLessThanOrEqual(62.5);
  expect(localStorage.getItem(SIDEBAR_VISIBILITY_STORAGE_KEY)).toBe("collapsed");
  expect(evaluateWorkspaceGeometry(measureWorkspaceGeometry(document)).passed).toBe(true);

  const newTopic = document.querySelector<HTMLButtonElement>('.topic-sidebar [aria-label="New topic"]');
  const appearance = document.querySelector<HTMLSelectElement>('.topic-sidebar [aria-label="Appearance"]');
  const expand = document.querySelector<HTMLButtonElement>('[aria-label="Expand topic sidebar"]');
  expect(newTopic?.getBoundingClientRect().width).toBeGreaterThanOrEqual(40);
  expect(appearance).not.toBeNull();
  appearance!.focus();
  expect(document.activeElement).toBe(appearance);
  expect(expand).not.toBeNull();

  await page.elementLocator(expand!).click();
  await settleLayout();

  expect(shell!.dataset.sidebarCollapsed).toBe("false");
  expect(Math.abs(sidebar!.getBoundingClientRect().width - expandedWidth)).toBeLessThanOrEqual(1);
  expect(localStorage.getItem(SIDEBAR_VISIBILITY_STORAGE_KEY)).toBe("expanded");
  expect(evaluateWorkspaceGeometry(measureWorkspaceGeometry(document)).passed).toBe(true);
});

async function assertRenderedGeometry(viewport: GeometryViewport, phase: string) {
  await page.viewport(viewport.width, viewport.height);
  await settleLayout();
  const measurement = measureWorkspaceGeometry(document);
  const evaluation = evaluateWorkspaceGeometry(measurement);
  if (!evaluation.passed) {
    await page.screenshot({
      path: `geometry-${phase}-${viewport.width}x${viewport.height}.png`,
    });
  }
  expect(
    evaluation,
    `${phase} ${viewport.width}x${viewport.height}: ${JSON.stringify(measurement)}`,
  ).toMatchObject({
    passed: true,
    horizontalOverflow: 0,
  });
}

function addStressContent() {
  const content = document.querySelector<HTMLElement>(".model-markdown");
  if (!content) throw new Error("Geometry stress fixture could not find rendered model content.");

  const code = document.createElement("pre");
  code.textContent = `const unbroken = "${"x".repeat(2_000)}";`;

  const table = document.createElement("table");
  const row = document.createElement("tr");
  for (let index = 0; index < 12; index += 1) {
    const cell = document.createElement("td");
    cell.textContent = `Wide column ${index + 1} ${"datum".repeat(12)}`;
    row.append(cell);
  }
  table.append(row);

  const citation = document.createElement("a");
  citation.href = "https://example.com/";
  citation.textContent = `Citation ${"reference".repeat(80)}`;

  const height = document.createElement("div");
  height.style.height = "2200px";
  height.textContent = "Tall response fixture";

  content.append(code, table, citation, height);
}

async function settleLayout() {
  await document.fonts.ready;
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
}
