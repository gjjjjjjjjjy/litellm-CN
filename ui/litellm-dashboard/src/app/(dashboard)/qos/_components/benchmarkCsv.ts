import Papa from "papaparse";

import { vendorName, type QosBenchmarkDeploymentLevel, type QosBenchmarkDetail, type QosBenchmarkRun } from "./qosData";

export interface BenchmarkExport {
  readonly run: QosBenchmarkRun;
  readonly detail: QosBenchmarkDetail;
}

interface BenchmarkCsvRow {
  readonly run: QosBenchmarkRun;
  readonly level: QosBenchmarkDeploymentLevel;
}

interface CsvColumn {
  readonly label: string;
  readonly value: (row: BenchmarkCsvRow) => string | number;
}

const twoDigits = (value: number): string => String(value).padStart(2, "0");

export const localDateTime = (at: Date): string =>
  `${at.getFullYear()}-${twoDigits(at.getMonth() + 1)}-${twoDigits(at.getDate())} ` +
  `${twoDigits(at.getHours())}:${twoDigits(at.getMinutes())}:${twoDigits(at.getSeconds())}`;

const ms = (value: number | null): string | number => (value === null ? "" : Math.round(value * 10) / 10);

const rate = (value: number): number => Math.round(value * 100) / 100;

const successPercent = (level: QosBenchmarkDeploymentLevel): string | number =>
  level.requests === 0 ? "" : rate(((level.requests - level.failed_requests) / level.requests) * 100);

const BENCHMARK_CSV_COLUMNS: readonly CsvColumn[] = [
  { label: "Run ID", value: ({ run }) => run.run_id },
  { label: "Started", value: ({ run }) => localDateTime(new Date(run.started_at)) },
  { label: "Model", value: ({ run }) => run.model_group },
  { label: "Provider", value: ({ level }) => vendorName(level.vendor) },
  { label: "Upstream model", value: ({ level }) => level.model },
  { label: "API Base", value: ({ level }) => level.api_base },
  { label: "Node ID", value: ({ level }) => level.model_id },
  { label: "Concurrency", value: ({ level }) => level.concurrency },
  { label: "Requests", value: ({ level }) => level.requests },
  { label: "Failed Requests", value: ({ level }) => level.failed_requests },
  { label: "Success rate (%)", value: ({ level }) => successPercent(level) },
  { label: "Peak concurrency", value: ({ level }) => level.peak_concurrency },
  { label: "Requests per second", value: ({ level }) => rate(level.requests_per_second) },
  { label: "Output tokens", value: ({ level }) => level.output_tokens },
  { label: "Output tokens/s", value: ({ level }) => rate(level.output_tokens_per_second) },
  { label: "TTFT P50 (ms)", value: ({ level }) => ms(level.ttft_ms.p50) },
  { label: "TTFT P95 (ms)", value: ({ level }) => ms(level.ttft_ms.p95) },
  { label: "TTFT P99 (ms)", value: ({ level }) => ms(level.ttft_ms.p99) },
  { label: "TPOT P50 (ms)", value: ({ level }) => ms(level.tpot_ms.p50) },
  { label: "TPOT P95 (ms)", value: ({ level }) => ms(level.tpot_ms.p95) },
  { label: "TPOT P99 (ms)", value: ({ level }) => ms(level.tpot_ms.p99) },
  { label: "Latency P50 (ms)", value: ({ level }) => ms(level.e2e_latency_ms.p50) },
  { label: "Latency P95 (ms)", value: ({ level }) => ms(level.e2e_latency_ms.p95) },
  { label: "Latency P99 (ms)", value: ({ level }) => ms(level.e2e_latency_ms.p99) },
  { label: "Responses checked", value: ({ level }) => level.response_checks.checked },
  { label: "Cross-talk responses", value: ({ level }) => level.response_checks.crosstalk },
  { label: "Responses missing their code", value: ({ level }) => level.response_checks.marker_missing },
  { label: "Other traffic on this deployment", value: ({ level }) => level.interference.same_deployment },
  { label: "Other traffic on its endpoint", value: ({ level }) => level.interference.same_endpoint },
];

const csvRows = ({ run, detail }: BenchmarkExport): readonly BenchmarkCsvRow[] =>
  detail.deployment_levels.map((level) => ({ run, level }));

/** One row per run, concurrency level and node, oldest run first. */
export const benchmarkCsv = (exports: readonly BenchmarkExport[]): string => {
  const rows = [...exports]
    .sort((left, right) => Date.parse(left.run.started_at) - Date.parse(right.run.started_at))
    .flatMap(csvRows);
  return Papa.unparse(
    {
      fields: BENCHMARK_CSV_COLUMNS.map((column) => column.label),
      data: rows.map((row) => BENCHMARK_CSV_COLUMNS.map((column) => column.value(row))),
    },
    { escapeFormulae: true },
  );
};

export const benchmarkCsvFileName = (now: Date): string =>
  `qos_benchmarks_${localDateTime(now).replace(" ", "_").replaceAll(":", "")}.csv`;
