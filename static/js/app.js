/**
 * CareBuddy — SPA client
 */

const STORAGE_KEY = "carebuddy_session_id";
let sessionId = null;
let meta = null;
let calMode = "daily";

// ── Utils ──────────────────────────────────────

function $(sel, root = document) { return root.querySelector(sel); }
function $all(sel, root = document) { return [...root.querySelectorAll(sel)]; }

function ts() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function toast(msg, isError = false) {
  const region = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast " + (isError ? "toast--error" : "toast--ok");
  el.innerHTML = `<span class="toast__icon">${isError ? "✕" : "✓"}</span><span class="toast__msg">${escapeHtml(msg)}</span>`;
  region.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .3s";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 320);
  }, 4500);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (sessionId) headers["X-Session-Id"] = sessionId;
  if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, { ...options, headers });
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { raw: text }; }
  }
  if (!res.ok) {
    const detail = data?.detail
      ? Array.isArray(data.detail) ? data.detail.map(d => d.msg || d).join(" ") : data.detail
      : res.statusText;
    throw new Error(detail || "Request failed");
  }
  return data;
}

function renderMarkdown(text) {
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    const d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
  }
  const raw = marked.parse(text, { breaks: true });
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function escapeAttr(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function kindBadge(kind) {
  return kind === "medicine"
    ? `<span class="badge badge--med">💊 Medicine</span>`
    : `<span class="badge badge--gen">📋 General</span>`;
}

function statusBadge(status) {
  const map = { pending: "badge--amber", completed: "badge--green", skipped: "badge" };
  return `<span class="badge ${map[status] || "badge"}">${escapeHtml(status)}</span>`;
}

// ── Session & boot ─────────────────────────────

async function ensureSession() {
  let sid = localStorage.getItem(STORAGE_KEY);
  const q = sid ? `?session_id=${encodeURIComponent(sid)}` : "";
  const boot = await api("/api/bootstrap" + q);
  sessionId = boot.session_id;
  localStorage.setItem(STORAGE_KEY, sessionId);
  return boot;
}

async function loadMeta() {
  meta = await api("/api/meta");
  const sched = $("#reminder-schedule-type");
  sched.innerHTML = "";
  for (const k of meta.schedule_keys) {
    const opt = document.createElement("option");
    opt.value = k; opt.textContent = meta.schedule_labels[k];
    sched.appendChild(opt);
  }
  const lang = $("#settings-language");
  lang.innerHTML = "";
  for (const L of meta.languages) {
    const opt = document.createElement("option");
    opt.value = L; opt.textContent = L;
    lang.appendChild(opt);
  }
  const rs = $("#settings-reminder-style");
  rs.innerHTML = "";
  for (const s of meta.reminder_styles) {
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = s.charAt(0).toUpperCase() + s.slice(1);
    rs.appendChild(opt);
  }
}

function fillSettingsForm(boot) {
  const f = $("#form-settings");
  f.name.value = boot.persona.name || "";
  f.age.value = boot.persona.age || "";
  f.language.value = boot.persona.language || "English";
  f.timezone.value = boot.persona.timezone || "UTC";
  f.reminder_style.value = boot.persona.reminder_style || "gentle";
  f.openai_api_key.value = "";
  f.notification_channel.value = boot.notification_channel || "email";
  f.notification_destination.value = boot.notification_destination || "";
}

// ── Dashboard ──────────────────────────────────

async function loadDashboard() {
  const d = await api("/api/dashboard");
  const p = d.persona;

  // Profile
  $("#profile-kv").innerHTML = [
    ["Name",  p.name  || '<span class="badge">Not set</span>'],
    ["Age",   p.age   || '<span class="badge">Not set</span>'],
    ["Language", escapeHtml(p.language)],
    ["Style",    escapeHtml(p.reminder_style)],
  ].map(([k,v]) => `<dt>${k}</dt><dd>${v.includes("<") ? v : escapeHtml(v)}</dd>`).join("");

  // Sidebar next
  const sideNext = $("#sidebar-next");
  if (d.next_reminder) {
    const nr = d.next_reminder;
    sideNext.innerHTML = `
      <div class="next-card__label">Next up</div>
      <div class="next-card__title">${escapeHtml(nr.title)}</div>
      <div class="next-card__meta">${escapeHtml(fmtDate(nr.reminder_date))} · ${escapeHtml(nr.reminder_time)}</div>
    `;
  } else {
    sideNext.innerHTML = `<div class="next-card__meta">No upcoming reminders.</div>`;
  }

  // Panel next
  const nextEl = $("#panel-next");
  const nextBadge = $("#next-badge");
  if (d.next_reminder) {
    const nr = d.next_reminder;
    nextBadge.hidden = false;
    nextEl.innerHTML = `
      <div class="nr-title">${escapeHtml(nr.title)}</div>
      <div class="nr-meta">${escapeHtml(fmtDate(nr.reminder_date))} at ${escapeHtml(nr.reminder_time)} · ${kindBadge(nr.kind)}</div>
    `;
  } else {
    nextBadge.hidden = true;
    nextEl.innerHTML = `<div class="nr-empty">No upcoming reminders.</div>`;
  }

  // Today list
  const list = $("#today-list");
  const count = $("#today-count");
  list.innerHTML = "";
  if (!d.today_reminders.length) {
    list.innerHTML = `<li style="color:var(--t-2);font-size:.85rem;padding:.25rem 0">No reminders today.</li>`;
    count.hidden = true;
  } else {
    count.hidden = false;
    count.textContent = d.today_reminders.length;
    count.className = "badge badge--teal";
    for (const r of d.today_reminders) {
      const done = r.status === "completed";
      const li = document.createElement("li");
      li.className = "today-item" + (done ? " today-item--done" : "");
      li.innerHTML = `
        <span class="today-item__time">${escapeHtml(r.reminder_time)}</span>
        <span class="today-item__name">${escapeHtml(r.title)}</span>
        <span class="today-item__kind">${kindBadge(r.kind)}</span>
        <button class="today-item__btn" data-rid="${r.id}" data-done="${done}">
          ${done ? "✓ Done" : "Mark done"}
        </button>
      `;
      li.querySelector("button").addEventListener("click", async (ev) => {
        const btn = ev.currentTarget;
        const isDone = btn.dataset.done === "true";
        const newStatus = isDone ? "pending" : "completed";
        await api(`/api/reminders/${r.id}`, { method: "PATCH", body: JSON.stringify({ status: newStatus }) });
        toast(isDone ? "Marked pending." : "Marked complete.");
        await loadDashboard();
        await loadAllReminders();
        await loadCalendar();
      });
      list.appendChild(li);
    }
  }

  // Summary
  const summaryEl = $("#daily-summary");
  if (d.daily_summary) {
    summaryEl.textContent = d.daily_summary;
  } else {
    summaryEl.textContent = "No summary yet.";
  }
}

// ── Sidebar upcoming ───────────────────────────

async function loadSidebarUpcoming() {
  const rows = (await api("/api/reminders")).slice(0, 5);
  const el = $("#sidebar-upcoming");
  if (!rows.length) {
    el.innerHTML = `<p style="color:var(--t-3);font-size:.8rem;margin:0">No reminders saved yet.</p>`;
    return;
  }
  el.innerHTML = rows.map(r => `
    <div class="sidebar-upitem">
      <div class="sidebar-upitem__title">${escapeHtml(r.title)}</div>
      <div class="sidebar-upitem__meta">${escapeHtml(r.schedule_summary)}</div>
    </div>
  `).join("");
}

// ── Chat ───────────────────────────────────────

async function loadChatHistory() {
  const { messages } = await api("/api/chat/history");
  const log = $("#chat-log");
  log.innerHTML = "";
  for (const m of messages) appendMessage(m.role, m.content, false);
  log.scrollTop = log.scrollHeight;
}

function appendMessage(role, content, scroll = true) {
  const log = $("#chat-log");
  const outer = document.createElement("div");
  outer.className = `msg msg--${role}`;
  const initials = role === "user" ? "You" : "CB";
  const timeStr = ts();
  if (role === "assistant") {
    outer.innerHTML = `
      <div class="msg__avatar">${initials}</div>
      <div class="msg__body">
        <div class="msg__bubble"><div class="md-content">${renderMarkdown(content)}</div></div>
        <span class="msg__time">${timeStr}</span>
      </div>`;
  } else {
    outer.innerHTML = `
      <div class="msg__body">
        <div class="msg__bubble"><div class="md-content">${escapeHtml(content)}</div></div>
        <span class="msg__time">${timeStr}</span>
      </div>
      <div class="msg__avatar">${initials}</div>`;
  }
  log.appendChild(outer);
  if (scroll) log.scrollTop = log.scrollHeight;
}

function appendLoading() {
  const log = $("#chat-log");
  const outer = document.createElement("div");
  outer.className = "msg msg--assistant msg--loading";
  outer.id = "msg-loading";
  outer.innerHTML = `
    <div class="msg__avatar">CB</div>
    <div class="msg__body">
      <div class="msg__bubble">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>
    </div>`;
  log.appendChild(outer);
  log.scrollTop = log.scrollHeight;
  return outer;
}

async function sendChatMessage(text) {
  const loading = appendLoading();
  const btn = $("#chat-send");
  btn.disabled = true;
  try {
    const out = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) });
    loading.remove();
    appendMessage("assistant", out.reply);
  } catch (e) {
    loading.remove();
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

function autoGrow(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 140) + "px";
}

