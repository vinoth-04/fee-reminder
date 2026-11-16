/* Excel import UI: upload -> match columns -> results.
   If your API returns different field names, change ONLY the normalize*() functions. */
(() => {
  "use strict";

  const API = { preview: "/api/import/preview", confirm: "/api/import/confirm" };
  const MAX_MB = 10;

  // Sync theme
  const savedTheme = localStorage.getItem("gym_theme");
  if (savedTheme) {
    document.documentElement.setAttribute("data-theme", savedTheme);
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    document.documentElement.setAttribute("data-theme", "dark");
  }

  const FIELDS = [
    { key: "name",         label: "Name",         required: true,  help: "Member's full name" },
    { key: "phone",        label: "Phone",        required: true,  help: "WhatsApp number" },
    { key: "monthly_fee",  label: "Monthly fee",  required: true,  help: "Amount paid each month" },
    { key: "joining_date", label: "Joining date", required: false, help: "Used to work out due dates if there is no due date column" },
    { key: "due_date",     label: "Due date",     required: false, help: "Next payment due date" },
    { key: "member_id",    label: "Member ID",    required: false, help: "Keeps IDs the same when you re-import" },
    { key: "status",       label: "Status",       required: false, help: "Active or Inactive" },
  ];
  const FIELD_KEYS = FIELDS.map(f => f.key);

  const $ = id => document.getElementById(id);
  const state = { file: null, token: null, columns: [], rows: [], mapping: {}, total: 0 };

  /* ---------- normalizers: adapt to the API's response shape ---------- */
  function normalizePreview(d) {
    const columns = d.columns || d.headers || d.detected_columns || [];
    const rows = d.preview_rows || d.preview || d.rows || d.sample || [];
    const raw = d.suggested_mapping || d.mapping || d.suggestions || d.column_mapping || {};
    const mapping = {};
    for (const [k, v] of Object.entries(raw)) {
      const val = (v && typeof v === "object") ? (v.column || v.field) : v;
      if (FIELD_KEYS.includes(k)) mapping[k] = val || "";          // field -> column
      else if (FIELD_KEYS.includes(val)) mapping[val] = k;         // column -> field
    }
    return {
      columns,
      rows,
      mapping,
      token: d.upload_id || d.file_id || d.token || d.temp_file || null,
      total: d.total_rows ?? d.row_count ?? rows.length,
    };
  }

  function normalizeResult(d) {
    const rejected = d.rejected_records || d.rejected_rows || d.errors || d.invalid || [];
    return {
      imported: d.imported ?? d.imported_count ?? d.valid_count ?? 0,
      created: d.created, updated: d.updated, unchanged: d.unchanged,
      rejectedCount: d.rejected ?? d.rejected_count ?? d.invalid_count ?? rejected.length,
      rejected: Array.isArray(rejected) ? rejected : [],
    };
  }

  /* ---------- helpers ---------- */
  function showAlert(msg, info = false) {
    const a = $("alert");
    a.textContent = msg; a.hidden = !msg;
    a.classList.toggle("info", info);
  }
  function setStep(n) {
    [1, 2, 3].forEach(i => { $("step" + i).hidden = i !== n; });
    document.querySelectorAll("#steps li").forEach(li => {
      const s = +li.dataset.step;
      li.classList.toggle("on", s === n);
      li.classList.toggle("done", s < n);
    });
    window.scrollTo({ top: 0 });
  }
  function el(tag, props = {}, ...kids) {
    const e = document.createElement(tag);
    Object.assign(e, props);
    kids.forEach(k => e.append(k));
    return e;
  }
  async function readError(res) {
    try {
      const j = await res.json();
      const d = j.detail ?? j.message ?? j;
      return typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg || JSON.stringify(x)).join("; ") : JSON.stringify(d);
    } catch { return `Request failed (${res.status})`; }
  }

  /* ---------- step 1: pick + preview ---------- */
  function pickFile(file) {
    showAlert("");
    if (!file) return;
    if (!/\.(xlsx|csv)$/i.test(file.name)) {
      showAlert("Unsupported file. Use .xlsx or .csv."); return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      showAlert(`File is larger than ${MAX_MB} MB. Split it and try again.`); return;
    }
    state.file = file;
    $("dropTitle").textContent = file.name;
    $("dropHint").textContent = (file.size / 1024).toFixed(1) + " KB";
    $("btnPreview").disabled = false;
  }

  async function doPreview() {
    const btn = $("btnPreview");
    btn.disabled = true; btn.textContent = "Reading…";
    try {
      const fd = new FormData();
      fd.append("file", state.file);
      const res = await fetch(API.preview, { method: "POST", body: fd });
      if (!res.ok) throw new Error(await readError(res));
      const p = normalizePreview(await res.json());
      if (!p.columns.length) throw new Error("No columns found in this file.");
      Object.assign(state, { columns: p.columns, rows: p.rows, token: p.token, total: p.total });
      state.mapping = {};
      FIELD_KEYS.forEach(k => { state.mapping[k] = p.columns.includes(p.mapping[k]) ? p.mapping[k] : ""; });
      renderMapping();
      setStep(2);
    } catch (e) {
      showAlert(e.message);
    } finally {
      btn.textContent = "Read file"; btn.disabled = !state.file;
    }
  }

  /* ---------- step 2: mapping ---------- */
  function renderMapping() {
    const grid = $("mapGrid");
    grid.replaceChildren();
    FIELDS.forEach(f => {
      const sel = el("select", { id: "map_" + f.key });
      sel.append(el("option", { value: "", textContent: f.required ? "Choose a column" : "Not in my file" }));
      state.columns.forEach(c => sel.append(el("option", { value: c, textContent: c })));
      sel.value = state.mapping[f.key] || "";
      sel.addEventListener("change", () => { state.mapping[f.key] = sel.value; refresh(); });

      const box = el("div", { className: "field", id: "box_" + f.key },
        el("label", { htmlFor: sel.id }, f.label,
          el("span", { className: "tag" + (f.required ? " req" : ""), textContent: f.required ? "Required" : "Optional" })),
        sel,
        el("small", { textContent: f.help }));
      grid.append(box);
    });
    $("dueOk").checked = false;
    refresh();
  }

  function validateMapping() {
    const m = state.mapping, issues = [], badKeys = new Set();
    FIELDS.filter(f => f.required && !m[f.key]).forEach(f => { issues.push(`Pick a column for ${f.label}.`); badKeys.add(f.key); });
    if (!m.due_date && !m.joining_date) {
      issues.push("Pick a Due date or a Joining date column. Without one, we can't work out when payment is due.");
      badKeys.add("due_date"); badKeys.add("joining_date");
    }
    const used = {};
    FIELD_KEYS.forEach(k => { if (m[k]) (used[m[k]] ||= []).push(k); });
    Object.entries(used).filter(([, ks]) => ks.length > 1).forEach(([col, ks]) => {
      issues.push(`"${col}" is used for more than one field.`); ks.forEach(k => badKeys.add(k));
    });
    return { issues, badKeys };
  }

  function renderPreviewTable() {
    const colToField = {};
    FIELDS.forEach(f => { if (state.mapping[f.key]) colToField[state.mapping[f.key]] = f.label; });
    const t = $("previewTable");
    t.replaceChildren();
    const head = el("tr");
    state.columns.forEach(c => {
      const th = el("th", {}, c);
      th.append(el("span", { className: "as", textContent: colToField[c] ? "→ " + colToField[c] : "Ignored" }));
      if (!colToField[c]) th.className = "unmapped";
      head.append(th);
    });
    t.append(el("thead", {}, head));
    const body = el("tbody");
    state.rows.slice(0, 10).forEach(r => {
      const tr = el("tr");
      state.columns.forEach(c => {
        const v = Array.isArray(r) ? r[state.columns.indexOf(c)] : r[c];
        const empty = v === null || v === undefined || v === "";
        tr.append(el("td", { textContent: empty ? "empty" : String(v), className: empty ? "empty" : "" }));
      });
      body.append(tr);
    });
    t.append(body);
    $("previewCount").textContent = `(first ${Math.min(10, state.rows.length)} of ${state.total} rows)`;
  }

  function refresh() {
    const { issues, badKeys } = validateMapping();
    FIELD_KEYS.forEach(k => $("box_" + k).classList.toggle("bad", badKeys.has(k)));
    const box = $("mapIssues");
    box.hidden = !issues.length;
    box.replaceChildren();
    if (issues.length) {
      box.append(el("b", { textContent: "Fix before importing:" }));
      const ul = el("ul"); issues.forEach(i => ul.append(el("li", { textContent: i }))); box.append(ul);
    }
    const dueMapped = !!state.mapping.due_date;
    $("dueConfirm").hidden = !dueMapped;
    $("btnImport").disabled = issues.length > 0 || (dueMapped && !$("dueOk").checked);
    renderPreviewTable();
  }

  /* ---------- step 3: confirm + results ---------- */
  async function doImport() {
    const btn = $("btnImport");
    btn.disabled = true; btn.textContent = "Importing…";
    try {
      const mapping = {};
      FIELD_KEYS.forEach(k => { if (state.mapping[k]) mapping[k] = state.mapping[k]; });
      let res;
      if (state.token) {
        res = await fetch(API.confirm, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ upload_id: state.token, token: state.token, mapping, due_date_confirmed: !!mapping.due_date }),
        });
      } else {
        const fd = new FormData();                       // backend has no token: send file again
        fd.append("file", state.file);
        fd.append("mapping", JSON.stringify(mapping));
        res = await fetch(API.confirm, { method: "POST", body: fd });
      }
      if (!res.ok) throw new Error(await readError(res));
      renderResult(normalizeResult(await res.json()));
      showAlert("");
      setStep(3);
    } catch (e) {
      showAlert(e.message);
    } finally {
      btn.textContent = "Import members"; refresh();
    }
  }

  function renderResult(r) {
    $("cntOk").textContent = r.imported;
    $("cntOkLabel").textContent = r.created === undefined ? "imported"
      : `imported (${r.created} new, ${r.updated} updated, ${r.unchanged} unchanged)`;
    $("cntBad").textContent = r.rejectedCount;
    const box = $("rejectBox");
    box.hidden = !r.rejected.length;
    const t = $("rejectTable");
    t.replaceChildren();
    if (!r.rejected.length) return;
    t.append(el("thead", {}, el("tr", {}, el("th", { textContent: "Row" }), el("th", { textContent: "Name" }), el("th", { textContent: "Why it was rejected" }))));
    const body = el("tbody");
    r.rejected.forEach((x, i) => {
      const row = x.row ?? x.row_number ?? x.index ?? i + 1;
      const name = x.name ?? x.record?.name ?? "";
      const reason = x.reason ?? x.error ?? x.errors ?? x.message ?? "";
      body.append(el("tr", {}, el("td", { textContent: row }), el("td", { textContent: name }),
        el("td", { textContent: Array.isArray(reason) ? reason.join("; ") : reason })));
    });
    t.append(body);
  }

  function reset() {
    Object.assign(state, { file: null, token: null, columns: [], rows: [], mapping: {}, total: 0 });
    $("file").value = "";
    $("dropTitle").textContent = "Choose a file or drag it here";
    $("dropHint").textContent = ".xlsx or .csv";
    $("btnPreview").disabled = true;
    showAlert(""); setStep(1);
  }

  /* ---------- wiring ---------- */
  const drop = $("drop");
  $("file").addEventListener("change", e => pickFile(e.target.files[0]));
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => pickFile(e.dataTransfer.files[0]));
  $("btnPreview").addEventListener("click", doPreview);
  $("dueOk").addEventListener("change", refresh);
  $("btnImport").addEventListener("click", doImport);
  $("btnBack").addEventListener("click", reset);
  $("btnAgain").addEventListener("click", reset);

  // Sidebar mobile toggle
  const sidebar = $("sidebar"), backdrop = $("sidebarBackdrop");
  const menuToggle = $("menuToggle"), sidebarClose = $("sidebarClose");
  const closeSidebar = () => {
    if (sidebar) sidebar.classList.remove("sidebar-open");
    if (backdrop) backdrop.classList.remove("active");
  };
  if (menuToggle && sidebar && backdrop) {
    menuToggle.addEventListener("click", () => {
      sidebar.classList.toggle("sidebar-open");
      backdrop.classList.toggle("active");
    });
  }
  if (sidebarClose) sidebarClose.addEventListener("click", closeSidebar);
  if (backdrop) backdrop.addEventListener("click", closeSidebar);

  // Theme toggle in import page
  const themeToggle = $("themeToggle");
  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "light";
      const next = current === "dark" ? "light" : "dark";
      localStorage.setItem("gym_theme", next);
      document.documentElement.setAttribute("data-theme", next);
    });
  }
})();
