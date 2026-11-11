"use strict";

const dimensions = [
  ["frontend_graphics", "前端与图形", "前端"],
  ["systems_performance", "底层系统与性能", "系统"],
  ["algorithms_data", "算法与数据处理", "算法"],
  ["backend_consistency", "后端与状态一致性", "后端"],
  ["maintenance_architecture", "遗留维护与架构演进", "维护"],
  ["math_science", "数学与科学验证", "数学"],
  ["research_evidence", "科研复现与证据审查", "科研"],
  ["computer_use", "电脑操作与工具使用", "操作"],
];
const modes = {
  official: "正式评测",
  pilot: "真实模型试跑",
  platform_validation: "平台验证",
  demo: "演示",
};
const statuses = {
  passed: "通过",
  model_error: "候选产物未通过",
  budget_exhausted: "预算耗尽",
  timeout: "协议内超时",
  unsupported_configuration: "配置不支持",
  environment_error: "环境初始化失败",
  api_error: "外部服务故障",
  verifier_error: "评分器失败",
  cancelled: "已取消",
  missing: "缺测",
  review_pending: "待复核",
};
const typeLabels = {
  android: "Android",
  web: "Web",
  svg: "SVG",
  "3d": "三维建模",
  bugfix: "Bug 修复",
  local_bug: "局部 Bug 修复",
  timing_bug: "时序 Bug 修复",
  certificate: "数学证书",
  idempotency: "幂等与恢复",
};
const $ = (id) => document.getElementById(id);
const scoreText = (score) => score === null ? "N/A" : score.toFixed(2);
const percentText = (rate) => rate === null ? "N/A" : `${(rate * 100).toFixed(1)}%`;
const labels = new Map(dimensions.map(([key, full]) => [key, full]));
const themePreference = window.matchMedia("(prefers-color-scheme: dark)");
const canvas = $("radar");
let rows = [];
let selected = null;

function themeButtonText() {
  const dark = document.documentElement.dataset.theme === "dark"
    || (!document.documentElement.dataset.theme && themePreference.matches);
  $("theme").textContent = dark ? "浅色主题" : "深色主题";
}

try {
  const saved = localStorage.getItem("meguvizbench-theme");
  if (saved === "dark" || saved === "light") document.documentElement.dataset.theme = saved;
} catch {
  // System preference still works when storage is disabled.
}
themeButtonText();
$("theme").addEventListener("click", () => {
  const current = getComputedStyle(document.documentElement).colorScheme;
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("meguvizbench-theme", next);
  } catch {
    // Theme remains active for this page.
  }
  themeButtonText();
  drawRadar();
});
themePreference.addEventListener("change", () => {
  themeButtonText();
  drawRadar();
});