function setupChat() {
  const input = $("#chat-input");
  input.addEventListener("input", () => autoGrow(input));
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      $("#chat-form").requestSubmit();
    }
  });

  $("#chat-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    autoGrow(input);
    appendMessage("user", text);
    await sendChatMessage(text);
  });

  $("#chat-image").addEventListener("change", async (ev) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    appendMessage("user", "📷 Shared a medicine label photo");
    const loading = appendLoading();
    try {
      const res = await fetch("/api/chat/image", {
        method: "POST",
        headers: { "X-Session-Id": sessionId },
        body: fd,
      });
      const data = await res.json();
      loading.remove();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      appendMessage("assistant", data.reply);
    } catch (e) {
      loading.remove();
      toast(e.message, true);
    }
  });
}

// ── Tabs ───────────────────────────────────────

function setupTabs() {
  $all(".tab-btn").forEach(tab => {
    tab.addEventListener("click", () => {
      const id = tab.dataset.tab;
      $all(".tab-btn").forEach(t => {
        t.classList.toggle("is-active", t === tab);
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });
      $all(".tab-pane").forEach(p => {
        const show = p.id === "panel-" + id;
        p.hidden = !show;
        p.classList.toggle("is-visible", show);
      });
      if (id === "calendar") loadCalendar();
      if (id === "reminders") loadAllReminders();
    });
  });
}

