"use client";

import React from "react";
import { ImageIcon, Play, RefreshCw, Save } from "lucide-react";

import { useImageConfig, useImageRun, useImageRuns, useRateImage, useStartImageRun } from "@/app/(dashboard)/hooks/qos/useQosImages";
import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import { apiClient } from "@/components/networking";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { extractErrorMessage } from "@/utils/errorUtils";
import { IMAGE_PROMPTS, SMOKE_PROMPTS, type DefectTag, type ImageItem, type ImagePrompt, type ImageRatingInput, type ImageRun } from "./imagePrompts";
import { isQosRange, QOS_RANGES, type QosRange } from "./qosData";

type ImageRange = QosRange | "all";
const IMAGE_RANGES: readonly { value: ImageRange; label: string }[] = [
  ...QOS_RANGES,
  { value: "all", label: "全部记录" },
];

const seconds = (value: number | null): string => (value === null ? "-" : `${value.toFixed(2)} s`);
const money = (value: number): string => `¥${value.toFixed(2)}`;
const estimatedBudget = (promptCount: number, repeats: number, unitCost: number): number =>
  Math.min(100, Math.ceil(promptCount * repeats * unitCost * 100) / 100);
const runStatusLabel: Record<ImageRun["status"], string> = {
  running: "进行中",
  complete: "已完成",
  interrupted: "已中断",
};
const itemStatusLabel: Record<ImageItem["status"], string> = {
  pending: "等待中",
  success: "成功",
  failure: "失败",
};

const runDate = (value: string): string => new Date(value).toLocaleString("zh-CN", {
  month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
});

const percentile = (values: number[], quantile: number): number | null => {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.ceil(quantile * sorted.length) - 1];
};

const defectOptions: { value: DefectTag; label: string }[] = [
  { value: "count", label: "数量错误" }, { value: "spatial", label: "关系错误" },
  { value: "text", label: "文字错误" }, { value: "hands", label: "手部异常" },
  { value: "perspective", label: "透视错误" }, { value: "fusion", label: "物体融合" },
  { value: "artifacts", label: "模糊或伪影" }, { value: "style", label: "风格不符" },
  { value: "other", label: "其他" },
];

function qualityScore(scores: number[], textScore: number | null): number {
  const weights = textScore === null ? [35, 25, 15, 10] : [35, 25, 15, 15, 10];
  const values = textScore === null ? scores : [scores[0], scores[1], textScore, scores[2], scores[3]];
  return Math.round(1000 * values.reduce((sum, score, index) => sum + weights[index] * (score - 1) / 4, 0) / weights.reduce((a, b) => a + b, 0)) / 10;
}

function ScoreField({ label, description, value, onChange }: { label: string; description: string; value: number | null; onChange: (value: number | null) => void }) {
  return <label className="flex flex-col gap-1" title={description}>{label}
    <select className="h-9 rounded-md border bg-background px-2" value={value ?? ""} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}>
      <option value="">请选择</option>
      {[1, 2, 3, 4, 5].map((score) => <option key={score} value={score}>{score}</option>)}
    </select>
  </label>;
}

function ImagePreview({ runId, item, accessToken }: { runId: string; item: ImageItem; accessToken: string }) {
  const [url, setUrl] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!item.image_file) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    const path = `/qos/images/runs/${encodeURIComponent(runId)}/items/${item.id}/image`;
    void apiClient.getBlob(path, { accessToken, signal: controller.signal })
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setUrl(null);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [accessToken, item.id, item.image_file, runId]);

  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" title="查看原图" className="block aspect-square bg-muted">
      <img src={url} alt={`${item.prompt_id}, seed ${item.seed}`} className="aspect-square w-full object-contain" />
    </a>
  ) : (
    <div className="flex aspect-square items-center justify-center bg-muted text-muted-foreground">
      <ImageIcon className="size-6" aria-label="图片加载中" />
    </div>
  );
}

