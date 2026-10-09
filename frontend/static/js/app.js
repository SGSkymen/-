
const state = {
  filterType: "default",
  searchQuery: "",
  pageStack: [0],      
  currentCursor: 0,
  limit: 100,
  monthlyChart: null,
  riskChart: null,
  apiReady: false,
};

const CHUNK_SIZE = 50000; 

function whenApiReady() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) {
      resolve();
      return;
    }
    window.addEventListener("pywebviewready", () => resolve(), { once: true });
  });
}

let modalTimer = null;

function showModal(title, message, isError = false, autoCloseMs = 3000) {
  const overlay = document.getElementById("modal-overlay");
  const box = document.getElementById("modal-box");
  const icon = document.getElementById("modal-icon");
  const titleEl = document.getElementById("modal-title");
  const msgEl = document.getElementById("modal-message");

  box.classList.toggle("modal-box--error", isError);
  icon.textContent = isError ? "!" : "✓";
  titleEl.textContent = title;
  msgEl.textContent = message || "";
  overlay.classList.add("visible");

  if (modalTimer) clearTimeout(modalTimer);
  if (autoCloseMs > 0) {
    modalTimer = setTimeout(() => overlay.classList.remove("visible"), autoCloseMs);
  }
}

document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target.id === "modal-overlay") e.target.classList.remove("visible");
});

function setProgressVisible(visible) {
  document.getElementById("progress-overlay").classList.toggle("visible", visible);
  if (!visible) {
    document.getElementById("progress-fill").style.width = "0%";
  }
}

window.onBackendProgress = function (percent, label) {
  setProgressVisible(percent < 100);
  document.getElementById("progress-fill").style.width = `${percent}%`;
  if (label) document.getElementById("progress-label").textContent = label;
  if (percent >= 100) {
    setTimeout(() => setProgressVisible(false), 400);
  }
};
const rub = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 });
const num = new Intl.NumberFormat("ru-RU");

function riskBadgeClass(zone) {
  return { green: "risk-badge--green", yellow: "risk-badge--yellow", red: "risk-badge--red" }[zone] || "risk-badge--yellow";
}
function riskLabel(zone) {
  return { green: "Безопасно", yellow: "Наблюдение", red: "Высокий риск" }[zone] || "—";
}

async function loadDashboard() {
  try {
    const data = await window.pywebview.api.get_dashboard_data();
    document.getElementById("kpi-portfolio").textContent = rub.format(data.total_portfolio || 0);
    document.getElementById("kpi-high-risk").textContent = num.format(data.high_risk_count || 0);
    document.getElementById("kpi-avg-churn").textContent = `${data.avg_churn_percent ?? 0}%`;
    document.getElementById("kpi-accuracy").textContent =
      data.model_accuracy != null ? `${Math.round(data.model_accuracy * 100)}%` : "—";

    updateRiskChart(data.risk_distribution);
  } catch (e) {
    console.error("Ошибка загрузки dashboard:", e);
  }
}

async function loadMonthlyChart() {
  try {
    const data = await window.pywebview.api.get_monthly_stats();
    const ctx = document.getElementById("chart-monthly").getContext("2d");

    if (state.monthlyChart) state.monthlyChart.destroy();
    state.monthlyChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: data.labels,
        datasets: [
          {
            label: "Новые клиенты",
            data: data.new_clients,
            borderColor: "#00aaff",
            backgroundColor: "rgba(0,170,255,0.12)",
            tension: 0.35,
            fill: true,
            yAxisID: "y",
          },
          {
            label: "Средний риск, %",
            data: data.avg_risk,
            borderColor: "#ffaa00",
            backgroundColor: "rgba(255,170,0,0.08)",
            tension: 0.35,
            fill: false,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#ffffff", font: { family: "Segoe UI" } } },
        },
        scales: {
          x: { ticks: { color: "#8fa0dd" }, grid: { color: "rgba(143,160,221,0.08)" } },
          y: { position: "left", ticks: { color: "#8fa0dd" }, grid: { color: "rgba(143,160,221,0.08)" } },
          y1: { position: "right", ticks: { color: "#8fa0dd" }, grid: { drawOnChartArea: false } },
        },
      },
    });
  } catch (e) {
    console.error("Ошибка загрузки графика динамики:", e);
  }
}

function updateRiskChart(distribution) {
  const ctx = document.getElementById("chart-risk").getContext("2d");
  const values = [distribution?.green || 0, distribution?.yellow || 0, distribution?.red || 0];

  if (state.riskChart) {
    state.riskChart.data.datasets[0].data = values;
    state.riskChart.update();
    return;
  }
  state.riskChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["Безопасно", "Наблюдение", "Высокий риск"],
      datasets: [{ data: values, backgroundColor: ["#00cc66", "#ffaa00", "#ff3366"], borderWidth: 0 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: "#ffffff" } } },
    },
  });
}