// ── Modals ─────────────────────────────────────

function openModal(id) {
  $(id).hidden = false;
  document.body.style.overflow = "hidden";
  $(id).querySelector(".modal__box")?.focus?.();
}

function closeModals() {
  $all(".modal").forEach(m => { m.hidden = true; });
  document.body.style.overflow = "";
}

function setupModals() {
  $all("[data-close-modal]").forEach(el => {
    el.addEventListener("click", closeModals);
  });

  document.addEventListener("keydown", ev => {
    if (ev.key === "Escape") closeModals();
  });

  const openReminder = () => {
    const f = $("#form-reminder");
    f.reset();
    const t = new Date();
    f.reminder_date.value = t.toISOString().slice(0, 10);
    f.reminder_time.value = "09:00";
    openModal("#modal-reminder");
  };

  $("#btn-open-reminder").addEventListener("click", openReminder);
  $("#btn-open-reminder-tab").addEventListener("click", openReminder);

  $("#btn-open-settings").addEventListener("click", async () => {
    const boot = await api("/api/bootstrap?session_id=" + encodeURIComponent(sessionId));
    fillSettingsForm(boot);
    openModal("#modal-settings");
  });

  const btnEditProfile = $("#btn-edit-profile");
  if (btnEditProfile) {
    btnEditProfile.addEventListener("click", async () => {
      const boot = await api("/api/bootstrap?session_id=" + encodeURIComponent(sessionId));
      fillSettingsForm(boot);
      openModal("#modal-settings");
    });
  }

  $("#form-reminder").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    const payload = {
      kind: f.kind.value,
      title: f.title.value.trim(),
      reminder_date: f.reminder_date.value,
      reminder_time: f.reminder_time.value,
      place: f.place.value.trim(),
      notes: f.notes.value.trim(),
      schedule_type: f.schedule_type.value,
      schedule_detail: f.schedule_detail.value.trim(),
    };
    try {
      await api("/api/reminders", { method: "POST", body: JSON.stringify(payload) });
      toast("Reminder saved.");
      closeModals();
      await loadDashboard();
      await loadAllReminders();
      await loadCalendar();
      await loadSidebarUpcoming();
    } catch (e) {
      toast(e.message, true);
    }
  });

  $("#form-settings").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    const payload = {
      name: f.name.value.trim(),
      age: f.age.value.trim(),
      language: f.language.value,
      timezone: f.timezone.value.trim() || "UTC",
      reminder_style: f.reminder_style.value,
      notification_channel: f.notification_channel.value,
      notification_destination: f.notification_destination.value.trim(),
    };
    const key = f.openai_api_key.value.trim();
    if (key) payload.openai_api_key = key;
    try {
      await api("/api/persona", { method: "PUT", body: JSON.stringify(payload) });
      toast("Settings saved.");
      closeModals();
      await loadDashboard();
    } catch (e) {
      toast(e.message, true);
    }
  });
}

