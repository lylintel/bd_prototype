import os from "node:os";

export function assessLoad(before, after, free, total) {
  const elapsed = after.total - before.total;
  const cpu = elapsed > 0 ? 100 * (1 - (after.idle - before.idle) / elapsed) : null;
  const minimum = Math.max(1024 ** 3, total * 0.1);
  return { cpu_percent: cpu, free_bytes: free, total_bytes: total,
    limits: { cpu_percent: 50, minimum_free_bytes: minimum },
    qualified: Number.isFinite(cpu) && cpu >= 0 && cpu <= 50 && free >= minimum };
}

export async function sampleLoad() {
  const ticks = () => os.cpus().reduce((sum, cpu) => ({ idle: sum.idle + cpu.times.idle,
    total: sum.total + Object.values(cpu.times).reduce((total, value) => total + value, 0) }), { idle: 0, total: 0 });
  const before = ticks(), started = performance.now();
  await new Promise((resolve) => setTimeout(resolve, 1000));
  return { ...assessLoad(before, ticks(), os.freemem(), os.totalmem()), sample_ms: performance.now() - started,
    at: new Date().toISOString() };
}