import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { decodeJsxEntities, inspectSource, parseTranslation } from "./units.mjs";

export { decodeJsxEntities, jsxTextValue, normalize } from "./units.mjs";

const sourceExtensions = new Set([".tsx", ".ts", ".jsx", ".js"]);
const ignoredDirectories = new Set(["node_modules", ".next", "out", "__tests__", "__mocks__"]);
const terminology = JSON.parse(fs.readFileSync(new URL("./terminology.json", import.meta.url), "utf8"));

export function terminologyViolations(source, translation) {
  return terminology
    .filter((term) => new RegExp(term.source, "i").test(source))
    .flatMap((term) => term.translations.filter((wording) => translation.includes(wording)).map((wording) => ({ term: term.preferred, wording })));
}

function preserveSpacing(original, translated) {
  const leading = /^\s/.test(original) ? " " : "";
  const trailing = /\s$/.test(original) ? " " : "";
  return leading + translated + trailing;
}

function preserveJsxSpacing(original, translated) {
  const lines = original.split(/\r\n|\r|\n/);
  const first = lines[0];
  const last = lines[lines.length - 1];
  const leading = first.trim() !== "" && /^[ \t]/.test(first) ? " " : "";
  const trailing = last.trim() !== "" && /[ \t]$/.test(last) ? " " : "";
  return leading + translated + trailing;
}