// ── Reminder cards ─────────────────────────────

function reminderCard(r, prefix) {
  const uid = `${prefix}-${r.id}`;
  return `
    <details class="rem-card" data-id="${r.id}">
      <summary>
        ${kindBadge(r.kind)}
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(r.title)}</span>
        <span style="font-size:.78rem;color:var(--t-2);white-space:nowrap">${escapeHtml(r.reminder_time)}</span>
        ${statusBadge(r.status)}
        <span class="rem-card__arrow">▾</span>
      </summary>
      <div class="rem-card__body">
        <p class="rem-card__sched span-2">${escapeHtml(r.schedule_summary)}</p>
        <div class="field">
          <label class="field-label">Kind</label>
          <select class="field-input" data-field="kind" id="${uid}-kind">
            <option value="medicine">Medicine</option>
            <option value="general">General</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">Status</label>
          <select class="field-input" data-field="status" id="${uid}-status">
            <option value="pending">Pending</option>
            <option value="completed">Completed</option>
            <option value="skipped">Skipped</option>
          </select>
        </div>
        <div class="field span-2">
          <label class="field-label">Title</label>
          <input class="field-input" type="text" data-field="title" id="${uid}-title" value="${escapeAttr(r.title)}" />
        </div>
        <div class="field">
          <label class="field-label">Date</label>
          <input class="field-input" type="date" data-field="reminder_date" id="${uid}-date" value="${escapeAttr(r.reminder_date)}" />
        </div>
        <div class="field">
          <label class="field-label">Time</label>
          <input class="field-input" type="time" data-field="reminder_time" id="${uid}-time" value="${escapeAttr(r.reminder_time)}" />
        </div>
        <div class="field">
          <label class="field-label">Place</label>
          <input class="field-input" type="text" data-field="place" id="${uid}-place" value="${escapeAttr(r.place || "")}" />
        </div>
        <div class="field">
          <label class="field-label">Notes</label>
          <input class="field-input" type="text" data-field="notes" id="${uid}-notes" value="${escapeAttr(r.notes || "")}" />
        </div>
        <div class="rem-card__actions span-2">
          <button class="btn-save" data-save="${r.id}">Save changes</button>
          <button class="btn-danger" data-delete="${r.id}">Delete</button>
        </div>
      </div>
    </details>
  `;
}

