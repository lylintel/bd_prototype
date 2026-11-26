import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { sampleLoad } from "./benchmark-load.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export function assessPair(pair) {
  const signal = pair.browser?.signal, grouped = pair.browser?.interface;
  const metrics = {};
  const add = (name, control, candidate, inverse = false) => {
    const available = Number.isFinite(control) && control > 0 && Number.isFinite(candidate) && candidate > 0;
    const ratio = available ? inverse ? control / candidate : candidate / control : null;
    metrics[name] = { signal: control ?? null, interface: candidate ?? null, ratio, overhead_percent: ratio === null ? null : (ratio - 1) * 100,
      passed: ratio !== null && ratio <= 1.1 };
  };
  for (const name of ["parse_ms", "inspect_ms", "generate_ms"]) add(name, pair.backend?.metrics?.[name]?.signal, pair.backend?.metrics?.[name]?.interface);
  add("load_ms", signal?.load_ms, grouped?.load_ms);
  add("cold_start_ms", signal?.cold_start?.total_ms, grouped?.cold_start?.total_ms);
  for (const phase of ["pan", "zoom", "drag"]) add(`${phase}_frame_time`, signal?.[phase]?.fps, grouped?.[phase]?.fps, true);
  add("selection_ms", signal?.selection_ms, grouped?.selection_ms);
  const qualified = pair.backend_preflight?.qualified === true && pair.backend_postflight?.qualified === true &&
    [signal, grouped].every((sample) => sample?.measurement_qualified === true && sample.preflight?.qualified === true && sample.postflight?.qualified === true);
  const complete = pair.backend?.physical_equivalence === true && pair.backend?.hdl_equivalence_except_schema_header === true &&
    [signal, grouped].every((sample) => sample?.status === "measured") && signal.chromium === grouped.chromium && signal.instances === grouped.instances;
  const overheadPassed = Object.values(metrics).every((item) => item.passed);
  return { qualified, complete, overhead_passed: overheadPassed, passed: qualified && complete && overheadPassed, metrics };
}

export function summarizePairs(results, instances = 2000) {
  return { required_pairs: 3, recorded_pairs: results.length, qualified_pairs: results.filter((item) => item.assessment.qualified && item.assessment.complete).length,
    accepted: instances === 2000 && results.length === 3 && results.every((item) => item.assessment.passed) };
}

async function run(command, args, label) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
    let output = "", errors = "", failure = null;
    const stop = () => {
      if (child.exitCode !== null || !child.pid) return;
      if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore", timeout: 10000 });
      else child.kill("SIGKILL");
    };
    const timer = setTimeout(() => { failure = new Error(`${label}: 300s deadline`); stop(); }, 300000);
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
      if (output.length > 4 * 1024 * 1024) { failure = new Error(`${label}: output limit`); stop(); }
      process.stdout.write(".");
    });
    child.stderr.on("data", (chunk) => { errors = (errors + chunk.toString()).slice(-8000); process.stderr.write(chunk); });
    child.once("error", (error) => { clearTimeout(timer); reject(error); });
    child.once("close", (code) => {
      clearTimeout(timer);
      if (failure || code !== 0) reject(failure ?? new Error(`${label}: exit ${code}: ${errors}`));
      else resolve(output);
    });
  });
}

function saveReport(directory, report) {
  Object.assign(report, summarizePairs(report.results, report.instances));
  writeFileSync(path.join(directory, "report.json"), JSON.stringify(report, null, 2) + "\n");
  const lines = ["# AXI-Stream Paired Performance", "", report.methodology, "",
    `Accepted: ${report.accepted}; qualified pairs: ${report.qualified_pairs}/3.`, "",
    "| Pair | Qualified | Metric | Signal | Interface | Overhead % | <=10% |", "|---:|---|---|---:|---:|---:|---|"];
  const value = (number) => Number.isFinite(number) ? number.toFixed(3) : "not measured";
  for (const pair of report.results) for (const [name, metric] of Object.entries(pair.assessment.metrics)) {
    lines.push(`| ${pair.sample} | ${pair.assessment.qualified} | ${name} | ${value(metric.signal)} | ${value(metric.interface)} | ${value(metric.overhead_percent)} | ${metric.passed} |`);
  }
  lines.push("", "Frame-time overhead is signal FPS / interface FPS - 1; raw FPS is retained. Missing or unqualified measurements cannot pass. Full raw backend sequences, memory, request bytes, load samples and browser reports are retained in JSON and subdirectories.");
  writeFileSync(path.join(directory, "report.md"), lines.join("\n") + "\n");
}

