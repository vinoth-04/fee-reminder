/* ==========================================================================
   GymFlow Automation - Admin Dashboard Client
   Modern, vanilla JavaScript (no build required), strictly XSS-safe DOM.
   ========================================================================== */
(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const inr = n => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  const today = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD
  const thisMonth = () => today().slice(0, 7);

  const niceDate = s => {
    if (!s) return "";
    const d = new Date(s + "T00:00:00");
    return isNaN(d) ? s : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };

  const niceMonth = ym => {
    if (!ym) return "";
    const d = new Date(ym + "-01T00:00:00");
    return isNaN(d) ? ym : d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
  };

  function el(tag, props = {}, ...kids) {
    const e = document.createElement(tag);
    Object.assign(e, props);
    kids.forEach(k => {
      if (k != null) {
        if (typeof k === "string" || typeof k === "number") {
          e.append(document.createTextNode(String(k)));
        } else {
          e.append(k);
        }
      }
    });
    return e;
  }

  const chip = (text, kind = "") => {
    const dot = el("span", { className: "chip-dot" });
    return el("span", { className: "chip " + kind }, dot, " " + text);
  };

  const btn = (text, onclick, cls = "btn small", extra = {}) =>
    el("button", { className: cls, textContent: text, onclick, type: "button", ...extra });

  /* ---------------- Toast Notifications ---------------- */
  let toastTimer;
  function toast(msg, bad = false) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast" + (bad ? " bad" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 4500);
  }

  /* ---------------- Theme Management ---------------- */
  function initTheme() {
    const saved = localStorage.getItem("gym_theme");
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = saved || (prefersDark ? "dark" : "light");
    applyTheme(theme);

    const toggleTheme = () => {
      const current = document.documentElement.getAttribute("data-theme") || "light";
      const next = current === "dark" ? "light" : "dark";
      localStorage.setItem("gym_theme", next);
      applyTheme(next);
    };

    const toggle = $("themeToggle");
    if (toggle) toggle.addEventListener("click", toggleTheme);

    const mobileToggle = $("mobileThemeToggle");
    if (mobileToggle) mobileToggle.addEventListener("click", toggleTheme);
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const sun = $("themeIconSun");
    const moon = $("themeIconMoon");
    if (sun && moon) {
      sun.style.display = theme === "dark" ? "block" : "none";
      moon.style.display = theme === "dark" ? "none" : "block";
    }
  }

  /* ---------------- API Helper ---------------- */
  async function api(path, opts = {}) {
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    let res;
    try {
      res = await fetch(path, init);
    } catch {
      throw new Error("Cannot connect to server. Ensure FastAPI backend is running.");
    }
    if (!res.ok) {
      let msg = `Request failed (${res.status})`;
      try {
        const j = await res.json();
        const d = j.detail ?? j.message;
        msg = Array.isArray(d) ? d.map(x => x.msg || JSON.stringify(x)).join("; ") : (typeof d === "string" ? d : msg);
      } catch { /* keep default */ }
      throw new Error(msg);
    }
    return res.json();
  }

  const guard = fn => async (...a) => {
    try {
      await fn(...a);
    } catch (e) {
      toast(e.message, true);
    }
  };

  /* ---------------- Table Builder ---------------- */
  function renderTable(table, cols, rows, emptyText = "Nothing here yet.") {
    table.replaceChildren();
    table.append(el("thead", {}, el("tr", {}, ...cols.map(c => el("th", { textContent: c.h, className: c.cls || "" })))));
    const body = el("tbody");
    if (!rows || !rows.length) {
      body.append(el("tr", {}, el("td", { className: "empty", colSpan: cols.length, textContent: emptyText })));
    } else {
      rows.forEach(r => body.append(el("tr", {}, ...cols.map(c => {
        const v = c.f(r);
        return el("td", { className: c.cls || "" }, v instanceof Node ? v : document.createTextNode(v ?? ""));
      }))));
    }
    table.append(body);
  }

  /* ---------------- Router ---------------- */
  const VIEWS = {
    dashboard: loadDashboard,
    members: loadMembers,
    payments: loadPayments,
    reminders: loadReminders,
    reports: loadReports,
    settings: loadSettings
  };

  function route() {
    const hash = location.hash.slice(1);
    const name = VIEWS[hash] ? hash : "dashboard";
    Object.keys(VIEWS).forEach(v => {
      const section = $("view-" + v);
      if (section) section.hidden = v !== name;
    });
    document.querySelectorAll("#nav a").forEach(a => {
      a.classList.toggle("on", a.getAttribute("href") === "#" + name);
    });
    guard(VIEWS[name])();
  }
  window.addEventListener("hashchange", route);

  /* ---------------- Dashboard ---------------- */
  async function loadDashboard() {
    const [s, rem] = await Promise.all([api("/api/dashboard/summary"), api("/api/reminders")]);

    // Update nav reminder count badge
    const alertCount = (s.due_today_count || 0) + (s.overdue_count || 0);
    const remBadge = $("navRemCount");
    if (remBadge) {
      remBadge.textContent = String(alertCount);
      remBadge.style.display = alertCount > 0 ? "inline-block" : "none";
      remBadge.className = "nav-badge" + (s.overdue_count > 0 ? "" : " warn");
    }

    // Modern Stat Cards
    const totalCollected = s.total_collected || 0;
    const pendingAmount = s.pending_amount || 0;
    const totalMonthExpected = (s.collected_this_month || 0) + pendingAmount;
    const collectionPct = totalMonthExpected > 0 ? Math.round(((s.collected_this_month || 0) / totalMonthExpected) * 100) : 0;

    const cards = [
      {
        label: "Total Members",
        val: s.total_members,
        sub: `${s.active_members} active • ${s.inactive_members} inactive`,
        iconCls: "blue",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'
      },
      {
        label: "Collected (This Month)",
        val: inr(s.collected_this_month),
        sub: `Collection Rate: ${collectionPct}%`,
        cls: "paid",
        iconCls: "emerald",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>'
      },
      {
        label: "Total Collected (All-Time)",
        val: inr(totalCollected),
        sub: "Cumulative lifetime collections",
        cls: "paid",
        iconCls: "emerald",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
      },
      {
        label: "Pending Dues",
        val: inr(pendingAmount),
        sub: s.overdue_count ? `${s.overdue_count} payments overdue` : "All dues on schedule",
        cls: "pending",
        iconCls: "amber",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'
      },
      {
        label: "Due Today",
        val: `${s.due_today_count} (${inr(s.due_today_amount)})`,
        sub: "Awaiting action today",
        cls: "due",
        iconCls: "rose",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
      }
    ];

    const ledger = $("ledger");
    ledger.replaceChildren(...cards.map(c => {
      const card = el("div", { className: "stat-card " + (c.cls || "") });
      const header = el("div", { className: "stat-header" },
        el("span", { className: "stat-label", textContent: c.label }),
        el("div", { className: "stat-icon " + c.iconCls, innerHTML: c.icon })
      );
      const val = el("div", { className: "stat-value", textContent: String(c.val) });
      const footer = el("div", { className: "stat-footer", textContent: c.sub });

      card.append(header, val, footer);
      return card;
    }));

    renderTable($("dashDue"), [
      {
        h: "Member",
        f: r => el("div", { className: "member-cell" },
          el("div", { className: "avatar", textContent: (r.name || "M").charAt(0).toUpperCase() }),
          el("div", { className: "member-info" },
            el("span", { className: "member-name", textContent: r.name }),
            el("span", { className: "member-sub", textContent: r.phone })
          )
        )
      },
      { h: "Amount", f: r => inr(r.amount), cls: "num" },
      {
        h: "Action",
        f: r => btn("Open Reminders", () => { location.hash = "#reminders"; }, "btn small primary")
      }
    ], rem.due_today, "No payments are due today. All caught up!");

    $("dashOverdue").textContent = s.overdue_count
      ? `⚠️ ${s.overdue_count} overdue payments requiring follow-up totalling ${inr(s.overdue_amount)}.`
      : "✅ No overdue payments currently recorded.";
  }

  /* ---------------- Members ---------------- */
  let memberTimer;
  async function loadMembers() {
    const q = encodeURIComponent($("memberQ").value.trim());
    const status = encodeURIComponent($("memberStatus").value);
    const rows = await api(`/api/members?q=${q}&status=${status}`);

    renderTable($("memberTable"), [
      { h: "ID", f: r => el("span", { style: "font-family:var(--font-mono);font-size:0.85rem;font-weight:600;", textContent: r.member_id }), cls: "nowrap" },
      {
        h: "Member",
        f: r => el("div", { className: "member-cell" },
          el("div", { className: "avatar", textContent: (r.name || "M").charAt(0).toUpperCase() }),
          el("div", { className: "member-info" },
            el("span", { className: "member-name", textContent: r.name }),
            el("span", { className: "member-sub", textContent: `Joined ${niceDate(r.joining_date)}` })
          )
        )
      },
      {
        h: "Phone",
        f: r => el("a", {
          href: `https://wa.me/${r.phone}`,
          target: "_blank",
          rel: "noopener",
          style: "color:inherit;text-decoration:none;display:inline-flex;align-items:center;gap:4px;",
          title: "Chat on WhatsApp"
        },
        document.createTextNode(r.phone),
        el("span", { style: "color:var(--whatsapp);font-size:0.9rem;", textContent: "💬" })
        )
      },
      { h: "Monthly Fee", f: r => inr(r.monthly_fee), cls: "num" },
      { h: "Next Due", f: r => niceDate(r.due_date), cls: "nowrap" },
      { h: "Status", f: r => chip(r.status, r.status === "Active" ? "" : "grey") },
      {
        h: "Actions",
        cls: "nowrap",
        f: r => el("div", { className: "row-actions" },
          btn("Edit", () => openMemberDialog(r)),
          btn("History", guard(() => openHistory(r))),
          btn(r.status === "Active" ? "Deactivate" : "Activate", guard(async () => {
            await api(`/api/members/${encodeURIComponent(r.member_id)}`, {
              method: "PUT",
              body: { status: r.status === "Active" ? "Inactive" : "Active" }
            });
            toast(r.status === "Active" ? `${r.name} deactivated.` : `${r.name} activated.`);
            loadMembers();
          }))
        )
      }
    ], rows, "No members found. Add one or import your Excel file.");
  }

  $("memberQ").addEventListener("input", () => {
    clearTimeout(memberTimer);
    memberTimer = setTimeout(guard(loadMembers), 250);
  });
  $("memberStatus").addEventListener("change", guard(loadMembers));

  // CSV Export for Members
  $("btnExportMembers").addEventListener("click", guard(async () => {
    const rows = await api("/api/members");
    if (!rows.length) { toast("No members to export.", true); return; }
    downloadCsv("gym_members.csv", rows);
    toast("Members exported to CSV.");
  }));

  const memberDlg = $("memberDlg"), memberForm = $("memberForm");
  let editingId = null;

  function openMemberDialog(m) {
    editingId = m ? m.member_id : null;
    $("memberDlgTitle").textContent = m ? `Edit Member: ${m.name}` : "Add New Member";
    memberForm.reset();
    if (m) {
      ["name", "phone", "monthly_fee", "joining_date", "due_date", "status"].forEach(k => {
        if (memberForm.elements[k]) memberForm.elements[k].value = m[k] ?? "";
      });
    } else {
      if (memberForm.elements.joining_date) memberForm.elements.joining_date.value = today();
    }
    $("memberErr").hidden = true;
    memberDlg.showModal();
  }

  $("btnAddMember").addEventListener("click", () => openMemberDialog(null));

  memberForm.addEventListener("submit", async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(memberForm).entries());
    try {
      await api(editingId ? `/api/members/${encodeURIComponent(editingId)}` : "/api/members", {
        method: editingId ? "PUT" : "POST",
        body
      });
      memberDlg.close();
      toast(editingId ? "Member updated successfully." : "Member added successfully.");
      loadMembers();
    } catch (err) {
      $("memberErr").textContent = err.message;
      $("memberErr").hidden = false;
    }
  });

  async function openHistory(m) {
    const rows = await api(`/api/members/${encodeURIComponent(m.member_id)}/payments`);
    $("histTitle").textContent = `Payment History: ${m.name} (${m.member_id})`;
    renderTable($("histTable"), [
      { h: "Month", f: r => niceMonth(r.payment_month) },
      { h: "Amount", f: r => inr(r.amount), cls: "num" },
      { h: "Status", f: r => chip(r.payment_status, r.payment_status === "Paid" ? "" : "warn") },
      { h: "Paid on", f: r => niceDate(r.payment_date) },
      { h: "Mode", f: r => r.payment_mode || "—" }
    ], rows, "No payment records for this member yet.");
    $("histDlg").showModal();
  }

  /* ---------------- Payments ---------------- */
  async function loadPayments() {
    if (!$("genMonth").value) $("genMonth").value = thisMonth();
    const qs = new URLSearchParams({
      status: $("payStatus").value,
      month: $("payMonth").value
    });
    const [rows, sum] = await Promise.all([api("/api/payments?" + qs), api("/api/payments/summary")]);
    $("payTotals").textContent = `Total Collected: ${inr(sum.total_collected)} | Total Pending: ${inr(sum.pending_amount)}`;

    renderTable($("payTable"), [
      { h: "ID", f: r => el("span", { style: "font-family:var(--font-mono);font-size:0.85rem;", textContent: r.payment_id }), cls: "nowrap" },
      { h: "Member", f: r => `${r.member_name} (${r.member_id})` },
      { h: "Month", f: r => niceMonth(r.payment_month), cls: "nowrap" },
      { h: "Amount", f: r => inr(r.amount), cls: "num" },
      { h: "Status", f: r => chip(r.payment_status, r.payment_status === "Paid" ? "" : "warn") },
      { h: "Paid on", f: r => niceDate(r.payment_date), cls: "nowrap" },
      { h: "Mode", f: r => r.payment_mode || "—" },
      {
        h: "Action",
        cls: "nowrap",
        f: r => r.payment_status === "Pending" ? btn("Mark Paid", () => openPayDialog(r), "btn small primary") : ""
      }
    ], rows, "No payment records found. Generate billing for a month to begin.");

    renderTable($("paySummary"), [
      { h: "Billing Month", f: r => niceMonth(r.month) },
      { h: "Collected", f: r => inr(r.collected), cls: "num" },
      { h: "Pending", f: r => inr(r.pending), cls: "num" },
      { h: "Paid / Total Members", f: r => `${r.paid_count} / ${r.paid_count + r.pending_count}`, cls: "num" }
    ], sum.months, "No billing months generated yet.");
  }

  $("payStatus").addEventListener("change", guard(loadPayments));
  $("payMonth").addEventListener("change", guard(loadPayments));

  // CSV Export for Payments
  $("btnExportPayments").addEventListener("click", guard(async () => {
    const qs = new URLSearchParams({ status: $("payStatus").value, month: $("payMonth").value });
    const rows = await api("/api/payments?" + qs);
    if (!rows.length) { toast("No payments to export.", true); return; }
    downloadCsv("gym_payments.csv", rows);
    toast("Payments exported to CSV.");
  }));

  $("btnGenerate").addEventListener("click", guard(async () => {
    const month = $("genMonth").value;
    if (!month) { toast("Please select a billing month first.", true); return; }
    const dry = await api("/api/payments/generate", { method: "POST", body: { month, dry_run: true } });
    if (!dry.created) {
      toast(`Nothing to create for ${niceMonth(month)}. All ${dry.already_exists} active members already have billing records.`);
      return;
    }
    const extra = dry.already_exists ? ` (${dry.already_exists} records already exist and won't be duplicated)` : "";
    if (!confirm(`Generate ${dry.created} Pending payment records for ${niceMonth(month)}?${extra}`)) return;

    const res = await api("/api/payments/generate", { method: "POST", body: { month } });
    toast(`Successfully generated ${res.created} pending payments for ${niceMonth(month)}.`);
    loadPayments();
  }));

  const payDlg = $("payDlg"), payForm = $("payForm");
  let payingId = null;

  function openPayDialog(p) {
    payingId = p.payment_id;
    payForm.reset();
    payForm.elements.payment_date.value = today();
    payForm.elements.payment_date.max = today();
    $("payDlgInfo").textContent = `${p.member_name} • Month: ${niceMonth(p.payment_month)} • Amount: ${inr(p.amount)}`;
    $("payErr").hidden = true;
    payDlg.showModal();
  }

  payForm.addEventListener("submit", async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(payForm).entries());
    if (!body.amount) delete body.amount;
    try {
      await api(`/api/payments/${encodeURIComponent(payingId)}/paid`, { method: "PUT", body });
      payDlg.close();
      toast("Payment recorded! Subsequent reminders for this month are stopped.");
      loadPayments();
    } catch (err) {
      $("payErr").textContent = err.message;
      $("payErr").hidden = false;
    }
  });

  /* ---------------- Reminders ---------------- */
  const logChip = l => !l
    ? chip("Not prepared", "grey")
    : chip(l.status, l.status === "Sent" ? "" : l.status === "Failed" ? "bad" : "warn");

  async function openWhatsApp(r) {
    window.open(r.whatsapp_link, "_blank", "noopener");
    try {
      await api(`/api/reminders/prepare/${encodeURIComponent(r.payment_id)}`, { method: "POST" });
    } catch (e) {
      toast(e.message, true);
    }
    loadReminders();
  }

  const markLog = (id, status) => guard(async () => {
    await api(`/api/reminders/${encodeURIComponent(id)}/status`, { method: "PUT", body: { status } });
    toast(`Reminder marked as ${status.toLowerCase()}.`);
    loadReminders();
  });

  function reminderCols() {
    return [
      {
        h: "Member",
        f: r => el("div", { className: "member-cell" },
          el("div", { className: "avatar", textContent: (r.name || "M").charAt(0).toUpperCase() }),
          el("div", { className: "member-info" },
            el("span", { className: "member-name", textContent: r.name }),
            el("span", { className: "member-sub", textContent: r.phone })
          )
        )
      },
      { h: "Amount", f: r => inr(r.amount), cls: "num" },
      {
        h: "Due Date",
        f: r => niceDate(r.due_date) + (r.days_overdue ? ` (${r.days_overdue}d late)` : ""),
        cls: "nowrap"
      },
      {
        h: "Message Preview",
        f: r => el("details", {},
          el("summary", { textContent: r.reminder_type }),
          el("pre", { textContent: r.message })
        )
      },
      {
        h: "Status",
        f: r => r.phone_valid ? logChip(r.last_log) : chip("Invalid Phone", "bad")
      },
      {
        h: "Actions",
        cls: "nowrap",
        f: r => el("div", { className: "row-actions" },
          btn("Open WhatsApp", () => openWhatsApp(r), "btn small whatsapp", { disabled: !r.phone_valid }),
          r.last_log && r.last_log.status !== "Sent"
            ? btn("Mark Sent", markLog(r.last_log.reminder_id, "Sent"), "btn small")
            : null
        )
      }
    ];
  }

  async function loadReminders() {
    const [rem, logs] = await Promise.all([api("/api/reminders"), api("/api/reminders/logs?limit=50")]);
    renderTable($("remOverdue"), reminderCols(), rem.overdue, "No overdue payments.");
    renderTable($("remToday"), reminderCols(), rem.due_today, "No payments are due today.");
    renderTable($("remSoon"), reminderCols(), rem.due_soon, "No payments are due soon.");

    renderTable($("remLogs"), [
      { h: "Date", f: r => niceDate(r.reminder_date), cls: "nowrap" },
      { h: "Member", f: r => r.name || r.member_id },
      { h: "Month", f: r => niceMonth(r.payment_month) },
      { h: "Type", f: r => r.reminder_type },
      { h: "Status", f: r => chip(r.status, r.status === "Sent" ? "" : r.status === "Failed" ? "bad" : "warn") },
      { h: "Sent at", f: r => r.sent_at || "—", cls: "nowrap" },
      {
        h: "Actions",
        cls: "nowrap",
        f: r => el("div", { className: "row-actions" },
          r.status !== "Sent" ? btn("Mark Sent", markLog(r.reminder_id, "Sent")) : null,
          r.status === "Prepared" ? btn("Mark Failed", markLog(r.reminder_id, "Failed")) : null
        )
      }
    ], logs, "No reminder logs recorded yet.");
  }

  $("btnPrepare").addEventListener("click", guard(async () => {
    const r = await api("/api/reminders/prepare", { method: "POST" });
    toast(`${r.prepared.length} reminders prepared` + (r.skipped.length ? `, ${r.skipped.length} skipped.` : "."));
    loadReminders();
  }));

  /* ---------------- Reports ---------------- */
  async function loadReports() {
    const [monthly, pending, rem] = await Promise.all([
      api("/api/reports/monthly"),
      api("/api/reports/pending"),
      api("/api/reports/reminders")
    ]);

    renderTable($("repMonthly"), [
      { h: "Month", f: r => niceMonth(r.month) },
      { h: "Collected", f: r => inr(r.collected), cls: "num" },
      { h: "Pending", f: r => inr(r.pending), cls: "num" },
      { h: "Paid Members", f: r => r.paid_count, cls: "num" },
      { h: "Pending Members", f: r => r.pending_count, cls: "num" }
    ], monthly, "No billing months generated yet.");

    $("repPendingTotal").textContent = `(${pending.count} payments totaling ${inr(pending.total)})`;

    renderTable($("repPending"), [
      { h: "Member", f: r => `${r.member_name} (${r.member_id})` },
      { h: "Phone", f: r => r.phone },
      { h: "Month", f: r => niceMonth(r.payment_month) },
      { h: "Amount", f: r => inr(r.amount), cls: "num" }
    ], pending.rows, "No pending dues outstanding.");

    renderTable($("repReminders"), [
      { h: "Date", f: r => niceDate(r.date) },
      { h: "Prepared", f: r => r.prepared, cls: "num" },
      { h: "Sent", f: r => r.sent, cls: "num" },
      { h: "Failed", f: r => r.failed, cls: "num" },
      { h: "Total", f: r => r.total, cls: "num" }
    ], rem.by_day, "No reminder activity in the last 30 days.");
  }

  /* ---------------- Settings & Live Preview ---------------- */
  const settingsForm = $("settingsForm");
  const gymNameInput = $("settingGymName");

  function updateWaPreview(gymName) {
    const preview = $("waPreviewText");
    if (!preview) return;
    const name = gymName || "Your Gym Name";
    preview.textContent = `Hello Rahul,\n\nYour gym membership fee of ₹1,500 is due on 25 November 2026.\n\nPlease complete your payment on time.\n\nThank you!\n${name}`;
  }

  if (gymNameInput) {
    gymNameInput.addEventListener("input", e => updateWaPreview(e.target.value.trim()));
  }

  async function loadSettings() {
    const s = await api("/api/settings");
    Object.entries(s).forEach(([k, v]) => {
      if (settingsForm.elements[k]) settingsForm.elements[k].value = v;
    });
    updateWaPreview(s.gym_name);
    $("settingsErr").hidden = true;
  }

  settingsForm.addEventListener("submit", async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(settingsForm).entries());
    try {
      await api("/api/settings", { method: "PUT", body });
      $("settingsErr").hidden = true;
      toast("Settings saved successfully.");
      brand();
    } catch (err) {
      $("settingsErr").textContent = err.message;
      $("settingsErr").hidden = false;
    }
  });

  async function brand() {
    try {
      const s = await api("/api/settings");
      const name = s.gym_name || "Gym fees";
      if ($("brand")) $("brand").textContent = name;
      if ($("brandMobile")) $("brandMobile").textContent = name;
      document.title = (s.gym_name ? s.gym_name + " | " : "") + "GymFlow Automation";
    } catch { /* ignore */ }
  }

  function initSidebar() {
    const sidebar = $("sidebar");
    const backdrop = $("sidebarBackdrop");
    const menuToggle = $("menuToggle");
    const sidebarClose = $("sidebarClose");

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

    // Auto-close on nav link click in mobile view
    document.querySelectorAll("#nav a").forEach(a => {
      a.addEventListener("click", () => {
        if (window.innerWidth <= 900) closeSidebar();
      });
    });
  }

  function initDateBadge() {
    const badge = $("currentDateBadge");
    if (!badge) return;
    const now = new Date();
    badge.textContent = now.toLocaleDateString("en-IN", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric"
    });
  }

  /* ---------------- CSV Downloader ---------------- */
  function downloadCsv(filename, rows) {
    if (!rows || !rows.length) return;
    const headers = Object.keys(rows[0]);
    const escape = v => {
      const s = String(v ?? "");
      return s.includes(",") || s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csvContent = [headers.join(","), ...rows.map(r => headers.map(h => escape(r[h])).join(","))].join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  /* ---------------- Shared Initialization ---------------- */
  document.querySelectorAll("dialog [data-close]").forEach(b => {
    b.addEventListener("click", () => b.closest("dialog").close());
  });

  // Close modals on click outside
  document.querySelectorAll("dialog").forEach(d => {
    d.addEventListener("click", e => {
      if (e.target === d) d.close();
    });
  });

  initTheme();
  initSidebar();
  initDateBadge();
  brand();
  route();
})();