function bindReminderCards(container) {
  $all("[data-save]", container).forEach(btn => {
    btn.addEventListener("click", async () => {
      const rid = Number(btn.dataset.save);
      const card = btn.closest(".rem-card");
      const payload = {
        kind:            card.querySelector('[data-field="kind"]').value,
        title:           card.querySelector('[data-field="title"]').value.trim(),
        reminder_date:   card.querySelector('[data-field="reminder_date"]').value,
        reminder_time:   card.querySelector('[data-field="reminder_time"]').value,
        place:           card.querySelector('[data-field="place"]').value,
        notes:           card.querySelector('[data-field="notes"]').value,
        status:          card.querySelector('[data-field="status"]').value,
      };
      try {
        await api(`/api/reminders/${rid}`, { method: "PATCH", body: JSON.stringify(payload) });
        toast("Changes saved.");
        await loadDashboard();
        await loadAllReminders();
        await loadCalendar();
        await loadSidebarUpcoming();
      } catch (e) {
        toast(e.message, true);
      }
    });
  });
  $all("[data-delete]", container).forEach(btn => {
    btn.addEventListener("click", async () => {
      const rid = Number(btn.dataset.delete);
      if (!confirm("Delete this reminder?")) return;
      try {
        await api(`/api/reminders/${rid}`, { method: "DELETE" });
        toast("Reminder deleted.");
        await loadDashboard();
        await loadAllReminders();
        await loadCalendar();
        await loadSidebarUpcoming();
      } catch (e) {
        toast(e.message, true);
      }
    });
  });
  // Restore select values after innerHTML injection
  $all(".rem-card", container).forEach(card => {
    const id = Number(card.dataset.id);
    // The row data is embedded in the DOM values already; just ensure dropdowns are set
  });
}

async function loadAllReminders() {
  const rows = await api("/api/reminders");
  const stack = $("#all-reminders");
  const total = $("#reminders-total");
  if (!rows.length) {
    stack.innerHTML = `<p style="color:var(--t-2);font-size:.88rem;padding:.5rem 0">No reminders yet. Add one above.</p>`;
    if (total) total.textContent = "0 reminders";
    return;
  }
  if (total) total.textContent = `${rows.length} reminder${rows.length > 1 ? "s" : ""}`;
  stack.innerHTML = rows.map(r => reminderCard(r, "all")).join("");
  stack.querySelectorAll(".rem-card").forEach(card => {
    const r = rows.find(x => x.id === Number(card.dataset.id));
    if (!r) return;
    card.querySelector('[data-field="kind"]').value = r.kind;
    card.querySelector('[data-field="status"]').value = r.status;
  });
  bindReminderCards(stack);
}

// ── Calendar ───────────────────────────────────

function mondayOfWeek(d) {
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  const n = new Date(d);
  n.setDate(d.getDate() + diff);
  return n;
}

