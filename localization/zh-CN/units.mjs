const displayProperties = new Set([
  "label", "title", "description", "placeholder", "header", "heading", "subheading",
  "tooltip", "helpText", "helperText", "hint", "emptyText", "emptyMessage", "message",
  "errorMessage", "successMessage", "buttonText", "confirmText", "cancelText", "okText",
  "loadingText", "searchPlaceholder", "aria-label", "aria-description", "alt", "caption",
  "text", "children", "content", "summary", "subtitle", "noResultsText", "triggerLabel",
  "emptyLabel", "descriptionText", "tooltipText", "actionLabel", "loadingMessage",
  "groupLabel", "shortLabel", "displayName",
  "showForAdmin", "showForNonAdmin",
  "noDataMessage",
]);
const machineProperties = new Set([
  "value", "key", "id", "name", "type", "role", "href", "src", "className", "class",
  "htmlFor", "accessorKey", "accessor", "dataIndex", "field", "path", "endpoint", "url",
  "method", "model", "model_name", "api_base", "api_key", "variant", "size", "target",
  "rel", "testId", "data-testid", "data-slot", "align", "side", "format", "language",
]);
const messageMethods = new Set(["error", "success", "warning", "info", "loading", "message", "fromError"]);
const lookupMethods = new Set(["get", "has", "set", "delete", "includes", "indexOf", "startsWith", "endsWith"]);
const displayVariable = /(?:labels?|titles?|descriptions?|placeholders?|hints?|tooltips?|messages?|headings?|captions?|emptyText|buttonText|subtitles?|displayName|helpText|display)$/i;
const codeTags = new Set(["code", "pre", "style", "script", "SyntaxHighlighter", "CodeBlock", "Code", "CodeEditor"]);
const placeholderPattern = /\{(\d+)\}|<(\d+)\/>|<(\d+)>|<\/(\d+)>/g;

const namedEntities = new Map([["quot", '"'], ["apos", "'"], ["amp", "&"], ["lt", "<"], ["gt", ">"], ["nbsp", " "]]);

export function decodeJsxEntities(text) {
  return text.replace(/&(?:#x([0-9a-fA-F]+)|#(\d+)|([a-zA-Z]+));/g, (entity, hex, decimal, name) => {
    if (hex !== undefined) return String.fromCodePoint(Number.parseInt(hex, 16));
    if (decimal !== undefined) return String.fromCodePoint(Number.parseInt(decimal, 10));
    return namedEntities.has(name) ? namedEntities.get(name) : entity;
  });
}

export function normalize(text) {
  return text.replace(/\s+/g, " ").trim();
}

export function jsxTextValue(raw) {
  const lines = raw.split(/\r\n|\n|\r/);
  const lastContentLine = lines.findLastIndex((line) => /[^ \t]/.test(line));
  const parts = lines.map((line, index) => {
    const leading = index === 0 ? line : line.replace(/^[ \t]+/, "");
    const trimmed = index === lines.length - 1 ? leading : leading.replace(/[ \t]+$/, "");
    if (trimmed === "") return "";
    return index === lastContentLine ? trimmed : `${trimmed} `;
  });
  return decodeJsxEntities(parts.join("").replace(/\t/g, " "));
}

function propertyName(ts, node) {
  if (ts.isIdentifier(node) || ts.isStringLiteral(node)) return node.text;
  return "";
}

