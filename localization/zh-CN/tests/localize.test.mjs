import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { run, translateSource, terminologyViolations } from "../localize.mjs";
import { inspectSource } from "../units.mjs";

const require = createRequire(import.meta.url);
const ts = require(process.env.TYPESCRIPT_PATH);
const dictionary = {
  "API Key": "API 密钥", "Enter your API key": "请输入 API 密钥", "Save": "保存",
  "Active": "已启用", "Inactive": "未启用", "Delete": "删除", "Delete model": "删除模型",
  "Failed to save": "保存失败", "No models found": "未找到模型",
};
const keysOf = (source, file = "units.tsx") => inspectSource(ts, file, source).units.map((unit) => unit.key);
const parses = (source) => ts.createSourceFile("out.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX).parseDiagnostics.length === 0;

test("本地化可见表单文案，同时保留提交值、协议标识和状态判断", () => {
  const source = `
    const payload = { model: "model-v1", role: "user", content: "Save", api_key: "private" };
    export const view = (status: string) => <form>
      <label htmlFor="api_key">API Key</label>
      <input id="api_key" name="api_key" placeholder="Enter your API key" value="Save" />
      <button type="submit">Save</button>
      <span>{status === "active" ? "Active" : "Inactive"}</span>
    </form>;
  `;
  const result = translateSource(ts, "form.tsx", source, dictionary);
  assert.match(result.source, /API 密钥/);
  assert.match(result.source, /请输入 API 密钥/);
  assert.match(result.source, /\{"保存"\}/);
  assert.match(result.source, /status === "active" \? "已启用" : "未启用"/);
  assert.match(result.source, /name="api_key"/);
  assert.match(result.source, /value="Save"/);
  assert.match(result.source, /content: "Save"/);
  assert.match(result.source, /model: "model-v1"/);
});

test("模板字符串整句翻译，变量可以随中文语序调整位置", () => {
  const source = 'toast.error(`Failed to save ${model.id} after ${count} retries`);';
  const result = translateSource(ts, "toast.ts", source, { "Failed to save {0} after {1} retries": "重试 {1} 次后仍无法保存 {0}" });
  assert.equal(result.source, 'toast.error(`重试 ${count} 次后仍无法保存 ${model.id}`);');
});

test("被行内标签拆开的句子按整句提取，翻译后标签和表达式按译文顺序还原", () => {
  const source = '<p><b className="x">Example:</b> name it <code>a-b</code>, then call {busy ? "Save" : "Delete"}</p>;';
  assert.deepEqual(keysOf(source).sort(), ["<0>Example:</0> name it <1/>, then call {2}", "Delete", "Save"]);
  const result = translateSource(ts, "inline.tsx", source, {
    ...dictionary, "<0>Example:</0> name it <1/>, then call {2}": "<0>示例：</0>先调用 {2}，再命名为 <1/>",
  });
  assert.equal(result.source, '<p><b className="x">{"示例："}</b>{"先调用 "}{busy ? "保存" : "删除"}{"，再命名为 "}<code>a-b</code></p>;');
  assert.ok(parses(result.source));
});

test("嵌套的独立句子先翻译，再作为整体放入外层句子", () => {
  const source = "<div>Read the <a href=\"/x\">guide</a> first<Panel><p>Note: see <b>docs</b></p></Panel></div>;";
  const result = translateSource(ts, "nested.tsx", source, {
    "Read the <0>guide</0> first<1/>": "请先阅读<0>指南</0><1/>",
    "Note: see <0>docs</0>": "注意：参见<0>文档</0>",
  });
  assert.equal(result.source, '<div>{"请先阅读"}<a href="/x">{"指南"}</a><Panel><p>{"注意：参见"}<b>{"文档"}</b></p></Panel></div>;');
});

test("译文的占位符与原文不一致时直接报错，不生成残缺页面", () => {
  const source = "<p>Read the <a>guide</a> first</p>;";
  assert.throws(() => translateSource(ts, "bad.tsx", source, { "Read the <0>guide</0> first": "请先阅读指南" }), /Placeholder mismatch/);
  assert.throws(() => translateSource(ts, "bad.tsx", "const message = `Saved ${n}`;", { "Saved {0}": "已保存 {1}" }), /Placeholder mismatch/);
});

test("英文复数后缀占位符可以在中文译文中省略，其他占位符不能省略", () => {
  const source = "const message = `Imported ${count} server${count === 1 ? \"\" : \"s\"}`;";
  const result = translateSource(ts, "plural.ts", source, { "Imported {0} server{1}": "已导入 {0} 个服务" });
  assert.equal(result.source, "const message = `已导入 ${count} 个服务`;");
  assert.throws(() => translateSource(ts, "plural.ts", source, { "Imported {0} server{1}": "已导入服务{1}" }), /Placeholder mismatch/);
});

test("上游新增文案明确列入报告，已应用中文补丁的文件可重复处理", () => {
  const first = translateSource(ts, "empty.tsx", '<div><p>No models found</p><button>New upstream action</button></div>', dictionary);
  assert.deepEqual(first.missing.map((item) => item.text), ["New upstream action"]);
  const second = translateSource(ts, "empty.tsx", first.source, dictionary);
  assert.equal(second.source, first.source);
  assert.equal(second.translated, 0);
});

test("构建遇到词库中没有的文案直接报错，列出文案和源文件位置", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "localize-"));
  t.after(() => fs.rmSync(root, { recursive: true }));
  fs.mkdirSync(path.join(root, "src"));
  fs.writeFileSync(path.join(root, "src", "page.tsx"), "export const Page = () => <button>New upstream action</button>;\n");
  fs.writeFileSync(path.join(root, "zh-CN.json"), JSON.stringify(dictionary));
  const apply = (output) => run("apply", [
    "--source", root, "--catalog", path.join(root, "zh-CN.json"), "--output", output, "--typescript", process.env.TYPESCRIPT_PATH,
  ]);

  assert.throws(() => apply(path.join(root, "missing.json")), /1 条文案缺少译文[^]*src\/page\.tsx:1: New upstream action/);
  assert.equal(fs.existsSync(path.join(root, "missing.json")), false);

  fs.writeFileSync(path.join(root, "zh-CN.json"), JSON.stringify({ ...dictionary, "New upstream action": "上游新操作" }));
  apply(path.join(root, "report.json"));
  assert.equal(fs.readFileSync(path.join(root, "src", "page.tsx"), "utf8"), 'export const Page = () => <button>{"上游新操作"}</button>;\n');
});

