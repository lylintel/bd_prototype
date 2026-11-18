import { chromium } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const argument = (name, fallback) => { const index = process.argv.indexOf(name); return index < 0 ? fallback : process.argv[index + 1]; };
const sizes = argument("--sizes", "100,500,2000").split(",").map(Number);
const samples = Number(argument("--samples", "3"));
const ceiling = Number(argument("--ceiling", "20000"));
const output = path.resolve(argument("--report", "build/phase4-performance"));
const venv = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.BD_PYTHON || (existsSync(venv) ? venv : "python");
if (sizes.some((size) => ![100, 500, 2000].includes(size)) || !Number.isInteger(samples) || samples < 1 || samples > 11 || !Number.isFinite(ceiling) || ceiling < 1000) throw new Error("Invalid benchmark arguments");
mkdirSync(output, { recursive: true });

async function deadline(operation, timeout, phase) {
  let timer;
  try {
    return await Promise.race([operation, new Promise((_, reject) => {
      timer = setTimeout(() => { const error = new Error(`${phase}_deadline`); error.name = "TimeoutError"; reject(error); }, timeout);
    })]);
  } finally { clearTimeout(timer); }
}

function killTree(child) {
  if (!child?.pid || child.exitCode !== null) return;
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore", timeout: 10000 });
  else { try { process.kill(child.pid, "SIGKILL"); } catch {} }
}

async function serverFor(directory) {
  const child = spawn(python, ["-u", "-m", "bdgui", "--workspace", directory, "--design", "design.json", "--port", "0"], {
    cwd: root, stdio: ["ignore", "pipe", "pipe"], detached: process.platform !== "win32",
  });
  const exited = new Promise((resolve) => child.once("close", resolve));
  const stop = async () => {
    if (child.exitCode === null) {
      if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      else process.kill(-child.pid, "SIGTERM");
    }
    await exited;
  };
  try {
    const url = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("server_start_timeout")), 60000);
      let text = "";
      child.stdout.on("data", (chunk) => { text += chunk; const found = text.match(/BD Studio: (http:\/\/127\.0\.0\.1:\d+)/); if (found) { clearTimeout(timer); resolve(found[1]); } });
      child.once("error", (error) => { clearTimeout(timer); reject(error); });
      child.once("exit", (code) => { clearTimeout(timer); reject(new Error(`server_exit_${code}`)); });
      child.stderr.on("data", () => {});
    });
    return { url, stop };
  } catch (error) { await stop(); throw error; }
}

async function frames(page, action) {
  await page.evaluate(() => {
    const capture = { active: true, started: performance.now(), samples: [] };
    window.__bdFrames = capture;
    function tick(now) { if (capture.active) { capture.samples.push(now); requestAnimationFrame(tick); } }
    requestAnimationFrame(tick);
  });
  await action();
  return page.evaluate(() => {
    const capture = window.__bdFrames;
    capture.active = false;
    const elapsed = performance.now() - capture.started;
    return { fps: capture.samples.length * 1000 / elapsed, duration_ms: elapsed, frames: capture.samples.length };
  });
}