function RatingEditor({ runId, item, accessToken }: { runId: string; item: ImageItem; accessToken: string }) {
  const initial = item.rating;
  const [adherence, setAdherence] = React.useState<number | null>(initial?.structure_correctness == null ? null : initial.prompt_adherence);
  const [structure, setStructure] = React.useState<number | null>(initial?.structure_correctness ?? null);
  const [textAccuracy, setTextAccuracy] = React.useState<number | null>(initial?.text_accuracy ?? null);
  const [imageQuality, setImageQuality] = React.useState<number | null>(initial?.image_quality ?? null);
  const [visualAppeal, setVisualAppeal] = React.useState<number | null>(initial?.visual_appeal ?? null);
  const [textApplicable, setTextApplicable] = React.useState<boolean | null>(initial?.text_applicable ?? null);
  const [hardPassed, setHardPassed] = React.useState<boolean | null>(initial?.hard_conditions_passed ?? null);
  const [textCorrect, setTextCorrect] = React.useState(initial?.text_correct ?? null);
  const [defectTags, setDefectTags] = React.useState<DefectTag[]>(initial?.defect_tags ?? []);
  const [notes, setNotes] = React.useState(initial?.notes ?? "");
  const rate = useRateImage(accessToken, runId);

  const scores = [adherence, structure, imageQuality, visualAppeal];
  const complete = scores.every((score) => score !== null) && hardPassed !== null && textApplicable !== null
    && (textApplicable === false || (textAccuracy !== null && textCorrect !== null));
  const preview = scores.every((score) => score !== null) && textApplicable !== null && (!textApplicable || textAccuracy !== null)
    ? qualityScore(scores as number[], textApplicable ? textAccuracy : null) : null;

  const save = () => {
    if (!complete || adherence === null) return;
    const rating: ImageRatingInput = {
      prompt_adherence: adherence, structure_correctness: structure, text_accuracy: textApplicable ? textAccuracy : null,
      text_applicable: textApplicable, image_quality: imageQuality, visual_appeal: visualAppeal,
      hard_conditions_passed: hardPassed, text_correct: textApplicable ? textCorrect : null,
      artifacts: defectTags.includes("artifacts"), defect_tags: defectTags, notes: notes.trim(),
    };
    rate.mutate({ itemId: item.id, rating });
  };

  return (
    <div className="space-y-3 border-t pt-3 text-sm">
      {initial && initial.quality_score === null && <p className="text-muted-foreground">旧版评分：Prompt 遵循 {initial.prompt_adherence}/5。补全下列维度后才计入新版质量统计。</p>}
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">查看评分标准</summary>
        <p className="mt-1">5 完整满足；4 仅轻微问题；3 基本可用但有明显瑕疵；2 重要要求缺失、影响使用；1 严重错误或不可用。指定数量、文字、对象及左右位置请单独核对硬条件。</p>
      </details>
      <div className="grid gap-2 2xl:grid-cols-2">
        <label className="flex flex-col gap-1">硬条件
          <select className="h-9 rounded-md border bg-background px-2" value={hardPassed === null ? "" : String(hardPassed)} onChange={(event) => setHardPassed(event.target.value === "" ? null : event.target.value === "true")}>
            <option value="">请选择</option><option value="true">全部通过</option><option value="false">未通过</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">提示词是否要求指定文字
          <select className="h-9 rounded-md border bg-background px-2" value={textApplicable === null ? "" : String(textApplicable)} onChange={(event) => { setTextApplicable(event.target.value === "" ? null : event.target.value === "true"); setTextAccuracy(null); setTextCorrect(null); }}>
            <option value="">请选择</option><option value="true">是</option><option value="false">否，不适用</option>
          </select>
        </label>
        <ScoreField label="A 指令遵循（35%）" description="主体、属性、数量、动作和空间关系与提示词是否一致" value={adherence} onChange={setAdherence} />
        <ScoreField label="B 结构正确（25%）" description="五官、手部、物体形状、透视、遮挡与接触关系" value={structure} onChange={setStructure} />
        {textApplicable && <ScoreField label="C 文字准确（15%）" description="指定文字逐字正确、清晰可读，字形与排版符合要求" value={textAccuracy} onChange={setTextAccuracy} />}
        <ScoreField label="D 成像质量（15%）" description="清晰度、细节、边缘、噪声、重复纹理、融合与伪影" value={imageQuality} onChange={setImageQuality} />
        <ScoreField label="E 视觉表现（10%）" description="构图、光照、配色与目标风格，以提示词要求为准" value={visualAppeal} onChange={setVisualAppeal} />
        {textApplicable && <label className="flex flex-col gap-1">指定文字是否完全正确
          <select className="h-9 rounded-md border bg-background px-2" value={textCorrect === null ? "" : String(textCorrect)} onChange={(event) => setTextCorrect(event.target.value === "" ? null : event.target.value === "true")}>
            <option value="">请选择</option><option value="true">完全正确</option><option value="false">有错误</option>
          </select>
        </label>}
      </div>
      <fieldset className="space-y-1"><legend>缺陷标签</legend><div className="flex flex-wrap gap-x-3 gap-y-1">
        {defectOptions.map(({ value, label }) => <label key={value} className="flex items-center gap-1 whitespace-nowrap">
          <input type="checkbox" checked={defectTags.includes(value)} onChange={(event) => setDefectTags(event.target.checked ? [...defectTags, value] : defectTags.filter((tag) => tag !== value))} />{label}
        </label>)}
      </div></fieldset>
      <label className="flex flex-col gap-1">可定位的问题与评审理由（选填）<Input value={notes} maxLength={1000} onChange={(event) => setNotes(event.target.value)} /></label>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" onClick={save} disabled={rate.isPending || !complete}><Save className="size-4" /> 保存评分</Button>
        <span className="text-muted-foreground">质量分：{preview === null ? "-" : `${preview}/100`}{hardPassed === false && " · 硬条件未通过"}</span>
        {rate.isSuccess && <span className="text-muted-foreground">已保存</span>}
        {rate.isError && <span className="text-destructive">{extractErrorMessage(rate.error)}</span>}
      </div>
    </div>
  );
}