export function isCode(text) {
  if (/[㐀-鿿]/.test(text)) return true;
  if (!/[a-zA-Z]/.test(text)) return true;
  if (/^(?:https?:|data:|\/|\.|#|--)/.test(text)) return true;
  if (/^\$\{|^\^|^[A-Z][A-Z0-9_]*=|^[a-z][a-z0-9+.-]*:\S/.test(text)) return true;
  if (/^[a-zA-Z\d_$.-]+(?:_[a-zA-Z\d_$.-]+)+$/.test(text)) return true;
  if (/^[A-Za-z\d_.+-]*\d[A-Za-z\d_.+-]*$/.test(text)) return true;
  if (/^[a-zA-Z\d@_-]+\/[a-zA-Z\d@_/*.-]+$/.test(text)) return true;
  if (/^(?:curl\s|import\s|from\s|SELECT\s|const\s|export\s|npm\s|pip\s|docker\s|pnpm\s)/.test(text)) return true;
  if (/^@keyframes\b|(?:^|[\s'"])(?:client|resolver|response|result|request|config)\s*=/.test(text)) return true;
  if (/^\s*[\[{][\s\S]*[\]}]\s*$/.test(text)) return true;
  if (/^(?:[A-Za-z]+\.)+[A-Za-z]+$/.test(text)) return true;
  if (/^#[0-9a-fA-F]{3,8}$/.test(text)) return true;
  return false;
}

function isComparison(ts, node) {
  if (!ts.isBinaryExpression(node)) return false;
  return new Set([
    ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.EqualsEqualsEqualsToken,
    ts.SyntaxKind.ExclamationEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken,
    ts.SyntaxKind.InKeyword, ts.SyntaxKind.InstanceOfKeyword,
  ]).has(node.operatorToken.kind);
}

function isLookupUse(ts, identifier) {
  const parent = identifier.parent;
  if (isComparison(ts, parent) || ts.isCaseClause(parent)) return true;
  if (ts.isElementAccessExpression(parent)) return parent.argumentExpression === identifier;
  if (ts.isCallExpression(parent)) {
    return parent.arguments.includes(identifier) && ts.isPropertyAccessExpression(parent.expression)
      && lookupMethods.has(parent.expression.name.text);
  }
  if (ts.isPropertyAssignment(parent)) return parent.initializer === identifier && machineProperties.has(propertyName(ts, parent.name));
  return false;
}

function isUsedForLookup(ts, declaration) {
  const name = declaration.name.text;
  let scope = declaration.parent;
  while (!ts.isBlock(scope) && !ts.isSourceFile(scope)) scope = scope.parent;
  function search(node) {
    if (ts.isIdentifier(node) && node.text === name && node !== declaration.name && isLookupUse(ts, node)) return true;
    return ts.forEachChild(node, search) === true;
  }
  return search(scope);
}

function insideCodeTag(ts, node) {
  for (let owner = node.parent; owner; owner = owner.parent) {
    if (ts.isJsxElement(owner) && codeTags.has(owner.openingElement.tagName.getText())) return true;
  }
  return false;
}

export function isVisible(ts, node) {
  if (insideCodeTag(ts, node)) return false;
  if (ts.isJsxText(node)) return true;
  for (let owner = node.parent; owner; owner = owner.parent) {
    if (ts.isJsxElement(owner) || ts.isJsxSelfClosingElement(owner)) break;
    if (ts.isVariableDeclaration(owner) && ts.isIdentifier(owner.name)
      && /(?:payload|request|requestBody|requestData|body|response|Variants|Sizes|Classes|Colors|Styles|Attributes)$/i.test(owner.name.text)) return false;
    if (ts.isCallExpression(owner) && owner.expression.getText() === "JSON.stringify") return false;
  }
  let current = node;
  while (current.parent) {
    const parent = current.parent;
    if (ts.isParameter(parent)) return parent.initializer === current && ts.isIdentifier(parent.name)
      && displayProperties.has(parent.name.text);
    if (ts.isBindingElement(parent) && parent.propertyName === current) return false;
    if (ts.isBindingElement(parent) && parent.initializer === current) return ts.isIdentifier(parent.name)
      && displayProperties.has(parent.name.text);
    if (ts.isComputedPropertyName(parent)) return false;
    if (ts.isMethodDeclaration(parent) && parent.name === current) return false;
    if (ts.isTypeNode(parent)) {
      if (!ts.isLiteralTypeNode(parent)) return false;
      let owner = parent;
      while (owner.parent && ts.isUnionTypeNode(owner.parent)) owner = owner.parent;
      return owner.parent !== undefined && ts.isPropertySignature(owner.parent)
        && displayProperties.has(propertyName(ts, owner.parent.name));
    }
    if (ts.isImportDeclaration(parent) || ts.isExportDeclaration(parent)) return false;
    if (ts.isElementAccessExpression(parent) || ts.isCaseClause(parent) || isComparison(ts, parent)) return false;
    if (ts.isArrayLiteralExpression(parent) && ts.isArrayLiteralExpression(parent.parent)
      && parent.elements.length === 2 && parent.elements[0] === current) return false;
    if (ts.isPropertyAssignment(parent)) {
      if (parent.name === current) return false;
      const name = propertyName(ts, parent.name);
      if (machineProperties.has(name)) return false;
      if (displayProperties.has(name)) return true;
      let owner = parent.parent;
      while (owner.parent && (ts.isAsExpression(owner.parent) || ts.isSatisfiesExpression(owner.parent) || ts.isParenthesizedExpression(owner.parent))) owner = owner.parent;
      return owner.parent !== undefined && ts.isVariableDeclaration(owner.parent)
        && ts.isIdentifier(owner.parent.name) && (displayVariable.test(owner.parent.name.text)
          || /(?:^|_)NOUNS?$/.test(owner.parent.name.text));
    }
    if (ts.isJsxAttribute(parent)) return displayProperties.has(parent.name.getText());
    if (ts.isJsxExpression(parent)) {
      if (ts.isJsxAttribute(parent.parent)) return displayProperties.has(parent.parent.name.getText());
      return true;
    }
    if (ts.isVariableDeclaration(parent)) {
      return ts.isIdentifier(parent.name) && displayVariable.test(parent.name.text) && !isUsedForLookup(ts, parent);
    }
    if (ts.isCallExpression(parent)) {
      const call = parent.expression;
      if (ts.isPropertyAccessExpression(call)) {
        const receiver = call.expression.getText();
        if (messageMethods.has(call.name.text) && /(?:toast|message|notification|notifications)/i.test(receiver)) return true;
        if (/(?:labelWithHint|toast|notify|alert|confirm|requiredRule)/i.test(call.name.text)) return true;
      }
      if (ts.isIdentifier(call) && /^(?:alert|confirm|prompt|requiredRule|labelWithHint)$/.test(call.text)) return true;
      return false;
    }
    if (ts.isNewExpression(parent)) {
      if (ts.isIdentifier(parent.expression) && /Error$/.test(parent.expression.text)) return true;
      current = parent;
      continue;
    }
    if (ts.isEnumMember(parent)) return false;
    if (ts.isReturnStatement(parent)) {
      let owner = parent.parent;
      while (owner && !ts.isFunctionLike(owner)) owner = owner.parent;
      if (owner && owner.name && (displayVariable.test(owner.name.getText())
        || /^(?:get|format|render).*(?:Text|Label|Title|Description|Message|DisplayName)$/.test(owner.name.getText()))) return true;
    }
    current = parent;
  }
  return false;
}

function isPluralSuffix(ts, expression) {
  const inner = ts.isJsxExpression(expression) ? expression.expression : expression;
  if (inner === undefined || !ts.isConditionalExpression(inner)) return false;
  return [inner.whenTrue, inner.whenFalse].every((branch) => ts.isStringLiteral(branch) && /^(?:s|es|)$/.test(branch.text));
}

function assertNoPlaceholderSyntax(text, file, node, sourceFile) {
  if (new RegExp(placeholderPattern.source).test(text)) {
    const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
    throw new Error(`${file}:${line + 1}: text already contains placeholder syntax: ${text}`);
  }
}

function jsxTokens(ts, sourceFile, children, counter, consumed) {
  return children.flatMap((child) => {
    if (ts.isJsxText(child)) {
      consumed.add(child);
      const value = jsxTextValue(child.text);
      return value === "" ? [] : [{ type: "text", value }];
    }
    if (ts.isJsxExpression(child)) {
      if (child.expression === undefined) return [];
      if (ts.isStringLiteral(child.expression) || ts.isNoSubstitutionTemplateLiteral(child.expression)) {
        consumed.add(child.expression);
        return [{ type: "text", value: child.expression.text }];
      }
      return [{ type: "expression", index: counter.next++, node: child, optional: isPluralSuffix(ts, child) }];
    }
    if (ts.isJsxElement(child) && !codeTags.has(child.openingElement.tagName.getText(sourceFile))
      && child.children.every((grandchild) => ts.isJsxText(grandchild) || ts.isJsxExpression(grandchild))) {
      const index = counter.next++;
      return [{ type: "element", index, node: child, children: jsxTokens(ts, sourceFile, child.children, counter, consumed) }];
    }
    return [{ type: "opaque", index: counter.next++, node: child }];
  });
}

function serializeTokens(tokens) {
  return tokens.map((token) => {
    if (token.type === "text") return token.value;
    if (token.type === "expression") return `{${token.index}}`;
    if (token.type === "opaque") return `<${token.index}/>`;
    return `<${token.index}>${serializeTokens(token.children)}</${token.index}>`;
  }).join("");
}

function textOf(tokens) {
  return tokens.map((token) => {
    if (token.type === "text") return token.value;
    if (token.type === "element") return textOf(token.children);
    return " ";
  }).join("");
}

function placeholderKinds(tokens) {
  return new Map(tokens.flatMap((token) => {
    if (token.type === "text") return [];
    if (token.type === "element") return [[token.index, token], ...placeholderKinds(token.children)];
    return [[token.index, token]];
  }));
}

function jsxMessage(ts, sourceFile, file, element) {
  if (codeTags.has(element.openingElement.tagName.getText(sourceFile)) || insideCodeTag(ts, element)) return null;
  const directText = element.children.some((child) => ts.isJsxText(child) && /[a-zA-Z]/.test(jsxTextValue(child.text)));
  if (!directText) return null;
  const consumed = new Set();
  const tokens = jsxTokens(ts, sourceFile, element.children, { next: 0 }, consumed);
  if (tokens.every((token) => token.type === "text")) return null;
  if (isCode(normalize(textOf(tokens)))) return null;
  for (const token of tokens) if (token.type === "text") assertNoPlaceholderSyntax(token.value, file, element, sourceFile);
  const raw = serializeTokens(tokens);
  return {
    kind: "jsx", key: normalize(raw), node: element, tokens, consumed,
    placeholders: placeholderKinds(tokens), leading: /^\s/.test(raw), trailing: /\s$/.test(raw),
    start: element.openingElement.end, end: element.closingElement.getStart(sourceFile),
  };
}

function templateMessage(ts, sourceFile, file, template) {
  if (ts.isTaggedTemplateExpression(template.parent) || !isVisible(ts, template)) return null;
  const texts = [template.head.text, ...template.templateSpans.map((span) => span.literal.text)];
  if (isCode(normalize(texts.join(" ")))) return null;
  for (const text of texts) assertNoPlaceholderSyntax(text, file, template, sourceFile);
  const raw = texts.map((text, index) => (index === 0 ? text : `{${index - 1}}${text}`)).join("");
  const placeholders = new Map(template.templateSpans.map((span, index) => [index, {
    type: "expression", index, node: span.expression, optional: isPluralSuffix(ts, span.expression),
  }]));
  return {
    kind: "template", key: normalize(raw), node: template, placeholders,
    leading: /^\s/.test(raw), trailing: /\s$/.test(raw), start: template.getStart(sourceFile), end: template.end,
  };
}

function plainKey(ts, node) {
  if (ts.isJsxText(node)) return normalize(jsxTextValue(node.text));
  if (ts.isStringLiteral(node) && ts.isJsxAttribute(node.parent)) return normalize(decodeJsxEntities(node.text));
  return normalize(node.text);
}

export function inspectSource(ts, file, source) {
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  if (sourceFile.parseDiagnostics.length > 0) {
    const diagnostic = sourceFile.parseDiagnostics[0];
    throw new Error(`${file}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, " ")}`);
  }
  const messages = [];
  function collectMessages(node) {
    const message = ts.isJsxElement(node) ? jsxMessage(ts, sourceFile, file, node)
      : ts.isTemplateExpression(node) ? templateMessage(ts, sourceFile, file, node) : null;
    if (message !== null) messages.push(message);
    ts.forEachChild(node, collectMessages);
  }
  collectMessages(sourceFile);
  const consumed = new Set(messages.flatMap((message) => (message.kind === "jsx" ? [...message.consumed] : [])));
  const plain = [];
  function collectPlain(node) {
    const literal = ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isJsxText(node);
    if (literal && !consumed.has(node) && isVisible(ts, node)) {
      const key = plainKey(ts, node);
      const start = ts.isJsxText(node) ? node.pos : node.getStart(sourceFile);
      if (!isCode(key)) plain.push({ kind: "plain", key, node, start, end: node.end });
    }
    ts.forEachChild(node, collectPlain);
  }
  collectPlain(sourceFile);
  const units = [...plain, ...messages].map((unit) => ({
    ...unit, line: sourceFile.getLineAndCharacterOfPosition(unit.node.getStart(sourceFile)).line + 1,
  }));
  return { sourceFile, units };
}

export function parseTranslation(unit, translation) {
  const root = { children: [] };
  const stack = [root];
  const used = new Set();
  let offset = 0;
  const fail = (reason) => { throw new Error(`Placeholder mismatch (${reason}) in translation of "${unit.key}": ${translation}`); };
  const claim = (index, type) => {
    const placeholder = unit.placeholders.get(index);
    if (placeholder === undefined || placeholder.type !== type || used.has(index)) fail(`unexpected placeholder ${index}`);
    used.add(index);
    return placeholder;
  };
  for (const match of translation.matchAll(placeholderPattern)) {
    const top = stack[stack.length - 1];
    if (match.index > offset) top.children.push({ type: "text", value: translation.slice(offset, match.index) });
    offset = match.index + match[0].length;
    const [, expression, opaque, open, close] = match;
    if (expression !== undefined) {
      top.children.push({ type: "placeholder", placeholder: claim(Number(expression), "expression") });
    } else if (opaque !== undefined) {
      top.children.push({ type: "placeholder", placeholder: claim(Number(opaque), "opaque") });
    } else if (open !== undefined) {
      const node = { type: "element", placeholder: claim(Number(open), "element"), children: [] };
      top.children.push(node);
      stack.push(node);
    } else {
      if (stack.length === 1 || top.placeholder.index !== Number(close)) fail(`unbalanced closing tag ${close}`);
      stack.pop();
    }
  }
  if (offset < translation.length) stack[stack.length - 1].children.push({ type: "text", value: translation.slice(offset) });
  if (stack.length !== 1) fail("unclosed tag");
  const required = [...unit.placeholders.values()].filter((placeholder) => !placeholder.optional);
  if (required.some((placeholder) => !used.has(placeholder.index))) fail("missing placeholder");
  return root.children;
}