test("代码示例、URL 和属性访问保持原样", () => {
  const source = 'const data = JSON.stringify({content: "Save"}); const code = <code>{"curl https://api.example.com/v1/models"}</code>; const value = titles["Save"];';
  assert.equal(translateSource(ts, "example.tsx", source, dictionary).source, source);
});

test("嵌入样式和代码片段原样保留，中文补丁可处理源文件中的内联样式", () => {
  const source = '<><style jsx>{`@keyframes loading { 0% { opacity: 0; } }`}</style><code>Save</code><span>Save</span></>';
  const result = translateSource(ts, "styles.tsx", source, dictionary);
  assert.match(result.source, /@keyframes loading \{ 0% \{ opacity: 0; \} \}/);
  assert.match(result.source, /<code>Save<\/code>/);
  assert.match(result.source, /<span>\{"保存"\}<\/span>/);
});

test("日期和数字采用中文地区设置，语言选项的接口取值保持原样", () => {
  const source = 'const date = value.toLocaleDateString("en-US"); const options = [{label:"English", value:"en-US"}];';
  const result = translateSource(ts, "date.ts", source, dictionary);
  assert.match(result.source, /toLocaleDateString\("zh-CN"\)/);
  assert.match(result.source, /value:"en-US"/);
});

test("包含引号和 JSON 示例的属性译文仍是有效 JSX", () => {
  const result = translateSource(ts, "quote.tsx", '<input placeholder="API Key" />', { "API Key": '输入 "api_key"，例如 {"value":"key"}' });
  assert.ok(parses(result.source));
  assert.match(result.source, /placeholder=\{/);
});

test("表单 render prop 中的字符串属性解构保持协议名称", () => {
  const source = '<Field>{({ "aria-invalid": invalid, "aria-describedby": description }) => <input aria-invalid={invalid} aria-describedby={description} placeholder="API Key" />}</Field>';
  const result = translateSource(ts, "binding.tsx", source, { "aria-invalid": "无效", "aria-describedby": "说明", "API Key": "API 密钥" });
  assert.match(result.source, /"aria-invalid": invalid/);
  assert.match(result.source, /"aria-describedby": description/);
  assert.match(result.source, /API 密钥/);
});

test("A2A 消息类型和遥测状态位于嵌套对象中时仍保持接口取值", () => {
  const source = 'const rpcRequest = {params:{message:{kind:"message",parts:[{kind:"text",text:"Save"}]}}}; const trace = {summary:{status:"error"}};';
  assert.equal(translateSource(ts, "request.ts", source, { message: "消息", text: "文本", error: "错误", Save: "保存" }).source, source);
});

test("样式映射和函数参数保持原值，独立的标题映射可以翻译", () => {
  const source = 'const buttonVariants = {text:"ghost"}; const tooltip = (entity: "key" | "team" = "key") => entity; const STATUS_TITLES = {not_found:"No models found"};';
  const result = translateSource(ts, "mapping.ts", source, { ghost: "幽灵", key: "密钥", "No models found": "未找到模型" });
  assert.match(result.source, /text:"ghost"/);
  assert.match(result.source, /= "key"/);
  assert.match(result.source, /not_found:"未找到模型"/);
});

test("Map 和键值对列表只翻译显示值，查找用的键保持原值", () => {
  const source = 'const FIELD_LABELS = new Map([["projects", "Create and update projects"], ["max_budget", "Max Budget"]]);';
  assert.deepEqual(keysOf(source, "map.ts"), ["Create and update projects", "Max Budget"]);
});

test("名称像标签但用于比较或查找的变量保持原值", () => {
  const source = 'const weekLabel = `Week ${n}`; const entry = rows.find((row) => row.week === weekLabel); const pageTitle = `Week ${n}`; render(pageTitle);';
  assert.deepEqual(keysOf(source, "week.ts"), ["Week {0}"]);
  const lookup = 'const statusLabel = "Active"; const found = statuses.get(statusLabel);';
  assert.deepEqual(keysOf(lookup, "lookup.ts"), []);
});

test("只包含展示标签的联合类型与返回标签同步翻译", () => {
  const source = 'const getLabel = (): { readonly label: "Active" | "Inactive" } => ({label: "Active"});';
  const result = translateSource(ts, "label.ts", source, dictionary);
  assert.match(result.source, /label: "已启用" \| "未启用"/);
  assert.match(result.source, /label: "已启用"\}\)/);
});

