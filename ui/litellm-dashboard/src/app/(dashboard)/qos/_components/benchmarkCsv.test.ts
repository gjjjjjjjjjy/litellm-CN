import Papa from "papaparse";
import { describe, expect, it } from "vitest";

import { benchmarkCsv, benchmarkCsvFileName, localDateTime, type BenchmarkExport } from "./benchmarkCsv";

const percentiles = (p50: number | null) => ({ p50, p95: p50 === null ? null : p50 * 2, p99: null });

const level = (model_id: string, concurrency: number, requests: number, failed_requests: number) => ({
  model_group: "qwen3-max",
  model_id,
  model: "Qwen3-Max",
  api_base: `https://${model_id}/v1`,
  vendor: "moark",
  concurrency,
  requests,
  failed_requests,
  streamed_requests: requests,
  output_tokens: 1200,
  peak_concurrency: concurrency,
  first_request_at: "2026-10-23T01:00:00Z",
  last_response_at: "2026-10-23T01:00:10Z",
  requests_per_second: 1.23456,
  output_tokens_per_second: 98.765,
  ttft_ms: percentiles(312.345),
  tpot_ms: percentiles(null),
  e2e_latency_ms: percentiles(1500),
  response_checks: { checked: requests, crosstalk: 1, marker_missing: 2 },
  interference: { same_deployment: 3, same_endpoint: 4 },
});

const exported = (run_id: string, started_at: string, model_group: string, levels: ReturnType<typeof level>[]) => ({
  run: {
    run_id,
    model_group,
    requests: 0,
    failed_requests: 0,
    crosstalk_responses: 0,
    started_at,
    last_response_at: started_at,
  },
  detail: { run_id, levels: [], deployments: [], deployment_levels: levels },
});

const parse = (csv: string): Record<string, string>[] => Papa.parse<Record<string, string>>(csv, { header: true }).data;

describe("benchmark CSV", () => {
  it("writes one row per run, concurrency level and node, oldest run first", () => {
    const exports: BenchmarkExport[] = [
      exported("run-new", "2026-10-23T02:00:00Z", "qwen3-max", [level("node-a", 1, 4, 0)]),
      exported("run-old", "2026-10-22T02:00:00Z", "glm-5", [level("node-a", 1, 4, 1), level("node-b", 8, 16, 0)]),
    ];

    const rows = parse(benchmarkCsv(exports));

    expect(rows.map((row) => [row["Run ID"], row["Node ID"], row.Concurrency])).toEqual([
      ["run-old", "node-a", "1"],
      ["run-old", "node-b", "8"],
      ["run-new", "node-a", "1"],
    ]);
    expect(rows[0].Model).toBe("glm-5");
    expect(rows[0].Started).toBe(localDateTime(new Date("2026-10-22T02:00:00Z")));
  });

  it("keeps the measured numbers and leaves missing percentiles empty", () => {
    const [row] = parse(benchmarkCsv([exported("run", "2026-10-23T02:00:00Z", "m", [level("node-a", 4, 8, 2)])]));

    const expected = {
      "Failed Requests": "2",
      "Success rate (%)": "75",
      "Requests per second": "1.23",
      "Output tokens/s": "98.77",
      "TTFT P50 (ms)": "312.3",
      "TTFT P95 (ms)": "624.7",
      "TTFT P99 (ms)": "",
      "TPOT P50 (ms)": "",
      "Latency P50 (ms)": "1500",
      "Responses checked": "8",
      "Cross-talk responses": "1",
      "Responses missing their code": "2",
      "Other traffic on this deployment": "3",
      "Other traffic on its endpoint": "4",
      "API Base": "https://node-a/v1",
      "Upstream model": "Qwen3-Max",
    };

    expect(row).toMatchObject(expected);
  });

  it("leaves the success rate empty for a level without requests", () => {
    const [row] = parse(benchmarkCsv([exported("run", "2026-10-23T02:00:00Z", "m", [level("node-a", 1, 0, 0)])]));

    expect(row["Success rate (%)"]).toBe("");
  });

  it("stops spreadsheet formulas in model names from running", () => {
    const [row] = parse(benchmarkCsv([exported("run", "2026-10-23T02:00:00Z", "=HYPERLINK()", [level("n", 1, 1, 0)])]));

    expect(row.Model).toBe("'=HYPERLINK()");
  });

  it("names the file after the local export time", () => {
    expect(benchmarkCsvFileName(new Date(2026, 9, 26, 9, 5, 7))).toBe("qos_benchmarks_2026-10-26_090507.csv");
  });
});
