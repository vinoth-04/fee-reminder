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
      return await fn(...a);
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
    replies: loadReplies,
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

    const dashOverdueEl = $("dashOverdue");
    if (dashOverdueEl) {
      if (s.overdue_count) {
        dashOverdueEl.innerHTML = `⚠️ <strong>${s.overdue_count} overdue payments</strong> requiring follow-up totalling <strong>${inr(s.overdue_amount)}</strong>. <a href="#reminders" class="btn small" style="margin-left:12px; display:inline-flex; align-items:center; vertical-align:middle;">View Reminders &rarr;</a>`;
      } else {
        dashOverdueEl.textContent = "✅ No overdue payments currently recorded.";
      }
    }
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

  /* ---------------- Shared App Settings & Helpers ---------------- */
  let appSettings = {
    gym_name: "",
    default_country_code: "91",
    default_monthly_fee: 1500,
    monthly_fee_options: "500, 800, 1000, 1200, 1500, 2000, 2500, 3000, 5000"
  };

  function addMonthsToDate(dateStr, months) {
    if (!dateStr) return "";
    const parts = dateStr.split("-").map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) return "";
    const [y, m, d] = parts;
    const numMonths = Number(months) || 1;
    const totalMonths = y * 12 + (m - 1) + numMonths;
    const newYear = Math.floor(totalMonths / 12);
    const newMonth = (totalMonths % 12) + 1;
    const daysInNewMonth = new Date(newYear, newMonth, 0).getDate();
    const newDay = Math.min(d, daysInNewMonth);
    const mm = String(newMonth).padStart(2, "0");
    const dd = String(newDay).padStart(2, "0");
    return `${newYear}-${mm}-${dd}`;
  }

  const memberDlg = $("memberDlg"), memberForm = $("memberForm");
  const memberFeeSelect = $("memberFeeSelect");
  const memberFeeInput = $("memberFeeInput");
  const memberJoiningDate = $("memberJoiningDate");
  const memberDurationSelect = $("memberDurationSelect");
  const memberDurationCustom = $("memberDurationCustom");
  const memberDueDate = $("memberDueDate");
  let editingId = null;

  function populateMemberFeeDropdown(selectedValue) {
    if (!memberFeeSelect) return;
    memberFeeSelect.replaceChildren();

    const rawOptions = (appSettings.monthly_fee_options || "500, 800, 1000, 1200, 1500, 2000, 2500, 3000, 5000");
    const opts = rawOptions.split(",").map(s => s.trim()).filter(Boolean);
    const defaultFee = String(appSettings.default_monthly_fee || 1500);

    if (!opts.includes(defaultFee)) {
      opts.push(defaultFee);
    }
    const uniqueOpts = Array.from(new Set(opts)).sort((a, b) => Number(a) - Number(b));

    uniqueOpts.forEach(fee => {
      const isDef = fee === defaultFee;
      memberFeeSelect.append(el("option", {
        value: fee,
        textContent: `₹${Number(fee).toLocaleString("en-IN")}${isDef ? " (Standard)" : ""}`
      }));
    });

    memberFeeSelect.append(el("option", {
      value: "custom",
      textContent: "Custom Amount..."
    }));

    const targetVal = selectedValue != null && selectedValue !== "" ? String(selectedValue) : defaultFee;
    if (uniqueOpts.includes(targetVal)) {
      memberFeeSelect.value = targetVal;
    } else {
      memberFeeSelect.value = "custom";
    }
  }

  function calculateMemberDueDate() {
    if (!memberJoiningDate || !memberDurationSelect || !memberDueDate) return;
    let months = 1;
    if (memberDurationSelect.value === "custom") {
      months = parseInt(memberDurationCustom.value, 10) || 1;
    } else {
      months = parseInt(memberDurationSelect.value, 10) || 1;
    }
    const joiningVal = memberJoiningDate.value || today();
    memberDueDate.value = addMonthsToDate(joiningVal, months);
  }

  if (memberFeeSelect && memberFeeInput) {
    memberFeeSelect.addEventListener("change", () => {
      if (memberFeeSelect.value === "custom") {
        memberFeeInput.focus();
      } else {
        memberFeeInput.value = memberFeeSelect.value;
      }
    });

    memberFeeInput.addEventListener("input", () => {
      const val = memberFeeInput.value.trim();
      const match = Array.from(memberFeeSelect.options).find(o => o.value === val);
      if (match) {
        memberFeeSelect.value = val;
      } else {
        memberFeeSelect.value = "custom";
      }
    });
  }

  if (memberDurationSelect && memberDurationCustom) {
    memberDurationSelect.addEventListener("change", () => {
      if (memberDurationSelect.value === "custom") {
        memberDurationCustom.style.display = "inline-block";
        if (!memberDurationCustom.value) memberDurationCustom.value = "1";
        memberDurationCustom.focus();
      } else {
        memberDurationCustom.style.display = "none";
      }
      calculateMemberDueDate();
    });

    memberDurationCustom.addEventListener("input", calculateMemberDueDate);
  }

  if (memberJoiningDate) {
    memberJoiningDate.addEventListener("change", calculateMemberDueDate);
  }

  function openMemberDialog(m) {
    editingId = m ? m.member_id : null;
    $("memberDlgTitle").textContent = m ? `Edit Member: ${m.name}` : "Add New Member";
    memberForm.reset();
    if (m) {
      ["name", "phone", "monthly_fee", "joining_date", "due_date", "status"].forEach(k => {
        if (memberForm.elements[k]) memberForm.elements[k].value = m[k] ?? "";
      });
      populateMemberFeeDropdown(m.monthly_fee);
      if (memberDurationSelect) memberDurationSelect.value = "1";
      if (memberDurationCustom) memberDurationCustom.style.display = "none";
    } else {
      const defFee = appSettings.default_monthly_fee || 1500;
      populateMemberFeeDropdown(defFee);
      if (memberFeeInput) memberFeeInput.value = defFee;
      if (memberJoiningDate) memberJoiningDate.value = today();
      if (memberDurationSelect) memberDurationSelect.value = "1";
      if (memberDurationCustom) memberDurationCustom.style.display = "none";
      calculateMemberDueDate();
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
      { h: "Mode", f: r => r.payment_mode || "—" },
      { h: "Invoice", f: r => r.payment_status === "Paid" ? btn("Invoice", () => openInvoice(r.payment_id)) : "" }
    ], rows, "No payment records for this member yet.");
    $("histDlg").showModal();
  }

  /* ---------------- Payments ---------------- */
  function openInvoice(paymentId) {
    window.open(`/api/payments/${encodeURIComponent(paymentId)}/invoice`, "_blank");
  }

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
        f: r => r.payment_status === "Pending"
          ? btn("Mark Paid", () => openPayDialog(r), "btn small primary")
          : btn("Invoice", () => openInvoice(r.payment_id))
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

  // Shared by the Payments page and the Reminders banner. Returns true if bills were created.
  const generateBilling = guard(async month => {
    if (!month) { toast("Please select a billing month first.", true); return false; }
    const dry = await api("/api/payments/generate", { method: "POST", body: { month, dry_run: true } });
    if (!dry.created) {
      toast(`Nothing to create for ${niceMonth(month)}. ${dry.already_exists} already exist.`);
      return false;
    }
    const extra = dry.already_exists ? ` (${dry.already_exists} already exist and won't be duplicated)` : "";
    if (!confirm(`Generate ${dry.created} Pending payment records for ${niceMonth(month)}?${extra}`)) return false;

    const res = await api("/api/payments/generate", { method: "POST", body: { month } });
    toast(`Generated ${res.created} pending payments for ${niceMonth(month)}.`);
    return true;
  });

  $("btnGenerate").addEventListener("click", async () => {
    if (await generateBilling($("genMonth").value)) loadPayments();
  });

  const btnDashGen = $("btnDashGenBilling");
  if (btnDashGen) {
    btnDashGen.addEventListener("click", async () => {
      if (await generateBilling(thisMonth())) loadDashboard();
    });
  }

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
    // Open first (inside the click) so the browser doesn't block the popup.
    waQueueManager.openChatInTab(r.whatsapp_link);
    try {
      await prepareLog(r);
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
          waStatus.state === "connected" && (!r.last_log || r.last_log.status !== "Sent")
            ? btn("Send now", () => sendNow(r), "btn small primary", { disabled: !r.phone_valid })
            : null,
          btn("Open WhatsApp", () => openWhatsApp(r), "btn small whatsapp", { disabled: !r.phone_valid }),
          r.last_log && r.last_log.status !== "Sent"
            ? btn("Mark Sent", markLog(r.last_log.reminder_id, "Sent"), "btn small")
            : null
        )
      }
    ];
  }

  let waStatus = { state: "disconnected", installed: true, sent_today: 0, daily_cap: 0 };
  let lastRem = { overdue: [], due_today: [], due_soon: [] };

  async function loadReminders() {
    const [rem, logs, pend] = await Promise.all([
      api("/api/reminders"),
      api("/api/reminders/logs?limit=50"),
      api("/api/payments/pending"),
      refreshWaStatus()
    ]);
    lastRem = rem;
    $("remHint").hidden = pend.length > 0;   // no bills generated yet -> show the banner

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

  $("btnHintGen").addEventListener("click", async () => {
    if (await generateBilling(thisMonth())) loadReminders();
  });

  /* ==========================================================================
     Sequential WhatsApp Messaging Engine (Single Tab Re-use)
     ========================================================================== */
  const WA_TAB = "gym_whatsapp";
  let waWindow = null;

  const prepareLog = r =>
    api(`/api/reminders/prepare/${encodeURIComponent(r.payment_id)}`, { method: "POST" })
      .then(x => { r._log = x.reminder_id; return x; });

  const waQueueManager = {
    queue: [],
    idx: 0,
    state: "idle", // "idle" | "running" | "paused" | "stopped" | "completed"
    completedCount: 0,
    failedCount: 0,
    delayTimer: null,
    delaySeconds: 0,
    isProcessing: false,

    init() {
      const btnStart = $("btnStartMessaging") || $("btnQueue");
      if (btnStart) {
        btnStart.addEventListener("click", () => this.openDashboard());
      }
      const btnModalStart = $("btnMsgStart");
      if (btnModalStart) {
        btnModalStart.addEventListener("click", () => this.startMessaging());
      }
      const btnNext = $("btnMsgNext");
      if (btnNext) {
        btnNext.addEventListener("click", () => this.handleNext());
      }
      const btnPauseResume = $("btnMsgPauseResume");
      if (btnPauseResume) {
        btnPauseResume.addEventListener("click", () => this.togglePauseResume());
      }
      const btnFail = $("btnMsgSkipFail");
      if (btnFail) {
        btnFail.addEventListener("click", () => this.handleSkipFail());
      }
      const btnStop = $("btnMsgStop");
      if (btnStop) {
        btnStop.addEventListener("click", () => this.handleStop());
      }
      const dlg = $("queueDlg");
      if (dlg) {
        dlg.addEventListener("close", () => {
          this.cleanupTimers();
          loadReminders();
        });
      }
    },

    cleanupTimers() {
      if (this.delayTimer) {
        clearInterval(this.delayTimer);
        this.delayTimer = null;
      }
    },

    buildQueue() {
      const raw = [...(lastRem.overdue || []), ...(lastRem.due_today || []), ...(lastRem.due_soon || [])];
      const seen = new Set();
      const list = [];
      for (const r of raw) {
        if (!r.phone_valid) continue;
        if (r.last_log && r.last_log.status === "Sent") continue;
        if (seen.has(r.payment_id)) continue;
        seen.add(r.payment_id);
        list.push(r);
      }
      return list;
    },

    async openDashboard() {
      this.cleanupTimers();
      if (!lastRem || (!lastRem.overdue?.length && !lastRem.due_today?.length && !lastRem.due_soon?.length)) {
        try {
          lastRem = await api("/api/reminders");
        } catch (e) {
          console.error("Could not fetch reminders:", e);
        }
      }
      this.queue = this.buildQueue();
      this.idx = 0;
      this.completedCount = 0;
      this.failedCount = 0;
      this.state = "idle";
      this.isProcessing = false;

      this.updateUI();
      $("queueDlg").showModal();

      if (!this.queue.length) {
        toast("All pending member reminders have already been sent!");
      }
    },

    startMessaging() {
      if (!this.queue.length) {
        toast("No pending recipients to message.", true);
        return;
      }
      this.state = "running";
      this.loadRecipient(this.idx, true);
    },

    openChatInTab(url) {
      if (!url) return;
      try {
        if (waWindow && !waWindow.closed) {
          waWindow.location.href = url;
          waWindow.focus();
          return;
        }
      } catch (e) {
        // Fallback for cross-origin boundary
      }
      waWindow = window.open(url, WA_TAB);
    },

    loadRecipient(index, navigateNow = true) {
      this.cleanupTimers();
      if (index >= this.queue.length) {
        this.finishQueue();
        return;
      }

      this.idx = index;
      const cur = this.queue[this.idx];

      if (navigateNow && cur.whatsapp_link) {
        this.openChatInTab(cur.whatsapp_link);
        prepareLog(cur).catch(e => console.error("Auto prepare log error:", e));
      }

      // Handle WhatsApp loading delays with 3-second countdown before Next is enabled
      this.startLoadingDelay(3);
    },

    startLoadingDelay(seconds) {
      this.delaySeconds = seconds;
      const banner = $("msgDelayBanner");
      const secSpan = $("msgDelaySec");
      const nextBtn = $("btnMsgNext");

      if (nextBtn) nextBtn.disabled = true;
      if (banner) banner.style.display = "flex";
      if (secSpan) secSpan.textContent = String(this.delaySeconds);

      this.updateUI();

      this.delayTimer = setInterval(() => {
        this.delaySeconds--;
        if (this.delaySeconds <= 0) {
          this.cleanupTimers();
          if (banner) banner.style.display = "none";
          if (nextBtn && this.state === "running") nextBtn.disabled = false;
          this.updateUI();
        } else {
          if (secSpan) secSpan.textContent = String(this.delaySeconds);
        }
      }, 1000);
    },

    async handleNext() {
      if (this.isProcessing || this.state !== "running") return;
      if (this.idx >= this.queue.length) return;

      this.isProcessing = true;
      const cur = this.queue[this.idx];

      try {
        await api(`/api/reminders/mark-sent/${encodeURIComponent(cur.payment_id)}`, { method: "POST" });
        this.completedCount++;
        toast(`Marked as sent: ${cur.name}.`);
      } catch (e) {
        toast(`Could not record ${cur.name}: ${e.message}`, true);
        this.failedCount++;
      } finally {
        this.isProcessing = false;
        this.idx++;
        if (this.idx < this.queue.length) {
          this.loadRecipient(this.idx, false);
        } else {
          this.finishQueue();
        }
      }
    },

    async handleSkipFail() {
      if (this.isProcessing || this.state === "idle" || this.state === "completed") return;
      if (this.idx >= this.queue.length) return;

      this.isProcessing = true;
      const cur = this.queue[this.idx];
      const next = this.queue[this.idx + 1];

      if (next && next.whatsapp_link) {
        this.openChatInTab(next.whatsapp_link);
      }

      try {
        if (!cur._log) await prepareLog(cur);
        await api(`/api/reminders/${encodeURIComponent(cur._log)}/status`, {
          method: "PUT",
          body: { status: "Failed" }
        });
        this.failedCount++;
      } catch (e) {
        toast(`Marked failed: ${e.message}`, true);
        this.failedCount++;
      } finally {
        this.isProcessing = false;
        this.idx++;
        if (this.idx < this.queue.length) {
          this.loadRecipient(this.idx, false);
        } else {
          this.finishQueue();
        }
      }
    },

    togglePauseResume() {
      if (this.state === "running") {
        this.state = "paused";
        this.cleanupTimers();
        if ($("msgDelayBanner")) $("msgDelayBanner").style.display = "none";
      } else if (this.state === "paused") {
        this.state = "running";
        const cur = this.queue[this.idx];
        if (cur && cur.whatsapp_link) {
          this.openChatInTab(cur.whatsapp_link);
        }
        this.startLoadingDelay(2);
      }
      this.updateUI();
    },

    handleStop() {
      if (!confirm("Stop sequential WhatsApp messaging session? Completed messages remain saved.")) return;
      this.cleanupTimers();
      this.state = "stopped";
      this.updateUI();
      toast(`Session stopped. ${this.completedCount} completed, ${this.failedCount} failed.`);
      loadReminders();
    },

    finishQueue() {
      this.cleanupTimers();
      this.state = "completed";
      this.updateUI();
      toast(`All done! ${this.completedCount} sent, ${this.failedCount} failed / skipped.`);
      loadReminders();
    },

    updateUI() {
      const total = this.queue.length;
      const processed = Math.min(this.completedCount + this.failedCount, total);
      const pending = Math.max(0, total - processed);
      const percent = total > 0 ? Math.round((processed / total) * 100) : 0;

      // Stats Cards
      if ($("msgTotalCount")) $("msgTotalCount").textContent = String(total);
      if ($("msgCompletedCount")) $("msgCompletedCount").textContent = String(this.completedCount);
      if ($("msgPendingCount")) $("msgPendingCount").textContent = String(pending);
      if ($("msgFailedCount")) $("msgFailedCount").textContent = String(this.failedCount);

      // Progress bar & text
      if ($("msgProgressBar")) $("msgProgressBar").style.width = `${percent}%`;
      if ($("msgProgressText")) {
        $("msgProgressText").textContent = total > 0
          ? `${processed} / ${total} messages completed (${percent}%)`
          : "0 / 0 messages completed";
      }

      // Status Badge
      const badge = $("msgStatusBadge");
      if (badge) {
        if (this.state === "running") {
          badge.textContent = this.delaySeconds > 0 ? "Loading WhatsApp..." : "Waiting for Send";
          badge.className = "chip" + (this.delaySeconds > 0 ? " warn" : "");
        } else if (this.state === "paused") {
          badge.textContent = "Paused";
          badge.className = "chip warn";
        } else if (this.state === "completed") {
          badge.textContent = "Completed";
          badge.className = "chip";
        } else if (this.state === "stopped") {
          badge.textContent = "Stopped";
          badge.className = "chip bad";
        } else {
          badge.textContent = "Ready to start";
          badge.className = "chip";
        }
      }

      // Recipient Card
      const cur = this.queue[this.idx];
      if (cur && (this.state === "running" || this.state === "paused" || this.state === "idle")) {
        if ($("msgRecipientName")) $("msgRecipientName").textContent = cur.name || "Unknown";
        if ($("msgRecipientPhone")) $("msgRecipientPhone").textContent = cur.phone || "—";
        if ($("msgRecipientType")) $("msgRecipientType").textContent = cur.reminder_type || "Reminder";
        if ($("msgRecipientAmount")) $("msgRecipientAmount").textContent = inr(cur.amount);
        if ($("msgMessageBox")) $("msgMessageBox").textContent = cur.message || "—";
      } else if (this.state === "completed") {
        if ($("msgRecipientName")) $("msgRecipientName").textContent = "All Recipients Completed";
        if ($("msgRecipientPhone")) $("msgRecipientPhone").textContent = "✓ Finished";
        if ($("msgRecipientType")) $("msgRecipientType").textContent = "Completed";
        if ($("msgRecipientAmount")) $("msgRecipientAmount").textContent = "—";
        if ($("msgMessageBox")) $("msgMessageBox").textContent = `Successfully completed ${this.completedCount} WhatsApp reminders.`;
      } else if (this.state === "stopped") {
        if ($("msgRecipientName")) $("msgRecipientName").textContent = "Session Stopped";
        if ($("msgRecipientPhone")) $("msgRecipientPhone").textContent = "Stopped";
        if ($("msgRecipientType")) $("msgRecipientType").textContent = "Stopped";
        if ($("msgRecipientAmount")) $("msgRecipientAmount").textContent = "—";
        if ($("msgMessageBox")) $("msgMessageBox").textContent = `Session was stopped at recipient ${this.idx + 1} of ${total}.`;
      } else {
        if ($("msgRecipientName")) $("msgRecipientName").textContent = "No active recipient";
        if ($("msgRecipientPhone")) $("msgRecipientPhone").textContent = "—";
        if ($("msgRecipientType")) $("msgRecipientType").textContent = "—";
        if ($("msgRecipientAmount")) $("msgRecipientAmount").textContent = "₹0";
        if ($("msgMessageBox")) $("msgMessageBox").textContent = "Click 'Start WhatsApp Messaging' to begin.";
      }

      // Instructions
      const inst = $("msgInstructions");
      if (inst) {
        if (this.state === "idle") {
          inst.innerHTML = `Click <strong>Start WhatsApp Messaging</strong> to launch WhatsApp Web in a single tab.`;
        } else if (this.state === "running") {
          if (this.delaySeconds > 0) {
            inst.innerHTML = `WhatsApp tab is loading chat contact... Please wait <strong>${this.delaySeconds}s</strong>.`;
          } else {
            inst.innerHTML = `1. Switch to WhatsApp tab & click <strong>Send</strong>. 2. Click <strong>Next (Sent)</strong> below to advance.`;
          }
        } else if (this.state === "paused") {
          inst.innerHTML = `Messaging is paused. Click <strong>Resume</strong> when ready to continue.`;
        } else if (this.state === "completed") {
          inst.innerHTML = `All messages sent! You may close this dialog.`;
        } else if (this.state === "stopped") {
          inst.innerHTML = `Messaging session stopped.`;
        }
      }

      // Buttons
      const btnStart = $("btnMsgStart");
      const btnNext = $("btnMsgNext");
      const btnPause = $("btnMsgPauseResume");
      const btnFail = $("btnMsgSkipFail");
      const btnStop = $("btnMsgStop");

      if (btnStart) {
        btnStart.style.display = this.state === "idle" ? "inline-flex" : "none";
        btnStart.disabled = total === 0;
      }
      if (btnNext) {
        btnNext.style.display = this.state !== "idle" ? "inline-flex" : "none";
        btnNext.disabled = this.state !== "running" || this.delaySeconds > 0 || this.isProcessing || this.idx >= total;
        const isLast = this.idx === total - 1;
        btnNext.innerHTML = isLast ? "Sent, Finish ✓" : "Next (Sent) &rarr;";
      }
      if (btnPause) {
        btnPause.disabled = this.state !== "running" && this.state !== "paused";
        btnPause.textContent = this.state === "paused" ? "Resume" : "Pause";
      }
      if (btnFail) {
        btnFail.disabled = this.state !== "running" || this.isProcessing || this.idx >= total;
      }
      if (btnStop) {
        btnStop.disabled = this.state !== "running" && this.state !== "paused";
      }
    }
  };

  waQueueManager.init();

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
  const settingDefaultFeeSelect = $("settingDefaultFeeSelect");
  const settingDefaultFeeInput = $("settingDefaultFeeInput");
  const settingFeeOptionsInput = $("settingFeeOptionsInput");

  /* ---- Message templates: placeholders, live preview, reset ---- */
  const TPL_PLACEHOLDERS = ["name", "full_name", "amount", "due_date", "gym_name"];
  let activeTplEl = null;
  const tplEls = () => Array.from(settingsForm.querySelectorAll("textarea[data-tpl]"));

  function renderTpl(text, gymName, fee) {
    const vals = {
      name: "Rahul", full_name: "Rahul Kumar",
      amount: "₹" + Number(fee).toLocaleString("en-IN"),
      due_date: "25 November 2026", gym_name: gymName
    };
    return text.replace(/\{(\w+)\}/g, (m, k) => (k in vals ? vals[k] : m)).trim();
  }

  function updateWaPreview(gymName, feeVal) {
    const preview = $("waPreviewText");
    if (!preview) return;
    const name = gymName || appSettings.gym_name || "Your Gym Name";
    const fee = feeVal || appSettings.default_monthly_fee || 1500;
    const ta = activeTplEl || tplEls()[0];
    if (ta && ta.value.trim()) {
      preview.textContent = renderTpl(ta.value, name, fee);
      if ($("waPreviewKind")) $("waPreviewKind").textContent = ta.dataset.tpl;
    } else {
      preview.textContent = `Hello Rahul,\n\nYour gym membership fee of ₹${Number(fee).toLocaleString("en-IN")} is due on 25 November 2026.\n\nPlease complete your payment on time.\n\nThank you!\n${name}`;
    }
  }

  function currentPreviewArgs() {
    return [gymNameInput ? gymNameInput.value.trim() : "", settingDefaultFeeInput ? settingDefaultFeeInput.value : null];
  }

  const chipBox = $("tplChips");
  if (chipBox) {
    TPL_PLACEHOLDERS.forEach(p => {
      chipBox.appendChild(btn("{" + p + "}", () => {
        const ta = activeTplEl || tplEls()[0];
        if (!ta) return;
        const text = "{" + p + "}";
        const start = ta.selectionStart ?? ta.value.length;
        const end = ta.selectionEnd ?? ta.value.length;
        ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
        ta.focus();
        ta.setSelectionRange(start + text.length, start + text.length);
        updateWaPreview(...currentPreviewArgs());
      }, "btn small"));
    });
  }
  tplEls().forEach(ta => {
    ta.addEventListener("focus", () => { activeTplEl = ta; updateWaPreview(...currentPreviewArgs()); });
    ta.addEventListener("input", () => updateWaPreview(...currentPreviewArgs()));
  });
  if ($("btnTplReset")) {
    $("btnTplReset").addEventListener("click", guard(async () => {
      if (!confirm("Replace all three message templates with the default text? (Press Save settings to keep it.)")) return;
      const defaults = await api("/api/settings/template-defaults");
      tplEls().forEach(ta => {
        const key = ta.name;
        if (defaults[key]) ta.value = defaults[key];
      });
      updateWaPreview(...currentPreviewArgs());
    }));
  }

  if (gymNameInput) {
    gymNameInput.addEventListener("input", e => updateWaPreview(e.target.value.trim(), settingDefaultFeeInput ? settingDefaultFeeInput.value : null));
  }

  if (settingDefaultFeeSelect && settingDefaultFeeInput) {
    settingDefaultFeeSelect.addEventListener("change", () => {
      if (settingDefaultFeeSelect.value === "custom") {
        settingDefaultFeeInput.focus();
      } else {
        settingDefaultFeeInput.value = settingDefaultFeeSelect.value;
        updateWaPreview(gymNameInput ? gymNameInput.value.trim() : "", settingDefaultFeeInput.value);
      }
    });

    settingDefaultFeeInput.addEventListener("input", () => {
      const val = settingDefaultFeeInput.value.trim();
      const match = Array.from(settingDefaultFeeSelect.options).find(o => o.value === val);
      if (match) {
        settingDefaultFeeSelect.value = val;
      } else {
        settingDefaultFeeSelect.value = "custom";
      }
      updateWaPreview(gymNameInput ? gymNameInput.value.trim() : "", val);
    });
  }

  async function loadSettings() {
    const s = await api("/api/settings");
    appSettings = Object.assign({}, appSettings, s);
    Object.entries(s).forEach(([k, v]) => {
      if (settingsForm.elements[k]) settingsForm.elements[k].value = v;
    });

    if (settingDefaultFeeInput && s.default_monthly_fee) {
      settingDefaultFeeInput.value = s.default_monthly_fee;
      const match = Array.from(settingDefaultFeeSelect.options).find(o => o.value === String(s.default_monthly_fee));
      settingDefaultFeeSelect.value = match ? String(s.default_monthly_fee) : "custom";
    }

    updateWaPreview(s.gym_name, s.default_monthly_fee);
    $("settingsErr").hidden = true;
  }

  settingsForm.addEventListener("submit", async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(settingsForm).entries());
    try {
      const updated = await api("/api/settings", { method: "PUT", body });
      appSettings = Object.assign({}, appSettings, updated);
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
      appSettings = Object.assign({}, appSettings, s);
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

  /* ==========================================================================
     WhatsApp link (optional QR link). Click-to-chat keeps working without it.
     ========================================================================== */
  async function refreshWaStatus() {
    try {
      waStatus = await api("/api/whatsapp/status");
    } catch {
      /* keep last known status */
    }
    renderWaBar();
    return waStatus;
  }

  function renderWaBar() {
    const bar = $("waLinkBar");
    if (!bar) return;
    const st = waStatus;
    const chipEl = $("waLinkChip");
    chipEl.replaceChildren();
    const connected = st.state === "connected";
    const label = { connected: "Connected", qr: "Waiting for scan", starting: "Connecting", error: "Problem" }[st.state] || "Not connected";
    const kind = connected ? "" : st.state === "error" ? "bad" : st.state === "disconnected" ? "grey" : "warn";
    chipEl.appendChild(chip(label, kind));

    let text;
    if (!st.installed) text = "Auto-send needs Playwright (pip install playwright). Click-to-chat works without it.";
    else if (connected) text = `Auto-send is on. ${st.sent_today} of ${st.daily_cap} sent today (daily safety limit).`;
    else if (st.state === "error") text = st.message || "Something went wrong. Try connecting again.";
    else if (st.state === "qr" || st.state === "starting") text = st.message || "Connecting...";
    else text = "Not linked. Reminders use click-to-chat (Open WhatsApp). Link the gym's WhatsApp to send automatically.";
    $("waLinkText").textContent = text;

    $("btnAutoSend").hidden = !connected;
    $("btnWaDisconnect").hidden = !connected && !st.has_saved_session;
    const cb = $("btnWaConnect");
    cb.hidden = connected;
    cb.disabled = !st.installed;
    cb.textContent = st.state === "qr" || st.state === "starting" ? "Show QR"
      : st.has_saved_session ? "Reconnect WhatsApp" : "Connect WhatsApp";
  }

  let waPoll = null;
  let waQrShownAt = 0;

  function stopWaPoll() {
    clearInterval(waPoll);
    waPoll = null;
  }

  async function pollWaConnect() {
    const st = await refreshWaStatus();
    const img = $("waQrImg");
    $("waQrMsg").textContent = st.message || "Starting...";
    if (st.state === "qr") {
      if (Date.now() - waQrShownAt > 5000 || img.hidden) {
        img.src = `/api/whatsapp/qr?t=${Date.now()}`;
        waQrShownAt = Date.now();
      }
      img.hidden = false;
    } else {
      img.hidden = true;
    }
    if (st.state === "connected") {
      stopWaPoll();
      $("waConnectDlg").close();
      toast("WhatsApp linked. You can now send automatically.");
      loadReminders();
    } else if (st.state === "error" || st.state === "disconnected") {
      stopWaPoll();
    }
  }

  $("btnWaConnect").addEventListener("click", guard(async () => {
    $("waQrImg").hidden = true;
    $("waQrMsg").textContent = "Starting WhatsApp Web...";
    $("waConnectDlg").showModal();
    await api("/api/whatsapp/connect", { method: "POST" });
    stopWaPoll();
    waPoll = setInterval(pollWaConnect, 2000);
    pollWaConnect();
  }));
  $("waConnectDlg").addEventListener("close", stopWaPoll);

  $("btnWaDisconnect").addEventListener("click", guard(async () => {
    if (!confirm("Unlink WhatsApp from this app? You will need to scan the QR code again to reconnect.")) return;
    await api("/api/whatsapp/disconnect?forget=true", { method: "POST" });
    toast("WhatsApp unlinked. Reminders use click-to-chat.");
    loadReminders();
  }));

  async function sendNow(r) {
    toast(`Sending to ${r.name}...`);
    try {
      const res = await api(`/api/reminders/send/${encodeURIComponent(r.payment_id)}`, { method: "POST" });
      toast(res.success ? `Sent to ${r.name}.` : `Failed for ${r.name}: ${res.error}`, !res.success);
    } catch (e) {
      toast(e.message, true);
    }
    loadReminders();
  }

  let autoSending = false;
  let autoStop = false;

  $("btnAutoSend").addEventListener("click", guard(async () => {
    const button = $("btnAutoSend");
    if (autoSending) {
      autoStop = true;
      button.textContent = "Stopping...";
      return;
    }
    const list = waQueueManager.buildQueue();
    if (!list.length) return toast("No pending reminders to send.", true);
    const room = Math.max(0, waStatus.daily_cap - waStatus.sent_today);
    if (!room) return toast(`Daily auto-send limit (${waStatus.daily_cap}) reached. Use Open WhatsApp for the rest.`, true);
    const batch = list.slice(0, room);
    if (!confirm(`Auto-send ${batch.length} reminder(s) from the linked WhatsApp number?\n\n` +
        "There is a 5-15 second pause between messages, so this takes a few minutes. Keep this page open.")) return;
    autoSending = true;
    autoStop = false;
    button.textContent = "Stop auto-send";
    let ok = 0, bad = 0;
    try {
      for (const r of batch) {
        if (autoStop) break;
        toast(`Sending ${ok + bad + 1} of ${batch.length}: ${r.name}...`);
        try {
          const res = await api(`/api/reminders/send/${encodeURIComponent(r.payment_id)}`, { method: "POST" });
          if (res.success) ok++; else bad++;
        } catch (e) {
          bad++;
          toast(e.message, true);
          break;   // not connected / limit reached: stop instead of failing every row
        }
      }
    } finally {
      autoSending = false;
      button.textContent = "Auto-send all";
      toast(`Auto-send finished: ${ok} sent, ${bad} failed.`, bad > 0);
      await loadReminders();
    }
  }));


  /* ==========================================================================
     Replies inbox (best-effort, read from the linked WhatsApp on demand)
     ========================================================================== */
  const chatPhone = p => {
    const d = String(p || "").replace(/\D/g, "");
    return d.length === 10 ? (appSettings.default_country_code || "91") + d : d;
  };

  async function loadReplies() {
    const [groups] = await Promise.all([api("/api/inbox"), refreshWaStatus()]);
    const connected = waStatus.state === "connected";
    $("btnSyncReplies").disabled = !connected || !!repPoll;
    $("btnSyncReplies").title = connected ? "" : "Connect WhatsApp on the Reminders page first";
    if (!connected && !repPoll) {
      $("repSyncStatus").textContent = "WhatsApp is not connected. Connect it on the Reminders page to fetch replies.";
    }
    renderTable($("repTable"), [
      { h: "Member", f: g => `${g.name} (${g.member_id})`, cls: "nowrap" },
      {
        h: "Latest replies",
        f: g => el("div", {}, ...g.messages.slice(0, 3).map(m =>
          el("div", { style: "margin-bottom:6px;" },
            el("small", { className: "muted", textContent: (m.received_at ? m.received_at + "  " : "") }),
            document.createTextNode(m.body))))
      },
      { h: "Status", f: g => (g.unseen ? chip(`${g.unseen} new`, "warn") : chip("Read", "grey")), cls: "nowrap" },
      {
        h: "Actions",
        cls: "nowrap",
        f: g => el("div", { className: "row-actions" },
          el("a", { className: "btn small whatsapp", href: `https://wa.me/${chatPhone(g.phone)}`, target: "_blank", rel: "noopener", textContent: "Open chat" }),
          g.unseen ? btn("Mark read", guard(async () => {
            await api(`/api/inbox/${encodeURIComponent(g.member_id)}/seen`, { method: "PUT" });
            loadReplies();
          })) : null)
      }
    ], groups, "No replies yet. Send reminders, then click \u201cCheck for replies\u201d.");
  }

  let repPoll = null;

  async function pollReplySync() {
    const st = await api("/api/inbox/sync/status");
    if (st.running) {
      $("repSyncStatus").textContent = `Checking chats: ${st.done} of ${st.total} (${st.new} new so far). Keep this page open.`;
      return;
    }
    clearInterval(repPoll);
    repPoll = null;
    $("repSyncStatus").textContent = st.error
      ? `Stopped: ${st.error}`
      : `Done. ${st.new} new message(s)` + (st.skipped ? `, ${st.skipped} chat(s) skipped` : "") + (st.total ? "." : ". No members were sent a reminder recently.");
    loadReplies();
  }

  $("btnSyncReplies").addEventListener("click", guard(async () => {
    const st = await api("/api/inbox/sync", { method: "POST" });
    $("btnSyncReplies").disabled = true;
    if (!st.running) return pollReplySync();
    clearInterval(repPoll);
    repPoll = setInterval(guard(pollReplySync), 3000);
    pollReplySync();
  }));

  initDateBadge();
  brand();
  route();
})();