async function loadClients(cursor = 0) {
  const tbody = document.getElementById("clients-tbody");
  tbody.innerHTML = `<tr><td colspan="7" class="empty-row">Загрузка...</td></tr>`;

  try {
    const result = await window.pywebview.api.get_clients(
      state.filterType, state.searchQuery, 1, state.limit, cursor
    );
    renderClientsTable(result.records);
    updatePaginationIndicator(result, cursor);
    state.currentCursor = cursor;
    document.getElementById("btn-next-page").disabled = !result.has_more;
    document.getElementById("btn-prev-page").disabled = state.pageStack.length <= 1;
  } catch (e) {
    console.error("Ошибка загрузки клиентов:", e);
    tbody.innerHTML = `<tr><td colspan="7" class="empty-row">Ошибка загрузки данных</td></tr>`;
  }
}

function renderClientsTable(records) {
  const tbody = document.getElementById("clients-tbody");
  if (!records || records.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-row">Клиенты не найдены</td></tr>`;
    return;
  }
  tbody.innerHTML = records.map((r) => `
    <tr>
      <td>${r.id}</td>
      <td>${escapeHtml(r.fio || "")}</td>
      <td>${escapeHtml(r.account_number || "")}</td>
      <td>${rub.format(r.deposit_amount || 0)}</td>
      <td>${(r.current_rate ?? "—")}%</td>
      <td>${Math.round((r.churn_probability || 0) * 100)}%</td>
      <td><span class="risk-badge ${riskBadgeClass(r.risk_zone)}">${riskLabel(r.risk_zone)}</span></td>
    </tr>
  `).join("");
}