test("属性类型内的 Pick 键名和索引访问保持类型系统原值", () => {
  const source = 'type Data = {summary: Pick<Stats,"count" | "average">; children: Props["children"]};';
  assert.equal(translateSource(ts, "types.ts", source, { count: "数量", average: "平均值", children: "子项" }).source, source);
});

test("术语检查报出被译成中文的保留术语，不改写译文", () => {
  assert.deepEqual(terminologyViolations("Input Tokens", "输入令牌"), [{ term: "Token", wording: "令牌" }]);
  assert.deepEqual(terminologyViolations("Input Tokens", "输入 Token"), []);
  assert.deepEqual(terminologyViolations("Task completed", "任务已完成"), []);
  const result = translateSource(ts, "term.tsx", "<p>Input Tokens</p>", { "Input Tokens": "输入令牌" });
  assert.equal(result.violations.length, 1);
  assert.match(result.source, /输入令牌/);
});

test("组件展示属性的默认值可以翻译，业务参数默认值保持原样", () => {
  const source = 'function Title({title="Save", entity="key"}) {return title;} function message(label="Save",entity="key"){return label;}';
  const result = translateSource(ts, "props.ts", source, { Save: "保存", key: "密钥" });
  assert.match(result.source, /title="保存", entity="key"/);
  assert.match(result.source, /label="保存",entity="key"/);
});

test("指标名称字典翻译展示值，业务索引变量保持原值", () => {
  const source = 'const METRIC_NOUN = {spend:"spend"}; const noun="investigation"; const state={metric:"spend"};';
  const result = translateSource(ts, "metric.ts", source, { spend: "费用", investigation: "调查" });
  assert.match(result.source, /spend:"费用"/);
  assert.match(result.source, /noun="investigation"/);
  assert.match(result.source, /metric:"spend"/);
});

test("多行 JSX 文本只保留 React 实际渲染的首尾空格", () => {
  const source = `<span className="flex">
        Public Model Name
        <Tooltip /></span>; <div>
        Plain heading
      </div>; <p>Hello <b>you</b> </p>`;
  assert.deepEqual(keysOf(source).sort(), ["Hello <0>you</0>", "Plain heading", "Public Model Name<0/>"]);
  const result = translateSource(ts, "spacing.tsx", source, { "Public Model Name<0/>": "公开模型名称<0/>", "Plain heading": "普通标题", "Hello <0>you</0>": "你好<0>你</0>" });
  assert.match(result.source, /<span className="flex">\{"公开模型名称"\}<Tooltip \/><\/span>/);
  assert.match(result.source, /<div>\{"普通标题"\}<\/div>/);
  assert.match(result.source, /<p>\{"你好"\}<b>\{"你"\}<\/b>\{" "\}<\/p>/);
});

test("JSX 文本和属性中的 HTML 实体按实际字符匹配词库并输出实际字符", () => {
  const source = '<p title="Say &quot;hi&quot;">Use &quot;team-*&quot; &amp; more</p>';
  assert.deepEqual(keysOf(source).sort(), ['Say "hi"', 'Use "team-*" & more']);
  const result = translateSource(ts, "entity.tsx", source, { 'Say "hi"': '输入 "hi"', 'Use "team-*" & more': '使用 "team-*" 等' });
  assert.match(result.source, /title=\{"输入 \\"hi\\""\}/);
  assert.match(result.source, /\{"使用 \\"team-\*\\" 等"\}/);
});