function getRunSummary(run: ImageRun) {
  const completed = run.items.filter((item) => item.status !== "pending");
  const succeeded = completed.filter((item) => item.status === "success");
  const latencies = succeeded.flatMap((item) => item.e2e_s === null ? [] : [item.e2e_s]);
  const rated = succeeded.filter((item) => item.rating !== null);
  const multidimensional = rated.filter((item) => item.rating?.quality_score != null);
  const checkedText = multidimensional.filter((item) => item.rating?.text_applicable === true);
  const correctText = checkedText.filter((item) => item.rating?.text_correct === true).length;
  const hardPassed = multidimensional.filter((item) => item.rating?.hard_conditions_passed === true).length;
  const premium = multidimensional.filter((item) => item.rating?.hard_conditions_passed === true && (item.rating?.quality_score ?? 0) >= 75).length;
  const meanQuality = multidimensional.length ? multidimensional.reduce((total, item) => total + item.rating!.quality_score!, 0) / multidimensional.length : null;

  return { completed, succeeded, rated, multidimensional, checkedText, correctText, hardPassed, premium, meanQuality,
    p50: percentile(latencies, 0.5), p95: percentile(latencies, 0.95),
    successRate: completed.length ? succeeded.length / completed.length * 100 : null };
}

function RunMetrics({ run }: { run: ImageRun }) {
  const summary = getRunSummary(run);
  const metrics = [
    { label: "完成进度", value: `${summary.completed.length} / ${run.items.length}`, note: runStatusLabel[run.status] },
    { label: "成功率", value: summary.successRate === null ? "-" : `${summary.successRate.toFixed(1)}%`, note: `${summary.succeeded.length} 张生成成功` },
    { label: "P95 端到端耗时", value: seconds(summary.p95), note: "包含等待和传输" },
    { label: "已评质量均分", value: summary.meanQuality === null ? "-" : summary.meanQuality.toFixed(1), note: summary.meanQuality === null ? "尚未评分" : "满分 100" },
  ];

  return <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
    {metrics.map((metric) => <div key={metric.label} className="min-w-0 rounded-xl border bg-card px-3 py-3 sm:px-4">
      <p className="text-xs text-muted-foreground">{metric.label}</p>
      <strong className="mt-1 block text-lg font-semibold tabular-nums sm:text-xl">{metric.value}</strong>
      <p className="text-xs text-muted-foreground">{metric.note}</p>
    </div>)}
  </div>;
}