function escapeTemplate(text) {
  return text.replace(/\\/g, "\\\\").replace(/`/g, "\\`").replace(/\$\{/g, "\\${");
}

function applyEdits(text, edits) {
  return [...edits].sort((left, right) => right.start - left.start)
    .reduce((result, edit) => result.slice(0, edit.start) + edit.value + result.slice(edit.end), text);
}

function dateLocaleEdits(ts, sourceFile) {
  const edits = [];
  function visit(node) {
    if (ts.isStringLiteral(node) && /^(?:en|en-US|en-GB)$/.test(node.text)) {
      const parent = node.parent;
      if ((ts.isCallExpression(parent) || ts.isNewExpression(parent)) && parent.arguments
        && parent.arguments[0] === node
        && /(?:toLocaleString|toLocaleDateString|toLocaleTimeString|Intl\.(?:NumberFormat|DateTimeFormat|RelativeTimeFormat|ListFormat|Collator))$/.test(parent.expression.getText(sourceFile))) {
        edits.push({ start: node.getStart(sourceFile), end: node.end, value: '"zh-CN"' });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return edits;
}

function plainReplacement(ts, unit, translation) {
  const { node } = unit;
  if (ts.isJsxText(node)) return `{${JSON.stringify(preserveJsxSpacing(node.text, translation))}}`;
  if (ts.isStringLiteral(node) && ts.isJsxAttribute(node.parent)) return `{${JSON.stringify(preserveSpacing(decodeJsxEntities(node.text), translation))}}`;
  return JSON.stringify(preserveSpacing(node.text, translation));
}

function renderJsx(sourceFile, nodes, sourceWithEdits) {
  return nodes.map((node) => {
    if (node.type === "text") return node.value === "" ? "" : `{${JSON.stringify(node.value)}}`;
    const target = node.placeholder.node;
    if (node.type === "placeholder") return sourceWithEdits(target.getStart(sourceFile), target.end);
    const { openingElement, closingElement } = target;
    return sourceWithEdits(openingElement.getStart(sourceFile), openingElement.end)
      + renderJsx(sourceFile, node.children, sourceWithEdits)
      + sourceWithEdits(closingElement.getStart(sourceFile), closingElement.end);
  }).join("");
}

function renderTemplate(sourceFile, nodes, sourceWithEdits) {
  return nodes.map((node) => {
    if (node.type === "text") return escapeTemplate(node.value);
    const expression = node.placeholder.node;
    return `\${${sourceWithEdits(expression.getStart(sourceFile), expression.end)}}`;
  }).join("");
}

function messageReplacement(sourceFile, unit, translation, sourceWithEdits) {
  const nodes = parseTranslation(unit, translation);
  if (unit.kind === "jsx") {
    const space = '{" "}';
    return (unit.leading ? space : "") + renderJsx(sourceFile, nodes, sourceWithEdits) + (unit.trailing ? space : "");
  }
  return `\`${unit.leading ? " " : ""}${renderTemplate(sourceFile, nodes, sourceWithEdits)}${unit.trailing ? " " : ""}\``;
}

export function translateSource(ts, file, source, dictionary) {
  const { sourceFile, units } = inspectSource(ts, file, source);
  const missing = [];
  const violations = [];
  let translated = 0;
  function translationOf(unit) {
    if (!Object.hasOwn(dictionary, unit.key)) {
      missing.push({ text: unit.key, line: unit.line });
      return null;
    }
    const value = dictionary[unit.key];
    if (typeof value !== "string" || value.trim().length === 0) throw new Error(`Invalid Chinese translation: ${unit.key}`);
    for (const violation of terminologyViolations(unit.key, value)) violations.push({ ...violation, text: unit.key, translation: value, line: unit.line });
    if (value === unit.key) return null;
    translated += 1;
    return value;
  }
  const plainEdits = units.filter((unit) => unit.kind === "plain").flatMap((unit) => {
    const translation = translationOf(unit);
    return translation === null ? [] : [{ start: unit.start, end: unit.end, value: plainReplacement(ts, unit, translation) }];
  });
  let edits = [...dateLocaleEdits(ts, sourceFile), ...plainEdits];
  const within = (edit, start, end) => edit.start >= start && edit.end <= end;
  const sourceWithEdits = (start, end) => applyEdits(source.slice(start, end), edits
    .filter((edit) => within(edit, start, end))
    .map((edit) => ({ ...edit, start: edit.start - start, end: edit.end - start })));
  const messages = units.filter((unit) => unit.kind !== "plain").sort((left, right) => (left.end - left.start) - (right.end - right.start));
  for (const unit of messages) {
    const translation = translationOf(unit);
    if (translation === null) continue;
    const value = messageReplacement(sourceFile, unit, translation, sourceWithEdits);
    edits = [...edits.filter((edit) => !within(edit, unit.start, unit.end)), { start: unit.start, end: unit.end, value }];
  }
  return { source: applyEdits(source, edits), translated, missing, violations, units: units.length };
}

function collectFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return ignoredDirectories.has(entry.name) ? [] : collectFiles(file);
    if (!sourceExtensions.has(path.extname(file))) return [];
    if (/\.(?:test|spec|test-d)\.[^.]+$/.test(file) || file.endsWith(".d.ts")) return [];
    return [file];
  });
}

function argumentsFrom(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    if (!argv[index].startsWith("--") || argv[index + 1] === undefined) throw new Error("Options must use --name value");
    values.set(argv[index].slice(2), argv[index + 1]);
  }
  return values;
}

function required(values, name) {
  if (!values.has(name)) throw new Error(`Missing --${name}`);
  return path.resolve(values.get(name));
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function sourceUnits(ts, root, files) {
  return files.map((file) => {
    const source = fs.readFileSync(file, "utf8");
    return { file, relative: path.relative(root, file), source, units: inspectSource(ts, file, source).units };
  });
}

function extract(scanned, output) {
  const entries = new Map();
  for (const { relative, units } of scanned) {
    for (const { key, line } of units) {
      const entry = entries.get(key) ?? { text: key, occurrences: 0, examples: [] };
      entries.set(key, { ...entry, occurrences: entry.occurrences + 1, examples: entry.examples.length < 3 ? [...entry.examples, `${relative}:${line}`] : entry.examples });
    }
  }
  fs.writeFileSync(output, JSON.stringify([...entries.values()].sort((a, b) => b.occurrences - a.occurrences), null, 2) + "\n");
  console.log(`已提取 ${entries.size} 条文案，扫描 ${scanned.length} 个源文件`);
}

function prune(scanned, catalogPath) {
  const catalog = readJson(catalogPath);
  const used = new Set(scanned.flatMap(({ units }) => units.map((unit) => unit.key)));
  const kept = Object.fromEntries(Object.entries(catalog).filter(([key]) => used.has(key)));
  fs.writeFileSync(catalogPath, JSON.stringify(kept, null, 2) + "\n");
  console.log(`已删除 ${Object.keys(catalog).length - Object.keys(kept).length} 条未使用的译文，保留 ${Object.keys(kept).length} 条`);
}

function apply(ts, scanned, catalogPath, output) {
  const dictionary = readJson(catalogPath);
  const contexts = readJson(new URL("./context-overrides.json", import.meta.url));
  const missing = new Map();
  const violations = [];
  let translated = 0;
  let affectedFiles = 0;
  for (const { file, relative, source } of scanned) {
    const fileDictionary = Object.hasOwn(contexts, relative) ? { ...dictionary, ...contexts[relative] } : dictionary;
    const result = translateSource(ts, file, source, fileDictionary);
    for (const item of result.missing) missing.set(item.text, [...(missing.get(item.text) ?? []), `${relative}:${item.line}`].slice(0, 3));
    violations.push(...result.violations.map((violation) => ({ ...violation, location: `${relative}:${violation.line}` })));
    translated += result.translated;
    if (result.source !== source) {
      fs.writeFileSync(file, result.source);
      affectedFiles += 1;
    }
  }
  if (violations.length > 0) {
    const details = violations.map(({ location, term, wording, translation }) => `${location}: 「${wording}」应保留为 ${term}：${translation}`);
    throw new Error(`译文违反术语规则 ${violations.length} 处：\n${details.join("\n")}`);
  }
  const report = {
    filesScanned: scanned.length, filesTranslated: affectedFiles, stringsTranslated: translated,
    missing: [...missing].map(([text, examples]) => ({ text, examples })),
  };
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
  console.log(`已翻译 ${translated} 处文案，涉及 ${affectedFiles} 个文件；新增待翻译文案 ${missing.size} 条，详见 ${output}`);
}

export function run(command, argv) {
  const args = argumentsFrom(argv);
  const root = required(args, "source");
  const require = createRequire(path.join(root, "package.json"));
  const ts = args.has("typescript") ? require(required(args, "typescript")) : require("typescript");
  const scanned = sourceUnits(ts, root, collectFiles(path.join(root, "src")));
  if (command === "extract") return extract(scanned, required(args, "output"));
  if (command === "prune") return prune(scanned, required(args, "catalog"));
  if (command === "apply") return apply(ts, scanned, required(args, "catalog"), required(args, "output"));
  throw new Error(`Unknown command: ${command}`);
}

if (process.argv[1] !== undefined && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] === undefined) throw new Error("Usage: node localize.mjs extract|apply|prune --source directory [--catalog zh-CN.json] [--output report.json]");
  run(process.argv[2], process.argv.slice(3));
}