function updatePaginationIndicator(result, cursor) {
  const shown = result.records.length;
  const rangeStart = shown > 0 ? (state.pageStack.length - 1) * state.limit + 1 : 0;
  const rangeEnd = rangeStart + shown - 1;
  document.getElementById("pagination-indicator").textContent =
    `Показано ${num.format(rangeStart)}-${num.format(rangeEnd)} из ${num.format(result.total)}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

document.getElementById("filter-select").addEventListener("change", (e) => {
  state.filterType = e.target.value;
  state.pageStack = [0];
  loadClients(0);
});

document.getElementById("btn-search").addEventListener("click", runSearch);
document.getElementById("search-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});

function runSearch() {
  state.searchQuery = document.getElementById("search-input").value.trim();
  state.pageStack = [0];
  loadClients(0);
}

document.getElementById("btn-next-page").addEventListener("click", async () => {
  const result = await window.pywebview.api.get_clients(
    state.filterType, state.searchQuery, 1, state.limit, state.currentCursor
  );
  if (result.records.length > 0) {
    const nextCursor = result.records[result.records.length - 1].id;
    state.pageStack.push(nextCursor);
    loadClients(nextCursor);
  }
});

document.getElementById("btn-prev-page").addEventListener("click", () => {
  if (state.pageStack.length <= 1) return;
  state.pageStack.pop();
  const prevCursor = state.pageStack[state.pageStack.length - 1];
  loadClients(prevCursor);
});

const fileInput = document.getElementById("file-input");
let pendingFormat = null;

function bindImportButton(id, format, accept) {
  document.getElementById(id).addEventListener("click", () => {
    pendingFormat = format;
    fileInput.accept = accept;
    fileInput.value = "";
    fileInput.click();
  });
}
bindImportButton("btn-import-json", "json", ".json");
bindImportButton("btn-import-excel", "excel", ".xlsx,.xls");
bindImportButton("btn-import-sqlite", "sqlite", ".db,.sqlite,.sqlite3");
bindImportButton("btn-import-csv", "csv", ".csv");

fileInput.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    window.onBackendProgress(2, "Чтение файла");
    let records;
    switch (pendingFormat) {
      case "json":
        records = await parseJsonFile(file);
        break;
      case "csv":
        records = await parseCsvFile(file);
        break;
      case "excel":
        records = await parseExcelFile(file);
        break;
      case "sqlite":
        records = await parseSqliteFile(file);
        break;
      default:
        throw new Error("Неизвестный формат импорта");
    }
    await sendImport(records);
  } catch (err) {
    console.error(err);
    setProgressVisible(false);
    showModal("Ошибка импорта", err.message || String(err), true);
  }
});

async function sendImport(records) {
  if (!records || records.length === 0) {
    throw new Error("Файл не содержит данных для импорта");
  }
  const totalChunks = Math.ceil(records.length / CHUNK_SIZE);
  let importedTotal = 0;
  let lastMetrics = null;

  for (let i = 0; i < totalChunks; i++) {
    const chunk = records.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
    window.onBackendProgress(
      Math.round(((i + 0.5) / totalChunks) * 90),
      `Импорт части ${i + 1} из ${totalChunks}`
    );
    const result = await window.pywebview.api.import_json(JSON.stringify(chunk));
    if (result.status !== "ok") {
      throw new Error(result.message || "Ошибка на стороне бэкенда");
    }
    importedTotal += result.imported;
    lastMetrics = result.metrics;
  }

  window.onBackendProgress(100, "Готово");
  clearCacheAndRefresh();
  showModal(
    "Импорт завершён",
    `Обработано записей: ${num.format(importedTotal)}. ` +
    (lastMetrics ? `ROC-AUC модели: ${lastMetrics.roc_auc ?? "—"}` : "")
  );
}


function parseJsonFile(file) {
  return file.text().then((text) => {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed : [parsed];
  });
}

function parseCsvFile(file) {
  return file.text().then((text) => {
    const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
    if (lines.length === 0) return [];
    const headers = splitCsvLine(lines[0]);
    const records = [];
    for (let i = 1; i < lines.length; i++) {
      const cells = splitCsvLine(lines[i]);
      const rec = {};
      headers.forEach((h, idx) => { rec[h.trim()] = cells[idx]; });
      records.push(rec);
    }
    return records;
  });
}

function splitCsvLine(line) {
  const result = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes) {
      result.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  result.push(cur);
  return result;
}

function parseExcelFile(file) {
  if (typeof XLSX === "undefined") {
    return Promise.reject(new Error(
      "Модуль чтения Excel (SheetJS) не подключён. Добавьте vendor/xlsx.full.min.js — см. README."
    ));
  }
  return file.arrayBuffer().then((buffer) => {
    const workbook = XLSX.read(buffer, { type: "array" });
    const sheetName = workbook.SheetNames[0];
    const sheet = workbook.Sheets[sheetName];
    return XLSX.utils.sheet_to_json(sheet, { defval: null });
  });
}

function parseSqliteFile(file) {
  if (typeof initSqlJs === "undefined") {
    return Promise.reject(new Error(
      "Модуль чтения SQLite (sql.js) не подключён. Добавьте vendor/sql-wasm.js — см. README."
    ));
  }
  return file.arrayBuffer().then(async (buffer) => {
    const SQL = await initSqlJs({ locateFile: (f) => `../static/js/vendor/${f}` });
    const db = new SQL.Database(new Uint8Array(buffer));
    const tablesRes = db.exec(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    );
    if (!tablesRes.length) return [];
    const tableName = tablesRes[0].values[0][0];
    const res = db.exec(`SELECT * FROM ${tableName};`);
    if (!res.length) return [];
    const [{ columns, values }] = res;
    return values.map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i]])));
  });
}

document.getElementById("btn-retrain").addEventListener("click", retrainModel);

async function retrainModel() {
  try {
    window.onBackendProgress(5, "Запуск переобучения");
    const result = await window.pywebview.api.retrain_model();
    if (result.status !== "ok") {
      throw new Error(result.message);
    }
    window.onBackendProgress(100, "Готово");
    clearCacheAndRefresh();
    showModal(
      "Модель переобучена",
      `Accuracy: ${Math.round(result.metrics.accuracy * 100)}%, ROC-AUC: ${result.metrics.roc_auc ?? "—"}`
    );
  } catch (e) {
    setProgressVisible(false);
    showModal("Ошибка переобучения", e.message || String(e), true);
  }
}

document.getElementById("btn-export").addEventListener("click", async () => {
  try {
    const result = await window.pywebview.api.export_report();
    if (result.status !== "ok") throw new Error(result.message);
    showModal("Экспорт завершён", `Файл сохранён: ${result.path} (${num.format(result.rows)} строк)`);
  } catch (e) {
    showModal("Ошибка экспорта", e.message || String(e), true);
  }
});

async function clearCacheAndRefresh() {
  await window.pywebview.api.clear_cache();
  await refreshAll();
}

async function refreshAll() {
  await Promise.all([loadDashboard(), loadMonthlyChart()]);
  await loadClients(0);
  state.pageStack = [0];
}

window.addEventListener("keydown", (e) => {
  const ctrlOrCmd = e.ctrlKey || e.metaKey;
  if (ctrlOrCmd && e.key.toLowerCase() === "r") {
    e.preventDefault();
    retrainModel();
  } else if (ctrlOrCmd && e.key.toLowerCase() === "i") {
    e.preventDefault();
    document.getElementById("btn-import-json").click();
  } else if (e.key === "F5") {
    e.preventDefault();
    refreshAll();
  }
});

whenApiReady().then(() => {
  state.apiReady = true;
  refreshAll();
});