async function loadCalendar() {
  const body = $("#calendar-body");
  const dateCtr = $("#calendar-date-controls");
  const today = new Date().toISOString().slice(0, 10);

  if (calMode === "daily") {
    if (!dateCtr.querySelector("#cal-daily-date")) {
      dateCtr.innerHTML = `<label style="display:flex;align-items:center;gap:.5rem;font-size:.84rem;color:var(--t-1)">
        Day <input type="date" id="cal-daily-date" class="cal-date-row" style="padding:.38rem .65rem;border-radius:var(--r-xs);border:1px solid var(--bdr-1);background:var(--bg-3);color:var(--t-0);font-family:var(--font);font-size:.83rem"/>
      </label>`;
      $("#cal-daily-date").addEventListener("change", () => loadCalendar());
    }
    const inp = $("#cal-daily-date");
    if (!inp.value) inp.value = today;
    const data = await api("/api/calendar/daily?date_str=" + encodeURIComponent(inp.value));
    if (!data.reminders.length) {
      body.innerHTML = `<p class="cal-empty">No reminders for this day.</p>`;
      return;
    }
    body.innerHTML = `<div class="reminder-list" id="cal-daily-stack"></div>`;
    const stack = $("#cal-daily-stack");
    stack.innerHTML = data.reminders.map(r => reminderCard(r, "calday")).join("");
    stack.querySelectorAll(".rem-card").forEach(card => {
      const r = data.reminders.find(x => x.id === Number(card.dataset.id));
      if (r) {
        card.querySelector('[data-field="kind"]').value = r.kind;
        card.querySelector('[data-field="status"]').value = r.status;
      }
    });
    bindReminderCards(stack);
  } else {
    if (!dateCtr.querySelector("#cal-week-start")) {
      dateCtr.innerHTML = `<label style="display:flex;align-items:center;gap:.5rem;font-size:.84rem;color:var(--t-1)">
        Week start <input type="date" id="cal-week-start" style="padding:.38rem .65rem;border-radius:var(--r-xs);border:1px solid var(--bdr-1);background:var(--bg-3);color:var(--t-0);font-family:var(--font);font-size:.83rem"/>
      </label>`;
      $("#cal-week-start").addEventListener("change", () => loadCalendar());
    }
    const inp = $("#cal-week-start");
    if (!inp.value) inp.value = mondayOfWeek(new Date()).toISOString().slice(0, 10);
    const data = await api("/api/calendar/weekly?start=" + encodeURIComponent(inp.value));
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    let html = '<div class="cal-week-grid">';
    for (const day of data.days) {
      const wd = new Date(day.date + "T12:00:00").getDay();
      const isToday = day.date === today;
      html += `<div class="cal-col${isToday ? " cal-col--today" : ""}">
        <div class="cal-col__head">${days[wd]} <span style="color:var(--t-0)">${day.date.slice(5)}</span>${isToday ? ' <span class="badge badge--teal" style="font-size:.65rem">Today</span>' : ""}</div>`;
      if (!day.reminders.length) {
        html += `<p style="color:var(--t-3);font-size:.78rem;margin:0">—</p>`;
      } else {
        html += `<div class="reminder-list" id="week-${day.date}"></div>`;
      }
      html += "</div>";
    }
    html += "</div>";
    body.innerHTML = html;
    for (const day of data.days) {
      if (!day.reminders.length) continue;
      const stack = $(`#week-${day.date}`);
      if (!stack) continue;
      stack.innerHTML = day.reminders.map(r => reminderCard(r, "calweek")).join("");
      stack.querySelectorAll(".rem-card").forEach(card => {
        const r = day.reminders.find(x => x.id === Number(card.dataset.id));
        if (r) {
          card.querySelector('[data-field="kind"]').value = r.kind;
          card.querySelector('[data-field="status"]').value = r.status;
        }
      });
      bindReminderCards(stack);
    }
  }
}

function setupCalendarMode() {
  $all(".seg-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      calMode = btn.dataset.calMode;
      $all(".seg-btn").forEach(b => b.classList.toggle("is-active", b === btn));
      // Clear date controls so they reinitialize
      $("#calendar-date-controls").innerHTML = "";
      loadCalendar();
    });
  });
}

// ── Sidebar mobile ─────────────────────────────

function setupSidebar() {
  const sidebar = $("#sidebar");
  const scrim = $("#sidebar-scrim");
  const toggle = $("#btn-sidebar-toggle");
  const close = () => {
    sidebar.classList.remove("is-open");
    scrim.hidden = true;
    scrim.classList.remove("is-visible");
  };
  const open = () => {
    sidebar.classList.add("is-open");
    scrim.hidden = false;
    scrim.classList.add("is-visible");
  };
  toggle.addEventListener("click", () => sidebar.classList.contains("is-open") ? close() : open());
  scrim.addEventListener("click", close);
  $all("#sidebar .sidebar-action").forEach(b => {
    b.addEventListener("click", () => { if (window.innerWidth < 960) close(); });
  });
}

// ── Init ───────────────────────────────────────

async function init() {
  try {
    const boot = await ensureSession();
    await loadMeta();
    fillSettingsForm(boot);

    const chip = $("#status-chip");
    const hint = $("#api-key-hint");
    if (boot.has_server_openai_key) {
      chip.classList.add("is-ready");
      $("#status-label").textContent = "Ready";
      hint.textContent = "Server API key is active.";
    } else {
      chip.classList.remove("is-ready");
      $("#status-label").textContent = "No API key";
      hint.innerHTML = `Open <strong>Settings</strong> to add your OpenAI key.`;
    }

    setupTabs();
    setupModals();
    setupChat();
    setupCalendarMode();
    setupSidebar();

    await Promise.all([
      loadDashboard(),
      loadChatHistory(),
      loadAllReminders(),
      loadCalendar(),
      loadSidebarUpcoming(),
    ]);
  } catch (e) {
    toast(e.message || "Failed to start", true);
    console.error(e);
  }
}

init();