function ImageResultCard({ run, item, accessToken, canRate }: { run: ImageRun; item: ImageItem; accessToken: string; canRate: boolean }) {
  const score = item.rating?.quality_score;
  const scoreLabel = score == null ? "待评分" : `质量 ${score}/100`;
  const resultLabel = item.rating && score == null ? "旧版评分" : scoreLabel;

  return (
    <article className="min-w-0 rounded-xl border bg-background p-3">
      <div className="flex min-w-0 gap-3">
        <div className="w-24 shrink-0 overflow-hidden rounded-lg sm:w-28">
          {item.status === "success" ? <ImagePreview runId={run.id} item={item} accessToken={accessToken} />
            : <div className="flex aspect-square items-center justify-center bg-muted text-sm text-muted-foreground">{itemStatusLabel[item.status]}</div>}
        </div>
        <div className="flex min-w-0 flex-col gap-1 text-sm">
          <h4 className="break-words font-medium">{item.prompt_id} · {run.supports_seed ? `种子 ${item.seed}` : `第 ${item.seed} 次`}</h4>
          <p className="text-xs text-muted-foreground">端到端 {seconds(item.e2e_s)} · 排队 {item.queue_s === null ? "未提供" : seconds(item.queue_s)}</p>
          <p className="mt-auto pt-2 text-xs"><span className={score == null ? "text-muted-foreground" : "font-medium text-primary"}>{item.status === "success" ? resultLabel : itemStatusLabel[item.status]}</span>
            {item.rating?.hard_conditions_passed !== null && item.rating?.hard_conditions_passed !== undefined && ` · 硬条件${item.rating.hard_conditions_passed ? "通过" : "未通过"}`}</p>
        </div>
      </div>
      <details className="mt-3 border-t pt-2 text-sm">
        <summary className="cursor-pointer text-primary">查看 Prompt、服务数据与评分</summary>
        <div className="space-y-2 pt-3">
          <p className="break-words">{item.prompt}</p>
          {item.negative_prompt && <p className="text-muted-foreground">排除：{item.negative_prompt}</p>}
          <p className="text-muted-foreground">检查项：{item.check || "指令遵循和可见缺陷"}</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>端到端：{seconds(item.e2e_s)}</span>
            <span title="从平台请求网关到收到完整图片响应，包含上游等待与传输">网关响应：{seconds(item.response_s ?? null)}</span>
            <span>上游排队：{item.queue_s === null ? "未提供" : seconds(item.queue_s)}</span>
            <span>上游生成：{item.run_s === null ? "未提供" : seconds(item.run_s)}</span>
            <span>单张预估：{money(run.unit_cost_cny)}</span>
            <span>服务商实际费用：{item.cost_cny === null ? "未提供" : money(item.cost_cny)}</span>
          </div>
          {item.error && <p className="break-words text-destructive">{item.error}</p>}
          {item.status === "success" && canRate && <RatingEditor runId={run.id} item={item} accessToken={accessToken} />}
          {item.rating && !canRate && <p className="text-muted-foreground">{item.rating.quality_score === null ? `旧版评分：指令遵循 ${item.rating.prompt_adherence}/5` : `质量分 ${item.rating.quality_score}/100 · 硬条件${item.rating.hard_conditions_passed ? "通过" : "未通过"}`}{item.rating.notes && ` · ${item.rating.notes}`}</p>}
        </div>
      </details>
    </article>
  );
}

