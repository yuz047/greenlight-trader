const DATA_PATHS = ["../data/", "./data/"];

const SEGMENT_COLORS = [
  "#1f3a5f",
  "#256f8f",
  "#2f6a4a",
  "#8b6f2f",
  "#9b2c1f",
  "#5f4b8b",
  "#767a82",
  "#b45309",
  "#0f766e",
];

const CHART_STORE = new Map();
let chartModalReady = false;

async function loadJson(name) {
  let lastError;
  for (const base of DATA_PATHS) {
    try {
      const response = await fetch(base + name, { cache: "no-store" });
      if (response.ok) return response.json();
      lastError = new Error(`${base}${name}: ${response.status}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error(`${name}: unavailable`);
}

function fmtPct(value, digits = 2, signed = false) {
  const num = Number(value || 0);
  const sign = signed && num > 0 ? "+" : "";
  return `${sign}${(num * 100).toFixed(digits)}%`;
}

function fmtUsd(value, digits = 2) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value || 0));
}

function fmtNum(value, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "n/a";
  return num.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function kpi(label, value, sub = "", cls = "") {
  return `
    <div class="kpi-tile">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value ${cls}">${escapeHtml(value)}</div>
      <div class="sub">${escapeHtml(sub)}</div>
    </div>
  `;
}

function renderTable(id, headers, rows) {
  const table = document.getElementById(id);
  if (!table) return;
  table.innerHTML = `
    <thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.length ? rows.join("") : `<tr><td colspan="${headers.length}">No rows</td></tr>`}</tbody>
  `;
}

function riskClass(light) {
  const value = String(light || "").toLowerCase();
  return ["green", "yellow", "red", "black"].includes(value) ? value : "black";
}

function lightLabel(light) {
  return `${String(light || "UNKNOWN").toUpperCase()} LIGHT`;
}

function numberClass(value) {
  const num = Number(value || 0);
  if (num > 0) return "num-pos";
  if (num < 0) return "num-neg";
  return "";
}

function metric(metrics, key) {
  return (metrics.metrics || {})[key] || {};
}

function greenMetric(metrics) {
  return (
    metric(metrics, "learned_weight_Greenlight").total_return != null
      ? metric(metrics, "learned_weight_Greenlight")
      : metric(metrics, "fixed_weight_Greenlight")
  );
}

function latestLog(backtestLogs, backtestResults) {
  const logs = backtestLogs.logs || backtestResults.decision_logs || [];
  return logs.at(-1) || {};
}

function targetRowsFromLog(log, fallbackRows) {
  const target = log.target_allocation || {};
  const rows = Object.entries(target)
    .map(([symbol, weight]) => ({
      symbol,
      weight: Number(weight || 0),
      sleeve: sleeveFor(symbol),
      reason: "latest replay target",
    }))
    .filter((row) => row.weight > 0.0001)
    .sort((a, b) => b.weight - a.weight);
  return rows.length ? rows : fallbackRows;
}

function sleeveFor(symbol) {
  if (symbol === "SPY") return "core";
  if (symbol === "QQQ") return "growth anchor";
  if (["CASH", "SGOV", "SHY"].includes(symbol)) return "defensive";
  if (/^XL|^XBI$|^KRE$|^MTUM$|^QUAL$|^USMV$|^IWM$|^TLT$/.test(symbol)) return "dynamic ETF";
  return "stock alpha";
}

function listSymbols(rows, limit = 6) {
  return (rows || [])
    .slice(0, limit)
    .map((row) => row.symbol)
    .filter(Boolean)
    .join(", ");
}

async function main() {
  const [
    status,
    portfolio,
    scores,
    etfs,
    targets,
    execution,
    benchmarkMetrics,
    benchmarkSnapshots,
    aiReviews,
    backtestResults,
    backtestLogs,
  ] = await Promise.all([
    loadJson("system_status.json"),
    loadJson("portfolio_state.json"),
    loadJson("candidate_scores.json"),
    loadJson("selected_etfs.json"),
    loadJson("target_allocations.json"),
    loadJson("execution_decisions.json"),
    loadJson("benchmark_metrics.json"),
    loadJson("benchmark_snapshots.json"),
    loadJson("ai_reviews.json"),
    loadJson("backtest_results.json"),
    loadJson("backtest_decision_logs.json"),
  ]);

  const log = latestLog(backtestLogs, backtestResults);
  const green = greenMetric(benchmarkMetrics);
  const spy = metric(benchmarkMetrics, "SPY_buy_hold");
  const qqq = metric(benchmarkMetrics, "QQQ_buy_hold");
  const finalEquity = (backtestResults.equity_curve || []).at(-1)?.equity || 0;
  const light = log.risk_light || status.risk_light || "UNKNOWN";
  const lightKey = riskClass(light);
  const dataHealth = status.data_health || log.data_health || {};
  const targetRows = targetRowsFromLog(log, targets.target_allocations || []);
  const targetSum = targetRows.reduce((sum, row) => sum + Number(row.weight || 0), 0);
  const replayLogs = backtestLogs.logs || [];

  document.getElementById("heroNav").textContent = fmtUsd(finalEquity);
  document.getElementById("heroRisk").textContent = light;
  document.getElementById("heroRisk").className = `value ${lightKey === "green" ? "num-pos" : lightKey === "red" ? "num-neg" : ""}`;
  document.getElementById("heroRegime").textContent = log.market_regime || status.market_regime || "n/a";
  document.getElementById("heroExecution").textContent = log.execution_decision || "n/a";
  document.getElementById("allocationDate").textContent = `replay ${log.date || status.latest_run_date || "n/a"}`;
  renderAllocationTrack(targetRows);

  const banner = document.getElementById("statusBanner");
  banner.className = `status-banner ${lightKey}`;
  const dot = document.getElementById("statusDot");
  const dotColor = lightKey === "green" ? "var(--ok)" : lightKey === "yellow" ? "var(--warn)" : lightKey === "red" ? "var(--stop)" : "var(--ink-soft)";
  dot.style.background = dotColor;
  dot.style.boxShadow = `0 0 12px ${lightKey === "green" ? "rgba(47, 106, 74, 0.45)" : lightKey === "yellow" ? "rgba(180, 83, 9, 0.45)" : lightKey === "red" ? "rgba(155, 44, 31, 0.45)" : "rgba(69, 73, 79, 0.35)"}`;
  document.getElementById("statusLabel").textContent = lightLabel(light);
  document.getElementById("statusLabel").className = `status-label ${lightKey}`;
  document.getElementById("statusReason").textContent = statusReason(light, dataHealth, log);
  document.getElementById("statusRegime").textContent = log.market_regime || status.market_regime || "n/a";
  document.getElementById("statusData").innerHTML = dataHealth.ok
    ? `<span class="num-pos">ok</span>${dataHealth.secondary_source_symbols?.length ? ` · ${escapeHtml(dataHealth.secondary_source_symbols.join(", "))}` : ""}`
    : `<span class="num-neg">stale</span>`;
  document.getElementById("statusDate").textContent = `as of ${log.date || status.latest_run_date || "n/a"}`;

  const rolling = backtestResults.rolling_training || {};
  document.getElementById("resultsKpis").innerHTML = [
    kpi("Final equity", fmtUsd(finalEquity), `${backtestResults.invest_start} to ${backtestResults.end_date}`),
    kpi("Total return", fmtPct(green.total_return, 2, true), `SPY ${fmtPct(spy.total_return, 2, true)}`, numberClass(green.total_return)),
    kpi("CAGR", fmtPct(green.CAGR, 2, true), `QQQ ${fmtPct(qqq.CAGR, 2, true)}`, numberClass(green.CAGR)),
    kpi("Sharpe", fmtNum(green.Sharpe), "risk adjusted"),
    kpi("Max drawdown", fmtPct(green.max_drawdown), "absolute", "num-neg"),
    kpi("Alpha vs SPY", fmtPct(green.alpha_vs_SPY, 2, true), "test window", numberClass(green.alpha_vs_SPY)),
    kpi("Initial train", `${backtestResults.train_start} to ${backtestResults.initial_train_end}`, "pre-replay"),
    kpi("Replay start", backtestResults.invest_start || "n/a", "daily loop begins"),
    kpi("Rolling window", `${rolling.window_years || "n/a"} years`, `updates ${rolling.updates || 0}`),
  ].join("");
  renderWeightTable(backtestResults.latest_learned_weights || {});

  document.getElementById("portfolioAsOf").textContent = `replay ${log.date || "n/a"}`;
  document.getElementById("portfolioKpis").innerHTML = [
    kpi("Replay NAV", fmtUsd(finalEquity), `starting ${fmtUsd(5000, 0)}`),
    kpi("Daily paper NAV", fmtUsd(portfolio.nav), `state file ${portfolio.date || "n/a"}`),
    kpi("Cash", fmtUsd(log.portfolio_snapshot?.cash ?? portfolio.cash), "latest replay cash"),
    kpi("Relative DD", fmtPct(log.portfolio_snapshot?.relative_drawdown_pct ?? portfolio.relative_drawdown_pct), "vs SPY mandate", Number(log.portfolio_snapshot?.relative_drawdown_pct || 0) > 0 ? "num-neg" : ""),
    kpi("Data source", dataHealth.source || "n/a", dataHealth.synthetic ? "synthetic" : "Massive-first / tagged fallback"),
    kpi("Memo", memoProvider(aiReviews), "watermarked"),
  ].join("");

  document.getElementById("targetSum").textContent = `sum · ${fmtPct(targetSum, 1)}`;
  renderTable(
    "allocationTable",
    ["Symbol", "Target", "Sleeve", "Reason"],
    targetRows.map(
      (row) => `<tr><td class="symbol">${escapeHtml(row.symbol)}</td><td class="right">${fmtPct(row.weight, 2)}</td><td>${escapeHtml(row.sleeve)}</td><td>${escapeHtml(row.reason)}</td></tr>`
    )
  );

  document.getElementById("executionTurnover").textContent = `latest · ${log.date || "n/a"}`;
  document.getElementById("executionKpis").innerHTML = [
    kpi("Decision", log.execution_decision || "n/a", log.execution_reason || ""),
    kpi("Risk light", light, log.market_regime || "n/a", lightKey === "green" ? "num-pos" : lightKey === "red" ? "num-neg" : ""),
    kpi("Orders", String((log.orders || []).length), "sparse execution"),
    kpi("Last rebalance", log.portfolio_snapshot?.last_rebalance_date || portfolio.last_rebalance_date || "none", "paper portfolio"),
  ].join("");
  renderTable(
    "ordersTable",
    ["Symbol", "Side", "Shares", "Notional"],
    (log.orders || []).map(
      (row) => `<tr><td class="symbol">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.side)}</td><td class="right">${fmtNum(row.shares, 4)}</td><td class="right">${fmtUsd(row.notional)}</td></tr>`
    )
  );

  const selectedEtfs = log.selected_etfs?.length ? log.selected_etfs : etfs.selected_etfs || [];
  const rejectedEtfs = log.rejected_etfs?.length ? log.rejected_etfs : etfs.rejected_etfs || [];
  document.getElementById("etfCount").textContent = `${selectedEtfs.length} selected`;
  renderTable(
    "etfTable",
    ["Symbol", "Score", "Theme", "Reason"],
    selectedEtfs.map(
      (row) => `<tr><td class="symbol">${escapeHtml(row.symbol)}</td><td class="right">${fmtNum(row.score, 3)}</td><td>${escapeHtml(row.theme || row.sector || "")}</td><td>${escapeHtml((row.reasons || []).slice(0, 2).join("; "))}</td></tr>`
    )
  );
  renderTable(
    "rejectedEtfTable",
    ["Symbol", "Theme", "Reason"],
    rejectedEtfs.slice(0, 10).map(
      (row) => `<tr><td class="symbol">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.theme || row.sector || "")}</td><td>${escapeHtml((row.reasons || []).slice(0, 2).join("; "))}</td></tr>`
    )
  );

  const stockRows = log.top_stock_candidates?.length
    ? log.top_stock_candidates
    : (scores.scores || []).filter((row) => row.asset_type === "stock").slice(0, 12);
  renderTable(
    "stockTable",
    ["Symbol", "Final", "Info", "Lead", "Timing", "Wait"],
    stockRows.slice(0, 12).map(
      (row) => `<tr><td class="symbol">${escapeHtml(row.symbol)}</td><td class="right">${fmtNum(row.final_score, 3)}</td><td class="right">${fmtNum(row.information_score, 3)}</td><td class="right">${fmtNum(row.leadership_score, 3)}</td><td class="right">${fmtNum(row.timing_score, 3)}</td><td>${row.wait_flag ? '<span class="pill yellow">wait</span>' : '<span class="pill green">eligible</span>'}</td></tr>`
    )
  );

  renderChart(backtestResults, benchmarkSnapshots);
  renderBenchmarkComparisonChart(backtestResults, benchmarkSnapshots);

  const metricRows = Object.entries(benchmarkMetrics.metrics || {}).map(([name, row]) => {
    return `<tr><td class="symbol">${escapeHtml(name)}</td><td class="right ${numberClass(row.total_return)}">${fmtPct(row.total_return, 2, true)}</td><td class="right">${fmtNum(row.Sharpe, 2)}</td><td class="right num-neg">${fmtPct(row.max_drawdown)}</td><td class="right ${numberClass(row.alpha_vs_SPY)}">${fmtPct(row.alpha_vs_SPY, 2, true)}</td></tr>`;
  });
  renderTable("benchmarkTable", ["Strategy", "Total return", "Sharpe", "Max DD", "Alpha vs SPY"], metricRows);

  document.getElementById("logsCount").textContent = `${replayLogs.length} published`;
  renderTable(
    "logsTable",
    ["Date", "Regime", "Risk", "Decision", "Reason", "ETFs", "Stocks"],
    replayLogs.slice(-14).reverse().map((row) => {
      const cls = riskClass(row.risk_light);
      return `<tr><td class="symbol">${escapeHtml(row.date)}</td><td>${escapeHtml(row.market_regime)}</td><td><span class="pill ${cls}">${escapeHtml(row.risk_light)}</span></td><td>${escapeHtml(row.execution_decision)}</td><td class="text-cell">${escapeHtml(row.execution_reason)}</td><td>${escapeHtml(listSymbols(row.selected_etfs, 5))}</td><td>${escapeHtml(listSymbols(row.top_stock_candidates, 5))}</td></tr>`;
    })
  );

  document.getElementById("memoProvider").textContent = `memo · ${memoProvider(aiReviews)}`;
  const reviews = aiReviews.reviews || [];
  renderTable(
    "aiTable",
    ["Date", "Watermark", "Provider", "Regime", "Risk", "Execution"],
    reviews.slice(-8).reverse().map((row) => {
      const review = row.systematic_review || {};
      const memo = row.memo || "";
      const provider = memo.includes("Model: deepseek-v4-pro") ? "DeepSeek v4 Pro" : memo.includes("Provider: DeepSeek") ? "DeepSeek" : "Template";
      return `<tr><td class="symbol">${escapeHtml(review.as_of || row.date || "")}</td><td>${escapeHtml(row.watermark || review.watermark || "")}</td><td>${provider}</td><td>${escapeHtml(review.market_regime || "")}</td><td>${escapeHtml(review.risk_light || "")}</td><td>${escapeHtml(review.execution_decision || "")}</td></tr>`;
    })
  );

  wireReportLinks();
  setupChartModal();
}

function statusReason(light, dataHealth, log) {
  const parts = [];
  if (dataHealth.ok) parts.push("Massive-first data is healthy");
  if (dataHealth.secondary_source_symbols?.length) parts.push(`${dataHealth.secondary_source_symbols.join(", ")} secondary source`);
  if (log.execution_reason) parts.push(log.execution_reason);
  if (!parts.length) parts.push(`${light} risk state`);
  return parts.join(". ");
}

function memoProvider(aiReviews) {
  const last = (aiReviews.reviews || []).at(-1) || {};
  const memo = last.memo || "";
  if (memo.includes("Model: deepseek-v4-pro")) return "DeepSeek v4 Pro";
  if (memo.includes("Provider: DeepSeek")) return "DeepSeek";
  return "Template";
}

function renderAllocationTrack(rows) {
  const track = document.getElementById("allocationTrack");
  const legend = document.getElementById("allocationLegend");
  track.innerHTML = "";
  legend.innerHTML = "";
  rows.forEach((row, idx) => {
    const weight = Number(row.weight || 0);
    const color = SEGMENT_COLORS[idx % SEGMENT_COLORS.length];
    const segment = document.createElement("div");
    segment.className = "allocation-segment";
    segment.style.width = `${Math.max(weight * 100, 1.5)}%`;
    segment.style.background = color;
    segment.title = `${row.symbol} ${(weight * 100).toFixed(1)}%`;
    track.appendChild(segment);

    const item = document.createElement("span");
    item.textContent = `${row.symbol} ${(weight * 100).toFixed(0)}%`;
    legend.appendChild(item);
  });
}

function renderWeightTable(weights) {
  const rows = [];
  for (const [assetType, values] of Object.entries(weights || {})) {
    for (const [name, value] of Object.entries(values || {})) {
      rows.push(
        `<tr><td class="symbol">${escapeHtml(assetType)}</td><td>${escapeHtml(name)}</td><td class="right">${fmtPct(value, 2)}</td><td>${escapeHtml(assetType === "etf" && Number(value) === 1 ? "watch for overfit" : "rolling learned")}</td></tr>`
      );
    }
  }
  renderTable("weightsTable", ["Sleeve", "Weight", "Value", "Note"], rows);
}

function renderChart(backtestResults, benchmarkSnapshots) {
  const local = (backtestResults.equity_curve || []).map((row) => ({ date: row.date, equity: Number(row.equity || 0) }));
  const spy = benchmarkSnapshots.snapshots?.SPY_buy_hold || [];
  const qqq = benchmarkSnapshots.snapshots?.QQQ_buy_hold || [];
  const labels = local.map((row) => row.date);
  const series = [
    { label: "Greenlight", color: "#1f3a5f", width: 2.4, values: denseSeries(labels, local) },
    { label: "SPY", color: "#767a82", width: 1.6, dash: [6, 5], values: denseSeries(labels, spy) },
    { label: "QQQ", color: "#b45309", width: 1.6, values: denseSeries(labels, qqq) },
  ];
  renderStoredChart("equityChart", "Greenlight vs SPY and QQQ", labels, series);
}

function renderBenchmarkComparisonChart(backtestResults, benchmarkSnapshots) {
  const snapshots = benchmarkSnapshots.snapshots || {};
  const local = (backtestResults.equity_curve || []).map((row) => ({ date: row.date, equity: Number(row.equity || 0) }));
  const labels = local.map((row) => row.date);
  const keys = [
    ["SPY_buy_hold", "SPY", "#767a82", 1.6, [6, 5]],
    ["QQQ_buy_hold", "QQQ", "#b45309", 1.6],
    ["VIX_20_15_strategy", "VIX 20/15", "#9b2c1f", 1.5, [3, 5]],
    ["SPY_200DMA_trend", "SPY 200DMA", "#2f6a4a", 1.6],
    ["dynamic_ETF_momentum_rotation", "ETF rotation", "#256f8f", 1.7],
    ["agent_led_experimental", "Agent track", "#5f4b8b", 1.4, [8, 5]],
  ].filter(([key]) => snapshots[key]?.length);
  const series = [
    { label: "Greenlight", color: "#1f3a5f", width: 2.8, values: denseSeries(labels, local) },
    ...keys.map(([key, label, color, width, dash]) => ({
      label,
      color,
      width,
      dash,
      values: denseSeries(labels, snapshots[key] || []),
    })),
  ];
  const pointCount = document.getElementById("benchmarkPointCount");
  if (pointCount) pointCount.textContent = `${labels.length.toLocaleString("en-US")} daily points`;
  renderStoredChart("benchmarkComparisonChart", "Benchmark comparison", labels, series);
}

function renderStoredChart(canvasId, title, labels, series) {
  CHART_STORE.set(canvasId, { title, labels, series });
  const canvas = document.getElementById(canvasId);
  drawCanvasChart(canvas, labels, series);
  attachChartHover(canvas);
}

function drawCanvasChart(canvas, labels, series) {
  if (!canvas || !labels.length) return;
  canvas.__chartData = { labels, series };
  const parent = canvas.parentElement;
  const width = Math.max(parent?.clientWidth || 640, 320);
  const height = Math.max(parent?.clientHeight || 312, 240);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const pad = { top: 18, right: 18, bottom: series.length > 4 ? 72 : 50, left: 70 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const values = series.flatMap((s) => s.values).filter((v) => Number.isFinite(v));
  if (!values.length) {
    canvas.__chartLayout = null;
    return;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.08;
  const x = (idx) => pad.left + (labels.length <= 1 ? 0 : (idx / (labels.length - 1)) * plotW);
  const y = (value) => pad.top + (1 - (value - yMin) / (yMax - yMin)) * plotH;
  canvas.__chartLayout = { pad, plotW, plotH, width, height };

  ctx.strokeStyle = "#e6e1d3";
  ctx.lineWidth = 1;
  ctx.font = "11px JetBrains Mono, SF Mono, ui-monospace, monospace";
  ctx.fillStyle = "#767a82";
  for (let i = 0; i <= 4; i += 1) {
    const py = pad.top + (plotH / 4) * i;
    const value = yMax - ((yMax - yMin) / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, py);
    ctx.lineTo(width - pad.right, py);
    ctx.stroke();
    ctx.fillText(fmtUsd(value, 0), 8, py + 4);
  }

  const tickCount = 5;
  for (let i = 0; i < tickCount; i += 1) {
    const idx = Math.round((labels.length - 1) * (i / (tickCount - 1)));
    const label = labels[idx];
    ctx.fillText(label.slice(0, 7), x(idx) - 22, height - pad.bottom + 28);
  }

  for (const item of series) {
    ctx.beginPath();
    ctx.strokeStyle = item.color;
    ctx.lineWidth = item.width;
    ctx.setLineDash(item.dash || []);
    let started = false;
    item.values.forEach((value, idx) => {
      if (!Number.isFinite(value)) return;
      if (!started) {
        ctx.moveTo(x(idx), y(value));
        started = true;
      } else {
        ctx.lineTo(x(idx), y(value));
      }
    });
    ctx.stroke();
  }
  ctx.setLineDash([]);

  let legendX = pad.left;
  let legendY = height - (series.length > 4 ? 34 : 12);
  series.forEach((item) => {
    const itemWidth = Math.max(96, ctx.measureText(item.label).width + 34);
    if (legendX + itemWidth > width - pad.right && legendX > pad.left) {
      legendX = pad.left;
      legendY += 17;
    }
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(legendX, legendY);
    ctx.lineTo(legendX + 20, legendY);
    ctx.stroke();
    ctx.fillStyle = "#45494f";
    ctx.fillText(item.label, legendX + 26, legendY + 4);
    legendX += itemWidth + 12;
  });
}

function attachChartHover(canvas) {
  if (!canvas || canvas.dataset.chartHoverReady === "true") return;
  canvas.dataset.chartHoverReady = "true";
  canvas.addEventListener("mousemove", (event) => showChartTooltip(canvas, event));
  canvas.addEventListener("mouseleave", hideChartTooltip);
}

function getChartTooltip() {
  let tooltip = document.querySelector(".chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    document.body.appendChild(tooltip);
  }
  return tooltip;
}

function showChartTooltip(canvas, event) {
  const chart = canvas.__chartData;
  const layout = canvas.__chartLayout;
  if (!chart?.labels?.length || !layout) return;

  const rect = canvas.getBoundingClientRect();
  const localX = Math.min(Math.max(event.clientX - rect.left, layout.pad.left), layout.width - layout.pad.right);
  const ratio = (localX - layout.pad.left) / Math.max(layout.plotW, 1);
  const idx = Math.min(chart.labels.length - 1, Math.max(0, Math.round(ratio * (chart.labels.length - 1))));
  const rows = chart.series
    .map((item) => ({ label: item.label, color: item.color, value: item.values?.[idx] }))
    .filter((row) => Number.isFinite(row.value));

  if (!rows.length) {
    hideChartTooltip();
    return;
  }

  const tooltip = getChartTooltip();
  tooltip.innerHTML = `
    <strong>${escapeHtml(chart.labels[idx])}</strong>
    ${rows
      .map(
        (row) => `<div><span><i style="background:${row.color}"></i>${escapeHtml(row.label)}</span><span>${fmtUsd(row.value, 0)}</span></div>`
      )
      .join("")}
  `;
  tooltip.style.display = "block";
  positionChartTooltip(tooltip, event);
}

function positionChartTooltip(tooltip, event) {
  const margin = 12;
  let left = event.clientX + 14;
  let top = event.clientY + 14;
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
  const box = tooltip.getBoundingClientRect();
  if (box.right > window.innerWidth - margin) left = event.clientX - box.width - 14;
  if (box.bottom > window.innerHeight - margin) top = event.clientY - box.height - 14;
  tooltip.style.left = `${Math.max(margin, left)}px`;
  tooltip.style.top = `${Math.max(margin, top)}px`;
}

function hideChartTooltip() {
  const tooltip = document.querySelector(".chart-tooltip");
  if (tooltip) tooltip.style.display = "none";
}

function denseSeries(labels, rows) {
  const points = (rows || [])
    .map((row) => ({ date: row.date, time: Date.parse(`${row.date}T00:00:00Z`), value: Number(row.equity || 0) }))
    .filter((row) => row.date && Number.isFinite(row.time) && Number.isFinite(row.value))
    .sort((a, b) => a.time - b.time);
  if (!points.length) return labels.map(() => null);

  const exact = new Map(points.map((row) => [row.date, row.value]));
  let idx = 0;
  return labels.map((label) => {
    if (exact.has(label)) return exact.get(label);
    const time = Date.parse(`${label}T00:00:00Z`);
    if (!Number.isFinite(time) || time < points[0].time) return null;
    while (idx < points.length - 2 && points[idx + 1].time < time) idx += 1;
    const prev = points[idx];
    const next = points[idx + 1];
    if (!next || time >= next.time) return prev.value;
    const span = Math.max(next.time - prev.time, 1);
    const t = (time - prev.time) / span;
    return prev.value + (next.value - prev.value) * t;
  });
}

function setupChartModal() {
  if (chartModalReady) return;
  chartModalReady = true;
  const modal = document.getElementById("chartModal");
  const close = document.getElementById("chartModalClose");
  const modalCanvas = document.getElementById("chartModalCanvas");
  const modalTitle = document.getElementById("chartModalTitle");
  if (!modal || !close || !modalCanvas || !modalTitle) return;
  let openChart = null;

  document.querySelectorAll("[data-expand-chart]").forEach((button) => {
    button.addEventListener("click", () => {
      const chart = CHART_STORE.get(button.getAttribute("data-expand-chart"));
      if (!chart) return;
      openChart = chart;
      modalTitle.textContent = chart.title;
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
      requestAnimationFrame(() => {
        drawCanvasChart(modalCanvas, chart.labels, chart.series);
        attachChartHover(modalCanvas);
      });
    });
  });

  const closeModal = () => {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    hideChartTooltip();
  };
  close.addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeModal();
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) closeModal();
  });

  let resizeTimer;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      CHART_STORE.forEach((chart, canvasId) => {
        drawCanvasChart(document.getElementById(canvasId), chart.labels, chart.series);
      });
      if (modal.classList.contains("is-open")) {
        if (openChart) drawCanvasChart(modalCanvas, openChart.labels, openChart.series);
      }
    }, 120);
  });
}

function wireReportLinks() {
  const inWebFolder = window.location.pathname.includes("/web/");
  const dataBase = inWebFolder || window.location.pathname.endsWith("/web")
    ? "../data/"
    : "./data/";
  document.querySelectorAll("[data-artifact]").forEach((link) => {
    link.setAttribute("href", dataBase + link.getAttribute("data-artifact"));
  });
}

function showLoadError(error) {
  document.getElementById("heroNav").textContent = "Data unavailable";
  document.getElementById("heroRisk").textContent = "LOAD ERROR";
  document.getElementById("heroRegime").textContent = "n/a";
  document.getElementById("heroExecution").textContent = "n/a";
  document.getElementById("allocationDate").textContent = "data not loaded";
  document.getElementById("allocationTrack").innerHTML = "";
  document.getElementById("allocationLegend").innerHTML = "";

  const banner = document.getElementById("statusBanner");
  banner.className = "status-banner black";
  document.getElementById("statusLabel").textContent = "DATA LOAD ERROR";
  document.getElementById("statusLabel").className = "status-label black";
  document.getElementById("statusReason").innerHTML = `
    ${escapeHtml(error.message)}. Open this dashboard through a static server or GitHub Pages;
    direct file opens cannot reliably fetch committed data JSON.
  `;
  document.getElementById("statusRegime").textContent = "n/a";
  document.getElementById("statusData").innerHTML = '<span class="num-neg">not loaded</span>';
  document.getElementById("statusDate").textContent = "as of n/a";

  const errorCard = document.createElement("section");
  errorCard.className = "container section-pad";
  errorCard.innerHTML = `
    <div class="dashboard-surface">
      <section class="panel">
        <div class="panel-head">
          <div>
            <div class="eyebrow">Dashboard load help</div>
            <h2>Use a local server for preview</h2>
          </div>
        </div>
        <div class="empty-state">
          From <span class="mono-path">/Users/yunhanzhang/Desktop/works/AI Trader/greenlight-trader</span>, run
          <span class="mono-path">python -m http.server 8765</span>, then open
          <span class="mono-path">http://localhost:8765/web/</span>.
        </div>
      </section>
    </div>
  `;
  document.querySelector("main").prepend(errorCard);
}

main().catch(showLoadError);