function element(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

function replaceOptions(select, options, initial = options[0]?.[0]) {
  const existing = select.value;
  select.replaceChildren(...options.map(([value, name]) => {
    const option = element("option", name);
    option.value = value;
    return option;
  }));
  select.value = options.some(([value]) => value === existing) ? existing : initial ?? "";
}

function unique(rows, key) {
  return Array.from(new Set(rows.map((row) => row[key]))).sort();
}

function filterRows() {
  replaceOptions($("mode"), Object.entries(modes).filter(([value]) => rows.some((row) => row.mode === value)));
  const mode = $("mode").value;
  let filtered = rows.filter((row) => row.mode === mode);
  for (const [id, key] of [["taskset", "taskset_id"], ["version", "taskset_version"], ["budget", "budget_id"]]) {
    const options = unique(filtered, key).map((value) => [value, value]);
    replaceOptions($(id), [["", "全部"], ...options]);
    if ($(id).value) filtered = filtered.filter((row) => row[key] === $(id).value);
  }

  const available = new Map();
  for (const row of filtered) {
    for (const [key, summary] of Object.entries(row.dimensions)) {
      if (summary.planned_trials) available.set(`dimension:${key}`, labels.get(key));
    }
    for (const type of Object.keys(row.task_types)) available.set(`type:${type}`, typeLabels[type] ?? type);
  }
  replaceOptions($("task-type"), [["", "全部"], ...available.entries()]);
  const taskType = $("task-type").value;
  if (taskType) filtered = filtered.filter((row) => taskSummary(row, taskType)?.planned_trials);

  const cohorts = new Map();
  for (const row of filtered) {
    cohorts.set(row.cohort, `${row.taskset_id} · ${row.tools_profile} · ${row.cohort.slice(0, 8)}`);
  }
  replaceOptions($("cohort"), Array.from(cohorts.entries()));
  const cohort = $("cohort").value;
  const comparable = filtered.filter((row) => row.cohort === cohort);
  const rankable = mode === "official" && comparable.some((row) => row.composite_score !== null);
  if (rankable) comparable.sort((a, b) => (b.composite_score ?? -1) - (a.composite_score ?? -1));
  else comparable.sort((a, b) => a.config_id.localeCompare(b.config_id) || a.run_id.localeCompare(b.run_id));

  const notices = {
    official: "正式评测记录。仅在同一可比组内比较综合分。",
    pilot: "真实模型试跑记录。成绩用于校准。",
    platform_validation: "平台验证记录。参考解和错误对照用于检验评测流程。",
    demo: "演示记录。",
  };
  $("notice").textContent = notices[mode];
  $("compare-context").textContent = rankable
    ? `${comparable.length} 条记录 · 同组按综合分排列`
    : `${comparable.length} 条记录 · 按配置列出`;
  $("type-column").hidden = !taskType;
  $("comparison-rows").replaceChildren(...comparable.map((row) => comparisonRow(row, taskType)));

  const byKey = new Map(comparable.map((row) => [JSON.stringify([row.run_id, row.config_id]), row]));
  replaceOptions($("selected-run"), Array.from(byKey, ([key, row]) => [key, `${row.config_id} · ${row.run_id}`]));
  selected = byKey.get($("selected-run").value) ?? null;
  $("selected-run").onchange = () => {
    selected = byKey.get($("selected-run").value) ?? null;
    renderDetails();
  };
  renderDetails();
}

function taskSummary(row, selectedType) {
  const separator = selectedType.indexOf(":");
  const field = selectedType.slice(0, separator) === "type" ? "task_types" : "dimensions";
  const key = selectedType.slice(separator + 1);
  return Object.hasOwn(row[field], key) ? row[field][key] : undefined;
}

function comparisonRow(row, taskType) {
  const tr = element("tr");
  tr.setAttribute("role", "row");
  const model = element("th", row.model_id);
  model.setAttribute("role", "rowheader");
  model.scope = "row";
  model.className = "model";
  const config = element("span", `${row.agent_id} · ${row.config_id} · ${row.config_digest.slice(0, 8)}`);
  config.className = "muted";
  model.append(config);
  const run = element("td", row.run_id);
  run.setAttribute("role", "cell");
  run.className = "run";
  const state = element("span", row.batch_state === "complete" ? "批次完整" : "暂定批次");
  state.className = "muted";
  run.append(state);
  const time = row.duration_seconds === null ? "未知" : `${row.duration_seconds.toFixed(1)} 秒`;
  const cost = row.cost_usd === null ? "未知" : `$${row.cost_usd.toFixed(row.cost_usd > 0 && row.cost_usd < 0.01 ? 8 : 2)}`;
  const columns = [["综合分", scoreText(row.composite_score)]];
  if (taskType) columns.push(["任务类型得分", scoreText(taskSummary(row, taskType).score)]);
  columns.push(["计分试次", `${row.scored_trials} / ${row.planned_trials}`],
    ["成功率", percentText(row.success_rate)], ["累计用时", time], ["累计费用", cost]);
  tr.append(model, run, ...columns.map(([label, value]) => {
    const cell = element("td", value);
    cell.setAttribute("role", "cell");
    cell.dataset.label = label;
    return cell;
  }));
  return tr;
}

function renderDetails() {
  renderHistory(selected);
  if (!selected) {
    $("dimension-rows").replaceChildren();
    $("statuses").replaceChildren();
    $("detail-context").textContent = "";
    drawRadar();
    return;
  }
  const row = selected;
  const state = row.state === "complete" ? "完整" : "暂定";
  const unknown = row.unknown_cost_attempts ? ` · ${row.unknown_cost_attempts} 次费用未知` : "";
  $("detail-context").textContent = `${state} · 协议 ${row.protocol_version} · ${row.attempts} 次执行尝试${unknown}`;
  $("dimension-rows").replaceChildren(...dimensions.map(([key, label]) => {
    const summary = row.dimensions[key];
    const tr = element("tr");
    const name = element("th", label);
    name.scope = "row";
    const interval = summary.uncertainty;
    const uncertainty = interval.status === "family_bootstrap"
      ? `${scoreText(interval.lower)}–${scoreText(interval.upper)}`
      : summary.score === null ? "N/A" : "证据不足";
    tr.append(
      name,
      element("td", scoreText(summary.score)),
      element("td", percentText(summary.coverage)),
      element("td", `${summary.scored_trials} / ${summary.planned_trials}`),
      element("td", `${summary.scored_families} / ${summary.planned_families}`),
      element("td", uncertainty),
    );
    return tr;
  }));
  const statusItems = Object.entries(statuses).flatMap(([key, label]) => {
    const count = row.failure_types[key];
    return count ? [element("li", `${label} ${count}`)] : [];
  });
  const retryFailures = row.attempts - (row.planned_trials - row.failure_types.missing);
  if (retryFailures) statusItems.push(element("li", `额外执行尝试 ${retryFailures}`));
  $("statuses").replaceChildren(...statusItems);
  drawRadar();
}

function renderHistory(current) {
  const history = current ? rows.filter((row) => row.model_id === current.model_id
    && row.agent_id === current.agent_id && row.mode === current.mode
    && row.taskset_id === current.taskset_id) : [];
  $("history").hidden = history.length < 2;
  $("history-rows").replaceChildren(...history.map((row) => {
    const tr = element("tr");
    const id = element("th", row.run_id);
    id.scope = "row";
    const taskset = element("td", row.taskset_version.slice(0, 12));
    taskset.title = row.taskset_version;
    const same = row.cohort === current.cohort ? "同组" : "不同组";
    tr.append(id, taskset, element("td", `${row.config_id} · ${row.config_digest.slice(0, 8)}`),
      element("td", row.budget_id), element("td", `${same} · ${row.cohort.slice(0, 8)}`),
      element("td", scoreText(row.composite_score)));
    return tr;
  }));
}

function drawRadar() {
  const {width, height} = canvas.getBoundingClientRect();
  if (!width || !height) return;
  const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.round(width * pixelRatio);
  canvas.height = Math.round(height * pixelRatio);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(pixelRatio, pixelRatio);
  const theme = getComputedStyle(document.documentElement);
  const x = width / 2;
  const y = height / 2;
  const radius = Math.min(x - 39, y - 31);
  if (radius <= 0) return;
  function point(index, rate) {
    const angle = index * Math.PI / 4 - Math.PI / 2;
    return [x + Math.cos(angle) * radius * rate, y + Math.sin(angle) * radius * rate];
  }
  function polygon(points) {
    ctx.beginPath();
    ctx.moveTo(...points[0]);
    for (const position of points.slice(1)) ctx.lineTo(...position);
    ctx.closePath();
    ctx.stroke();
  }
  ctx.strokeStyle = theme.getPropertyValue("--line");
  for (const tick of [0.25, 0.5, 0.75, 1]) {
    polygon(dimensions.map((_, index) => point(index, tick)));
  }
  ctx.font = "12px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";
  ctx.fillStyle = theme.getPropertyValue("--muted");
  dimensions.forEach(([, , short], index) => {
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(...point(index, 1));
    ctx.stroke();
    const [labelX, labelY] = point(index, 1 + 24 / radius);
    ctx.fillText(short, labelX, labelY);
  });
  ctx.textAlign = "left";
  for (const tick of [0, 25, 50, 75, 100]) {
    ctx.fillText(String(tick), x + 5, y - radius * tick / 100 + 3);
  }
  if (!selected) return;
  const scores = dimensions.map(([key]) => selected.dimensions[key].score);
  const measured = scores.map((score, index) => score === null ? null : point(index, score / 100));
  ctx.strokeStyle = theme.getPropertyValue("--accent");
  ctx.fillStyle = ctx.strokeStyle;
  ctx.lineWidth = 2;
  measured.forEach((position, index) => {
    if (!position) return;
    const next = measured[(index + 1) % measured.length];
    if (next) {
      ctx.beginPath();
      ctx.moveTo(...position);
      ctx.lineTo(...next);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(...position, 4, 0, Math.PI * 2);
    ctx.fill();
  });
}

for (const id of ["mode", "taskset", "version", "budget", "task-type", "cohort"]) {
  $(id).addEventListener("change", filterRows);
}
new ResizeObserver(drawRadar).observe(canvas);

async function load() {
  try {
    const response = await fetch("data.json", {credentials: "omit"});
    if (!response.ok) throw new Error("data load failed");
    const report = await response.json();
    if (report.schema_version !== "1.0" || !Array.isArray(report.rows)) throw new Error("unknown public schema");
    rows = report.rows;
    if (!rows.length) {
      $("notice").textContent = "暂无公开评测记录。发布脱敏成绩后，结果会在这里显示。";
      return;
    }
    $("results").hidden = false;
    filterRows();
  } catch {
    $("results").hidden = true;
    $("notice").textContent = "公开成绩读取失败。请刷新页面或检查发布的数据文件。";
  }
}

load();