async function main() {
  const argument = (name, fallback) => { const index = process.argv.indexOf(name); return index < 0 ? fallback : process.argv[index + 1]; };
  const count = Number(argument("--instances", "2000")), samples = Number(argument("--samples", "3"));
  if (![100, 500, 2000].includes(count) || !Number.isInteger(samples) || samples < 1 || samples > 3) throw new Error("Invalid paired benchmark arguments");
  const output = path.resolve(argument("--report", "build/phase2b-paired-performance"));
  if (existsSync(path.join(output, "report.json"))) throw new Error("Report exists; use a new output directory to retain previous evidence");
  mkdirSync(output, { recursive: true });
  const venv = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const python = process.env.BD_PYTHON || (existsSync(venv) ? venv : "python");
  const fixture = path.join(output, "fixtures");
  const generated = await run(python, ["-m", "scripts.interface_benchmark", "--output", fixture, "--instances", String(count)], "fixtures");
  const report = { schema_version: 1, suite: "axis-interface-pair", created: new Date().toISOString(), instances: count,
    fixture: JSON.parse(generated), threshold_ratio: 1.1, viewport: { width: 1440, height: 900 },
    machine: { platform: os.platform(), release: os.release(), cpu: os.cpus()[0].model, cores: os.cpus().length, node: process.version },
    source_sha256: createHash("sha256").update(["core/interfaces.py", "core/generation.py", "core/design.py", "core/hierarchy.py", "bdgui.py", "bdsemantic.py", "web/src/App.jsx", "web/src/semantic/interfaces.js", "web/src/CircuitEdge.jsx"]
      .map((file) => readFileSync(path.join(root, file))).reduce((combined, bytes) => Buffer.concat([combined, bytes]), Buffer.alloc(0))).digest("hex"),
    methodology: "Three same-machine same-run electrically equivalent pairs, alternating which representation runs first. Backend phases use one warmup and three interleaved repetitions. Browser reuses the unchanged performance runner with fresh backend/browser and CPU/memory pre/postflight. Gate: each cost ratio <=1.10; no absolute milliseconds/FPS gate. Raw request bytes and derived-net memory are reported, not substituted for timings. OS caches are not flushed. No real model or external network calls.", results: [] };
  for (let sample = 1; sample <= samples; sample++) {
    const first = sample % 2 ? "signal" : "interface";
    const pair = { sample, first, backend: null, browser: {}, failures: [] };
    pair.backend_preflight = await sampleLoad();
    console.log(JSON.stringify({ sample, phase: "backend_preflight", ...pair.backend_preflight }));
    if (pair.backend_preflight.qualified) {
      try {
        pair.backend = JSON.parse(await run(python, ["-m", "scripts.interface_benchmark", "--measure", "--output", fixture, "--first", first], "backend"));
      } catch (error) { pair.failures.push(error.message); }
      pair.backend_postflight = await sampleLoad();
    }
    for (const variant of [first, first === "signal" ? "interface" : "signal"]) {
      const destination = path.join(output, `pair-${sample}-${variant}`);
      try {
        await run(process.execPath, ["web/e2e/performance.mjs", "--sizes", String(count), "--samples", "1", "--fixture", path.join(fixture, variant), "--report", destination], `browser-${variant}`);
        const browserReport = JSON.parse(readFileSync(path.join(destination, "report.json"), "utf8"));
        pair.browser[variant] = browserReport.results[0];
        if (pair.browser[variant].instances !== count || pair.browser[variant].top_level_instances !== count && pair.browser[variant].status === "measured") throw new Error("Browser fixture size mismatch");
      } catch (error) { pair.failures.push(error.message); }
    }
    pair.assessment = assessPair(pair);
    report.results.push(pair);
    saveReport(output, report);
    console.log(JSON.stringify({ sample, assessment: pair.assessment, failures: pair.failures }));
  }
  console.log(JSON.stringify({ report: output, ...summarizePairs(report.results, count), acceptance_size: count === 2000 }));
  if (process.argv.includes("--strict") && (!report.accepted || count !== 2000)) process.exitCode = 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();