function RunDetail({ run, accessToken, canRate }: { run: ImageRun; accessToken: string; canRate: boolean }) {
  const summary = getRunSummary(run);
  const promptCount = new Set(run.items.map((item) => item.prompt_id)).size;
  const repeats = promptCount ? run.items.length / promptCount : 0;

  return <section aria-label="所选批次详情" className="min-w-0 space-y-4 rounded-xl border bg-card p-4 md:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
      <div className="min-w-0">
        <h3 className="break-words text-lg font-semibold">{run.model}</h3>
        <p className="mt-1 break-all text-xs text-muted-foreground">{new Date(run.started_at).toLocaleString("zh-CN")} · 批次 {run.id} · {run.size}</p>
      </div>
      <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">{runStatusLabel[run.status]}</span>
    </div>
    <div className="flex flex-wrap gap-x-8 gap-y-3 border-b pb-4 text-sm">
      <div><p className="text-xs text-muted-foreground">Prompt × 重复</p><strong>{promptCount} × {Number.isInteger(repeats) ? repeats : "-"}</strong></div>
      <div><p className="text-xs text-muted-foreground">已评分</p><strong>{summary.multidimensional.length} / {summary.succeeded.length}</strong></div>
      <div><p className="text-xs text-muted-foreground">预估费用</p><strong>{money(run.estimated_cost_cny)}</strong></div>
      <div><p className="text-xs text-muted-foreground">P50 端到端耗时</p><strong>{seconds(summary.p50)}</strong></div>
    </div>
    {summary.multidimensional.length > 0 && <p className="text-xs text-muted-foreground">硬条件通过 {summary.hardPassed}/{summary.multidimensional.length} · 文字完全正确 {summary.correctText}/{summary.checkedText.length} · 优质图 {summary.premium}/{summary.multidimensional.length}（硬条件通过且质量分 ≥ 75）</p>}
    {summary.rated.length > summary.multidimensional.length && <p className="text-xs text-muted-foreground">另有 {summary.rated.length - summary.multidimensional.length} 张旧版评分，未计入新版质量统计。</p>}
    <div>
      <h4 className="mb-3 text-xs font-medium text-muted-foreground">生成结果 · {run.items.length} 张</h4>
      <div className="grid gap-3 xl:grid-cols-2">
        {run.items.map((item) => <ImageResultCard key={item.id} run={run} item={item} accessToken={accessToken} canRate={canRate} />)}
      </div>
    </div>
  </section>;
}