async function measure(directory, size, sample) {
  console.log(JSON.stringify({ instances: size, sample, phase: "server_start" }));
  const server = await serverFor(directory);
  console.log(JSON.stringify({ instances: size, sample, phase: "browser_start" }));
  const browser = await chromium.launch({ headless: true });
  const control = await browser.newBrowserCDPSession();
  const processes = await control.send("SystemInfo.getProcessInfo");
  const browserPid = processes.processInfo.find((process) => process.type === "browser").id;
  await control.detach();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.setDefaultTimeout(ceiling);
  await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
  await page.addInitScript(() => {
    window.__bdLongTasks = [];
    new PerformanceObserver((entries) => { window.__bdLongTasks.push(...entries.getEntries().map((entry) => entry.duration)); }).observe({ type: "longtask", buffered: true });
  });
  const result = { instances: size, nets: size * 3 + 1, sample, status: "unavailable", load_ms: null, pan: null, zoom: null, drag: null, selection_ms: null, drag_rendered_nodes: null, chromium: browser.version() };
  const started = performance.now();
  try {
    result.phase = "load";
    await deadline((async () => {
      await page.goto(`${server.url}/?perf=1`, { waitUntil: "domcontentloaded", timeout: ceiling });
      await page.locator('[aria-label="校验设计"].valid').waitFor();
      await page.locator('.react-flow__node[data-id="unit_0"] .block-heading').waitFor();
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    })(), ceiling, "load");
    result.load_ms = performance.now() - started;
    result.status = "loaded";
    const pane = await deadline(page.locator(".react-flow__pane").boundingBox(), ceiling, "pane");
    const start = { x: pane.x + 25, y: pane.y + pane.height * 0.6 };
    result.phase = "pan";
    result.pan = await deadline(frames(page, async () => {
      await page.mouse.move(start.x, start.y); await page.mouse.down();
      const until = performance.now() + 1500;
      let step = 0;
      while (performance.now() < until) { await page.mouse.move(start.x + (step++ % 2 ? 60 : 0), start.y + 12); }
      await page.mouse.up();
    }), ceiling, "pan");
    result.phase = "zoom";
    result.zoom = await deadline(frames(page, async () => {
      await page.mouse.move(pane.x + pane.width / 2, pane.y + pane.height / 2);
      const until = performance.now() + 1500;
      let step = 0;
      while (performance.now() < until) await page.mouse.wheel(0, step++ % 2 ? 20 : -20);
    }), ceiling, "zoom");
    const header = page.locator('.react-flow__node[data-id="unit_0"] .block-heading');
    result.phase = "drag";
    const bounds = await deadline(header.boundingBox(), ceiling, "header");
    const before = await deadline(page.evaluate(() => ({ ...window.__bdPerformance.node })), ceiling, "counters");
    result.drag = await deadline(frames(page, async () => {
      await page.mouse.move(bounds.x + 50, bounds.y + 12); await page.mouse.down();
      const until = performance.now() + 1500;
      let step = 0;
      while (performance.now() < until) await page.mouse.move(bounds.x + 50 + (step++ % 2 ? 60 : 20), bounds.y + 24);
      await page.mouse.up();
    }), ceiling, "drag");
    result.drag_rendered_nodes = await deadline(page.evaluate((previous) => Object.entries(window.__bdPerformance.node).filter(([identifier, count]) => count > (previous[identifier] ?? 0)).length, before), ceiling, "counters");
    result.phase = "selection";
    const selectedAt = performance.now();
    await page.locator('.react-flow__node[data-id="unit_1"] .block-heading').click();
    await page.locator('.react-flow__node[data-id="unit_1"] .block-node.is-selected').waitFor();
    result.selection_ms = performance.now() - selectedAt;
    result.max_long_task_ms = await deadline(page.evaluate(() => Math.max(0, ...window.__bdLongTasks)), ceiling, "long_tasks");
    await page.screenshot({ path: path.join(output, `${size}-${sample}.png`), timeout: ceiling });
    result.status = "measured";
  } catch (error) {
    result.status = result.load_ms === null ? error.name === "TimeoutError" ? "load_timeout" : "load_failed" : "interaction_failed";
    result.failure = error.name;
    result.browser_errors = errors;
    result.elapsed_ms = performance.now() - started;
    result.load_lower_bound_ms = result.status === "load_timeout" ? ceiling : undefined;
    try {
      result.visible_text = (await deadline(page.locator("body").innerText({ timeout: 1000 }), 1000, "snapshot_text")).slice(0, 1200);
      await deadline(page.screenshot({ path: path.join(output, `${size}-${sample}-failure.png`), timeout: 1000 }), 1500, "snapshot");
    } catch { result.failure_snapshot = "unavailable"; }
  } finally {
    killTree({ pid: browserPid, exitCode: null });
    await deadline(browser.close(), 5000, "browser_cleanup").catch(() => {});
    await server.stop();
  }
  const budget = size === 2000 ? { load: 4000, pan: 30, drag: 20 } : { load: 2000, pan: 45, drag: 30 };
  result.budget_passed = result.status === "measured" && result.load_ms < budget.load && Math.min(result.pan.fps, result.zoom.fps) >= budget.pan && result.drag.fps >= budget.drag;
  return result;
}

const report = { schema_version: 1, created: new Date().toISOString(), viewport: { width: 1440, height: 900 }, seed: 20261117,
  machine: { platform: os.platform(), release: os.release(), cpu: os.cpus()[0].model, cores: os.cpus().length, node: process.version },
  source_sha256: createHash("sha256").update(readFileSync(path.join(root, "web/src/App.jsx"))).update(readFileSync(path.join(root, "web/src/CircuitEdge.jsx"))).digest("hex"),
  benchmark_sha256: createHash("sha256").update(readFileSync(fileURLToPath(import.meta.url))).digest("hex"),
  methodology: "Navigation to validated interactive first node; RAF cadence during real pointer/wheel input; fresh browser per sample; no external requests; timeouts are not FPS measurements", results: [] };
for (const size of sizes) {
  const directory = mkdtempSync(path.join(os.tmpdir(), "bd-gui-benchmark-"));
  try {
    const generated = spawnSync(python, ["-m", "scripts.gui_benchmark", "--output", directory, "--instances", String(size)], { cwd: root, encoding: "utf8", timeout: 60000 });
    if (generated.status !== 0) throw new Error(`fixture_generation_failed: ${generated.stderr}`);
    for (let sample = 1; sample <= samples; sample++) {
      const result = await measure(directory, size, sample);
      report.results.push(result);
      writeFileSync(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n");
      console.log(JSON.stringify(result));
    }
  } finally { rmSync(directory, { recursive: true, force: true }); }
}
const value = (number) => number == null ? "not measured" : number.toFixed(2);
const lines = ["# Browser Performance", "", report.methodology, "", "| Instances | Sample | Status | Load ms | Pan fps | Zoom fps | Drag fps | Selection ms | Drag node renders | Budget |", "|---:|---:|---|---:|---:|---:|---:|---:|---:|---|"];
lines.push(...report.results.map((item) => `| ${item.instances} | ${item.sample} | ${item.status} | ${value(item.load_ms)} | ${value(item.pan?.fps)} | ${value(item.zoom?.fps)} | ${value(item.drag?.fps)} | ${value(item.selection_ms)} | ${item.drag_rendered_nodes ?? "not measured"} | ${item.budget_passed} |`));
writeFileSync(path.join(output, "report.md"), lines.join("\n") + "\n");
if (process.argv.includes("--strict") && report.results.some((result) => !result.budget_passed)) process.exitCode = 1;