export default function ImageQosPanel({ accessToken }: { accessToken: string | null }) {
  const { userRole, isViewOnly } = useAuthorized();
  const canWrite = !isViewOnly && userRole === "Admin";
  const config = useImageConfig(accessToken);
  const models = Object.keys(config.data?.models ?? {}).sort();
  const [model, setModel] = React.useState("");
  const [preset, setPreset] = React.useState<"smoke" | "full" | "custom">("smoke");
  const [customPromptCount, setCustomPromptCount] = React.useState(4);
  const [seedText, setSeedText] = React.useState("42");
  const [repeats, setRepeats] = React.useState(1);
  const [concurrency, setConcurrency] = React.useState(1);
  const [budget, setBudget] = React.useState(0.5);
  const [range, setRange] = React.useState<ImageRange>("24h");
  const [selectedRun, setSelectedRun] = React.useState<string | null>(null);
  const runs = useImageRuns(accessToken, range);
  const detail = useImageRun(accessToken, selectedRun);
  const start = useStartImageRun(accessToken);

  React.useEffect(() => {
    if (!model && models.length > 0) {
      setModel(models[0]);
      setSeedText(config.data?.models[models[0]]?.supports_seed
        ? (preset === "full" ? "42,20261023" : "42")
        : "42");
      setRepeats(preset === "full" ? 2 : 1);
      setBudget(estimatedBudget(preset === "smoke" ? 2 : preset === "full" ? 16 : customPromptCount,
        preset === "full" ? 2 : 1, config.data?.models[models[0]]?.unit_cost_cny ?? 0));
    }
  }, [model, models, config.data, preset, customPromptCount]);
  React.useEffect(() => {
    if (runs.data?.length && !runs.data.some((run) => run.id === selectedRun)) setSelectedRun(runs.data[0].id);
    if (runs.data?.length === 0 && selectedRun) setSelectedRun(null);
  }, [runs.data, selectedRun]);

  const prompts: readonly ImagePrompt[] = preset === "smoke" ? SMOKE_PROMPTS
    : preset === "full" ? IMAGE_PROMPTS : IMAGE_PROMPTS.slice(0, customPromptCount);
  const profile = config.data?.models[model];
  const seedParts = seedText.split(",");
  const validRepeats = Number.isInteger(repeats) && repeats >= 1 && repeats <= 4;
  const seeds = profile?.supports_seed ? seedParts.map((value) => Number(value.trim()))
    : validRepeats ? Array.from({ length: repeats }, (_, index) => index + 1) : [];
  const validSeeds = profile?.supports_seed
    ? seedParts.length > 0 && seedParts.length <= 4 && seedParts.every((value) => value.trim() !== "")
      && seeds.every((seed) => Number.isInteger(seed) && seed >= 0 && seed <= 2147483647) && new Set(seeds).size === seeds.length
    : validRepeats;
  const count = prompts.length * seeds.length;
  const estimate = count * (profile?.unit_cost_cny ?? 0);
  const promptsSupported = Boolean(profile && prompts.every((prompt) => prompt.text.length <= profile.max_prompt_chars
    && (profile.supports_negative_prompt || !prompt.negative_prompt)));
  const canStart = canWrite && Boolean(model && profile && config.data && prompts.length > 0 && promptsSupported && validSeeds
    && count <= config.data.max_images && estimate <= budget && concurrency >= 1 && concurrency <= 4);

  const handleStart = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canStart) return;
    start.mutate({ model, prompts, seeds, concurrency, size: "1024x1024", max_cost_cny: budget }, {
      onSuccess: (run) => setSelectedRun(run.id),
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="qos-image-range" className="text-sm text-muted-foreground">测试记录时间范围</label>
          <Select items={IMAGE_RANGES} value={range} onValueChange={(value: string | null) => {
            if (value !== null && (value === "all" || isQosRange(value))) {
              setSelectedRun(null);
              setRange(value);
            }
          }}>
            <SelectTrigger id="qos-image-range" className="w-44"><SelectValue /></SelectTrigger>
            <SelectContent>{IMAGE_RANGES.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <Button type="button" variant="outline" disabled={runs.isFetching || config.isFetching || detail.isFetching}
          onClick={() => {
            void runs.refetch();
            void config.refetch();
            if (selectedRun) void detail.refetch();
          }}>
          <RefreshCw className={`size-4 ${runs.isFetching || config.isFetching || detail.isFetching ? "animate-spin" : ""}`} />刷新
        </Button>
      </div>
      {canWrite && <form onSubmit={handleStart} className="space-y-4 border-b pb-5">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex w-full min-w-0 max-w-sm flex-col gap-1 text-sm">Image model
            <Select items={models.map((name) => ({ value: name, label: name }))} value={model} onValueChange={(value) => {
              const next = value ?? "";
              setModel(next);
              setSeedText(preset === "full" ? "42,20261023" : "42");
              setRepeats(preset === "full" ? 2 : 1);
              setBudget(estimatedBudget(prompts.length, preset === "full" ? 2 : 1, config.data?.models[next]?.unit_cost_cny ?? 0));
            }}>
              <SelectTrigger className="w-full"><SelectValue placeholder="Choose an image model" /></SelectTrigger>
              <SelectContent>{models.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
            </Select>
          </label>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1 text-sm"><span>Prompt set</span>
            <div className="flex h-9 overflow-hidden rounded-md border">
              <Button type="button" variant={preset === "smoke" ? "default" : "ghost"} size="sm" className="rounded-none" onClick={() => { setPreset("smoke"); setSeedText("42"); setRepeats(1); setBudget(estimatedBudget(2, 1, profile?.unit_cost_cny ?? 0)); }}>Smoke · 2</Button>
              <Button type="button" variant={preset === "full" ? "default" : "ghost"} size="sm" className="rounded-none" onClick={() => { setPreset("full"); setSeedText("42,20261023"); setRepeats(2); setBudget(estimatedBudget(16, 2, profile?.unit_cost_cny ?? 0)); }}>Full · 16</Button>
              <Button type="button" variant={preset === "custom" ? "default" : "ghost"} size="sm" className="rounded-none" onClick={() => { setPreset("custom"); setSeedText("42"); setRepeats(1); setBudget(estimatedBudget(customPromptCount, 1, profile?.unit_cost_cny ?? 0)); }}>自选</Button>
            </div>
          </div>
          {preset === "custom" && <label className="flex flex-col gap-1 text-sm" title="按固定题库顺序取前 N 条 Prompt">Prompt 数量（前 N 条）
            <Input className="w-28" type="number" min={1} max={IMAGE_PROMPTS.length} value={customPromptCount} onChange={(event) => {
              const value = Number(event.target.value);
              setCustomPromptCount(value);
              if (Number.isInteger(value) && value >= 1 && value <= IMAGE_PROMPTS.length) setBudget(estimatedBudget(value, profile?.supports_seed ? seedParts.length : repeats, profile?.unit_cost_cny ?? 0));
            }} />
          </label>}
          {profile?.supports_seed ? <label className="flex flex-col gap-1 text-sm">种子（逗号分隔）<Input className="w-40" value={seedText} onChange={(event) => setSeedText(event.target.value)} /></label>
            : <label className="flex flex-col gap-1 text-sm">每条重复次数<Input className="w-28" type="number" min={1} max={4} value={repeats} onChange={(event) => setRepeats(Number(event.target.value))} /></label>}
          <label className="flex flex-col gap-1 text-sm">Concurrency<Input className="w-24" type="number" min={1} max={4} value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))} /></label>
          <label className="flex flex-col gap-1 text-sm">Budget (CNY)<Input className="w-28" type="number" min={0.01} max={100} step={0.01} value={budget} onChange={(event) => setBudget(Number(event.target.value))} /></label>
          <Button type="submit" disabled={!canStart || start.isPending}><Play className="size-4" /> Start image test</Button>
        </div>
        <p className="text-sm text-muted-foreground">{prompts.length} 条 Prompt × {seeds.length} 次 = {count} 张；按每张 {money(profile?.unit_cost_cny ?? 0)} 预估 {money(estimate)}。每张会发送一次付费请求，预算是预估校验，不是服务商实际扣费上限。</p>
        {profile && !profile.supports_seed && <p className="text-sm text-muted-foreground">该模型未声明支持 seed；重复生成不会发送种子参数。</p>}
        {profile && !promptsSupported && <Alert variant="destructive"><AlertDescription>当前 Prompt 集包含该模型不支持的参数或超出长度限制。</AlertDescription></Alert>}
        {config.data && count > config.data.max_images && <Alert variant="destructive"><AlertDescription>单次最多可生成 {config.data.max_images} 张图片，请减少 Prompt 数量或重复次数。</AlertDescription></Alert>}
        {profile && estimate > budget && <Alert variant="destructive"><AlertDescription>预估费用超过当前预算，请减少图片数量或调整预算。</AlertDescription></Alert>}
        {models.length === 0 && <Alert><AlertDescription>暂无已注册且配置了评测费用的生图模型。</AlertDescription></Alert>}
        {start.isError && <Alert variant="destructive"><AlertDescription>{extractErrorMessage(start.error)}</AlertDescription></Alert>}
      </form>}
      <section className="space-y-4 rounded-xl border bg-muted/20 p-4 md:p-5" aria-label="图像测试记录">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div><h2 className="text-xl font-semibold">图像测试记录</h2><p className="mt-1 text-sm text-muted-foreground">按批次浏览生成结果、服务指标和人工评分。</p></div>
          <span className="text-xs text-muted-foreground">最近 {runs.data?.length ?? 0} 次测试</span>
        </div>
        {runs.isError && <Alert variant="destructive"><AlertDescription>{extractErrorMessage(runs.error)}</AlertDescription></Alert>}
        {detail.data && <RunMetrics run={detail.data} />}
        <div className="grid items-start gap-4 lg:grid-cols-[238px_minmax(0,1fr)]">
          <nav aria-label="测试批次" className="min-w-0 space-y-2">
            <h3 className="text-xs font-medium text-muted-foreground">测试批次</h3>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
              {(runs.data ?? []).map((run) => {
                const completed = run.items.filter((item) => item.status !== "pending").length;
                return <button key={run.id} type="button" onClick={() => setSelectedRun(run.id)} aria-pressed={selectedRun === run.id}
                  className={`min-w-0 rounded-xl border p-3 text-left text-sm transition-colors hover:bg-accent ${selectedRun === run.id ? "border-primary bg-primary/5" : "bg-card"}`}>
                  <span className="block break-words font-medium">{run.model}</span>
                  <span className="mt-2 flex flex-wrap items-center justify-between gap-1 text-xs text-muted-foreground"><span>{runDate(run.started_at)}</span><span>{completed} / {run.items.length} · {runStatusLabel[run.status]}</span></span>
                </button>;
              })}
              {runs.data?.length === 0 && <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">暂无图像测试记录。</p>}
              {runs.isPending && <p className="text-sm text-muted-foreground">正在加载测试记录…</p>}
            </div>
          </nav>
          {detail.data && accessToken ? <RunDetail run={detail.data} accessToken={accessToken} canRate={canWrite} />
            : selectedRun && <div className="rounded-xl border bg-card p-5 text-sm text-muted-foreground">正在加载批次详情…</div>}
        </div>
      </section>
    </div>
  );
}
