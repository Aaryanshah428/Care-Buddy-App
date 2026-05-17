/**
 * CareBuddy — SPA client
 */

const STORAGE_KEY = "carebuddy_session_id";
const THEME_KEY = "carebuddy_theme_v1";
const UI_PREFS_KEY = "carebuddy_ui_preferences_v1";
const FAMILY_NOTE_KEY = "carebuddy_family_note_v1";
const FAMILY_NOTES_KEY = "carebuddy_family_notes_v2";
const FAMILY_MEMBERS_KEY = "carebuddy_family_members_v1";
const ONBOARDING_KEY = "carebuddy_onboarding_v1";
const REMINDER_EVENTS_KEY = "carebuddy_reminder_events_v1";
const TASK_META_KEY = "carebuddy_task_meta_v1";
let sessionId = null;
let meta = null;
let calMode = "daily";
let activeView = "today";
let activeFamilyTab = "overview";
let onboardingStep = 0;
let selectedMember = "";
const ONBOARDING_DEFAULTS = {
  role_choice: "myself",
  family_members: [],
  help_with: ["Knowing what to do today"],
  wake_time: "07:30",
  med_time: "08:30",
  appointment_reminder: "2 hours before",
  wellness_task: "Walk for 10 minutes",
  medication_name: "",
  medication_dosage: "",
  medication_time: "08:30",
  medication_days: "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
  medication_instructions: "",
  appointment_title: "",
  appointment_datetime: "",
  appointment_location: "",
  appointment_notes: "",
  visibility_mode: "light_support",
  text_size: "normal",
  high_contrast: false,
  reduce_motion: false,
  voice_prompts_enabled: false,
  completed: false,
};
let onboardingData = { ...ONBOARDING_DEFAULTS };

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

function fmtLongDate(d = new Date()) {
  return d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

function loadUiPrefs() {
  try {
    return JSON.parse(localStorage.getItem(UI_PREFS_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveUiPrefs(next) {
  const current = loadUiPrefs();
  const merged = { ...current, ...next };
  localStorage.setItem(UI_PREFS_KEY, JSON.stringify(merged));
  return merged;
}

function loadOnboarding() {
  try {
    const raw = JSON.parse(localStorage.getItem(ONBOARDING_KEY) || "{}");
    onboardingData = { ...onboardingData, ...raw };
  } catch {
    // keep defaults
  }
}

function saveOnboarding(next = {}) {
  onboardingData = { ...onboardingData, ...next };
  localStorage.setItem(ONBOARDING_KEY, JSON.stringify(onboardingData));
}

function loadReminderEvents() {
  try {
    return JSON.parse(localStorage.getItem(REMINDER_EVENTS_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveReminderEvents(events) {
  localStorage.setItem(REMINDER_EVENTS_KEY, JSON.stringify(events));
}

function loadTaskMeta() {
  try {
    return JSON.parse(localStorage.getItem(TASK_META_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveTaskMeta(meta) {
  localStorage.setItem(TASK_META_KEY, JSON.stringify(meta));
}

function getFamilyMembers() {
  try { return JSON.parse(localStorage.getItem(FAMILY_MEMBERS_KEY) || "[]"); }
  catch { return []; }
}

function saveFamilyMembers(members) {
  localStorage.setItem(FAMILY_MEMBERS_KEY, JSON.stringify(members));
}

function isInFamilyMode() {
  return onboardingData.role_choice === "family" && getFamilyMembers().length > 0;
}

function getFamilyNote(member) {
  try {
    const notes = JSON.parse(localStorage.getItem(FAMILY_NOTES_KEY) || "{}");
    return notes[member || "general"] || localStorage.getItem(FAMILY_NOTE_KEY) || "";
  } catch { return localStorage.getItem(FAMILY_NOTE_KEY) || ""; }
}

function saveFamilyNote(member, note) {
  let notes = {};
  try { notes = JSON.parse(localStorage.getItem(FAMILY_NOTES_KEY) || "{}"); } catch { /**/ }
  notes[member || "general"] = note;
  localStorage.setItem(FAMILY_NOTES_KEY, JSON.stringify(notes));
}

function filterByMember(rows) {
  if (!selectedMember) return rows;
  const meta = loadTaskMeta();
  return rows.filter(r => (meta[r.id]?.member || "") === selectedMember);
}

function renderMemberSelector(wrapId, viewName) {
  const wrap = $(`#${wrapId}`);
  if (!wrap) return;
  const members = getFamilyMembers();
  const isFamily = onboardingData.role_choice === "family" && members.length > 0;
  if (!isFamily) { wrap.innerHTML = ""; return; }
  wrap.innerHTML = `
    <div class="member-selector">
      <label class="sr-only" for="${wrapId}-select">Show for</label>
      <select class="member-selector__select" id="${wrapId}-select" title="Filter by family member">
        <option value="">All members</option>
        ${members.map(m => `<option value="${escapeAttr(m)}" ${selectedMember === m ? "selected" : ""}>${escapeHtml(m)}</option>`).join("")}
      </select>
    </div>
  `;
  $(`#${wrapId}-select`)?.addEventListener("change", async ev => {
    selectedMember = ev.target.value;
    if (viewName === "medications") await loadMedicationsView();
    else if (viewName === "appointments") await loadAppointmentsView();
    else if (viewName === "progress") await loadProgressView();
    else if (viewName === "family") await loadFamilyView();
  });
}

function classifyTaskType(reminder) {
  const meta = loadTaskMeta();
  const localType = meta[reminder.id]?.task_type;
  if (localType) return localType;
  if (reminder.kind === "medicine") return "medication";
  if (reminder.kind === "general") return "appointment";
  if (reminder.kind === "routine") return "routine";
  if (reminder.kind === "family_note") return "family_note";
  return "routine";
}

function isCriticalTask(reminder) {
  const meta = loadTaskMeta();
  if (typeof meta[reminder.id]?.is_critical === "boolean") return !!meta[reminder.id].is_critical;
  return classifyTaskType(reminder) === "medication";
}

function reminderOffsets(reminder) {
  const meta = loadTaskMeta();
  return meta[reminder.id]?.reminder_offsets || [];
}

function upsertTaskMeta(reminderId, patch) {
  const all = loadTaskMeta();
  all[reminderId] = { ...(all[reminderId] || {}), ...patch };
  saveTaskMeta(all);
}

function getReminderDelayMinutes(reminder, now = new Date()) {
  const due = new Date(`${reminder.reminder_date}T${reminder.reminder_time}:00`);
  return Math.floor((now.getTime() - due.getTime()) / 60000);
}

function getReminderEscalationStage(reminder, now = new Date()) {
  if (reminder.status === "completed" || classifyTaskType(reminder) !== "medication") return 0;
  const delay = getReminderDelayMinutes(reminder, now);
  if (delay < 0) return 0;
  const familyDelay = Number(loadUiPrefs().family_alert_delay || 45);
  if (delay >= familyDelay) return 3;
  if (delay >= 15) return 2;
  return 1;
}

function reminderStatusLabel(reminder, now = new Date()) {
  if (reminder.status === "completed") return "completed";
  const delay = getReminderDelayMinutes(reminder, now);
  if (delay > 45) return "missed";
  return "pending";
}

function simulateReminderEscalation(reminders, mode) {
  const events = loadReminderEvents();
  const now = new Date();
  for (const r of reminders) {
    if (classifyTaskType(r) !== "medication" || r.status === "completed") continue;
    const stage = getReminderEscalationStage(r, now);
    if (stage === 0) continue;
    const previous = Number(events[r.id]?.stage || 0);
    if (stage <= previous) continue;
    if (stage === 1) {
      toast(`Time for ${r.title}.`);
    } else if (stage === 2) {
      toast(`Just checking in about ${r.title}. Would you like another reminder?`);
    } else if (stage === 3) {
      toast(`${r.title} is still waiting. Need help?`);
      if (isCriticalTask(r) && (mode === "light_support" || mode === "active_support" || mode === "caregiver_mode")) {
        toast("Family alert simulated for this missed critical medication.");
      }
    }
    events[r.id] = { stage, at: now.toISOString() };
  }
  saveReminderEvents(events);
}

function ensureMedicalSafetyText(userText, assistantText) {
  const combined = `${userText || ""} ${assistantText || ""}`.toLowerCase();
  const medicalHint = /(medicine|medication|dose|dosage|pill|drug|blood pressure|diabetes|appointment|doctor|pharmacist|health)/.test(combined);
  if (!medicalHint) return assistantText;
  const disclaimer = "I can help explain this in simple terms, but you should follow your doctor or pharmacist's instructions.";
  if ((assistantText || "").toLowerCase().includes("doctor") || (assistantText || "").toLowerCase().includes("pharmacist")) {
    return assistantText;
  }
  return `${assistantText}\n\n${disclaimer}`;
}

function getRouteViewFromUrl() {
  const path = window.location.pathname.replace(/^\/+/, "");
  const directMap = {
    "": "today",
    onboarding: "onboarding",
    today: "today",
    medications: "medications",
    appointments: "appointments",
    progress: "progress",
    assistant: "assistant",
    settings: "settings",
    family: "family",
    "family/alerts": "family",
    "family/settings": "family",
  };
  if (directMap[path] != null) return directMap[path];
  const q = new URLSearchParams(window.location.search);
  const fromQuery = q.get("view");
  if (fromQuery) return fromQuery;
  return (window.location.hash || "").replace("#/", "");
}

function applyAccessibilityFromPrefs(prefs = loadUiPrefs()) {
  document.body.classList.toggle("text-large", prefs.text_size === "large");
  document.body.classList.toggle("text-extra-large", prefs.text_size === "extra_large");
  document.body.classList.toggle("high-contrast", !!prefs.high_contrast);
  document.body.classList.toggle("reduce-motion", !!prefs.reduce_motion);
}

function applyTheme(theme) {
  const isLight = theme === "light";
  document.body.classList.toggle("light-mode", isLight);
  const sun = $("#theme-icon-sun");
  const moon = $("#theme-icon-moon");
  const btn = $("#btn-theme-toggle");
  if (sun) sun.style.display = isLight ? "none" : "";
  if (moon) moon.style.display = isLight ? "" : "none";
  if (btn) {
    btn.setAttribute("aria-label", isLight ? "Switch to dark mode" : "Switch to light mode");
    btn.setAttribute("title", isLight ? "Switch to dark mode" : "Switch to light mode");
  }
  localStorage.setItem(THEME_KEY, theme);
}

function setupThemeToggle() {
  const saved = localStorage.getItem(THEME_KEY) || "dark";
  applyTheme(saved);
  $("#btn-theme-toggle")?.addEventListener("click", () => {
    const isLight = document.body.classList.contains("light-mode");
    applyTheme(isLight ? "dark" : "light");
  });
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

async function findCreatedReminderId(payload) {
  const rows = await api("/api/reminders");
  const candidates = rows.filter(r =>
    r.title === payload.title &&
    r.reminder_date === payload.reminder_date &&
    r.reminder_time === payload.reminder_time
  );
  const newest = candidates.sort((a, b) => Number(b.id) - Number(a.id))[0];
  return newest?.id || null;
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
  if (kind === "medicine") return `<span class="badge badge--med">💊 Medication</span>`;
  if (kind === "general") return `<span class="badge badge--gen">📅 Appointment</span>`;
  if (kind === "routine") return `<span class="badge">🌿 Routine</span>`;
  if (kind === "family_note") return `<span class="badge">💌 Family note</span>`;
  return `<span class="badge">${escapeHtml(kind)}</span>`;
}

function statusBadge(status) {
  const map = { pending: "badge--amber", completed: "badge--green", skipped: "badge" };
  return `<span class="badge ${map[status] || "badge"}">${escapeHtml(status)}</span>`;
}

function setActiveView(view, opts = {}) {
  const { updateUrl = true } = opts;
  const allowed = ["onboarding", "today", "medications", "appointments", "progress", "assistant", "settings", "family"];
  activeView = allowed.includes(view) ? view : "today";
  if (!onboardingData.completed && activeView !== "onboarding") {
    activeView = "onboarding";
  }
  document.body.classList.toggle("onboarding-active", activeView === "onboarding");
  $all(".primary-nav__btn, .bottom-nav__btn, .sidebar-nav-item").forEach(btn => {
    const on = btn.dataset.view === activeView;
    btn.classList.toggle("is-active", on);
  });
  $all(".app-view").forEach(section => {
    const show = section.id === `view-${activeView}`;
    section.hidden = !show;
    section.classList.toggle("is-visible", show);
  });
  if (activeView === "settings") {
    $("#btn-open-settings-top")?.click();
    setActiveView("today");
    return;
  }
  if (updateUrl) {
    const url = new URL(window.location.href);
    const routeMap = {
      onboarding: "/onboarding",
      today: "/today",
      medications: "/medications",
      appointments: "/appointments",
      progress: "/progress",
      assistant: "/assistant",
      settings: "/settings",
      family: "/family",
    };
    const path = routeMap[activeView] || "/today";
    window.history.replaceState({}, "", `${path}${url.search || ""}`);
  }
}

async function snoozeReminder(reminder) {
  const prefs = loadUiPrefs();
  const snoozeMins = Number(prefs.snooze_duration || 15);
  const [hh, mm] = String(reminder.reminder_time || "09:00").split(":").map(Number);
  const dt = new Date();
  dt.setHours(Number.isFinite(hh) ? hh : 9, Number.isFinite(mm) ? mm : 0, 0, 0);
  dt.setMinutes(dt.getMinutes() + snoozeMins);
  const next = `${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
  await api(`/api/reminders/${reminder.id}`, {
    method: "PATCH",
    body: JSON.stringify({ reminder_time: next, status: "pending" }),
  });
  toast(`Reminder moved ${snoozeMins} minutes later.`);
  await Promise.all([loadDashboard(), loadMedicationsView(), loadAppointmentsView(), loadProgressView(), loadFamilyView(), loadSidebarUpcoming()]);
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
  const prefs = loadUiPrefs();
  f.name.value = boot.persona.name || "";
  f.age.value = boot.persona.age || "";
  f.language.value = boot.persona.language || "English";
  f.timezone.value = boot.persona.timezone || "UTC";
  f.reminder_style.value = boot.persona.reminder_style || "gentle";
  const maskedKey = boot.masked_openai_api_key || "";
  f.openai_api_key.value = maskedKey;
  f.openai_api_key.dataset.maskedValue = maskedKey;
  f.notification_channel.value = boot.notification_channel || "email";
  f.notification_destination.value = boot.notification_destination || "";
  f.visibility_mode.value = prefs.visibility_mode || "light_support";
  f.text_size.value = prefs.text_size || "normal";
  f.high_contrast.checked = !!prefs.high_contrast;
  f.reduce_motion.checked = !!prefs.reduce_motion;
  f.voice_prompts_enabled.checked = !!prefs.voice_prompts_enabled;
  f.reminder_sound.value = prefs.reminder_sound || "chime";
  f.reminder_frequency.value = prefs.reminder_frequency || "normal";
  f.snooze_duration.value = Number(prefs.snooze_duration || 15);
  f.family_alert_delay.value = Number(prefs.family_alert_delay || 45);
}

const ONBOARDING_STEPS = [
  { title: "Welcome to CareBuddy", subtitle: "A calm daily guide to help you stay independent, organized, and on track." },
  { title: "Who are you setting this up for?", subtitle: "Tell us who you'd like to care for." },
  { title: "What would you like help with?", subtitle: "Pick all that apply." },
  { title: "Build Today's routine", subtitle: "Set your preferred daily schedule." },
  { title: "Add first medication", subtitle: "You can skip this and add it later." },
  { title: "Add first appointment", subtitle: "You can skip this and add it later." },
  { title: "Family support", subtitle: "Choose how much visibility to share." },
  { title: "Accessibility", subtitle: "Make CareBuddy comfortable and readable." },
  { title: "You're all set", subtitle: "Let's make today feel easier." },
];

function renderOnboarding() {
  let step = ONBOARDING_STEPS[onboardingStep];
  if (onboardingStep === 1 && onboardingData.role_choice === "family") {
    step = { title: "Who are you setting this up for?", subtitle: "Add the names of the family members you want to care for." };
  } else if (onboardingStep === 1) {
    step = { title: "Ready to get started", subtitle: "CareBuddy will guide you step by step through your personal setup." };
  }
  $("#onboarding-title").textContent = step.title;
  $("#onboarding-subtitle").textContent = step.subtitle;
  $("#onboarding-step-label").textContent = `Step ${onboardingStep + 1} of ${ONBOARDING_STEPS.length}`;
  $("#onboarding-progress-bar").style.width = `${((onboardingStep + 1) / ONBOARDING_STEPS.length) * 100}%`;
  const backBtn = $("#onboarding-back");
  const nextBtn = $("#onboarding-next");
  backBtn.disabled = onboardingStep === 0;
  nextBtn.textContent = onboardingStep === ONBOARDING_STEPS.length - 1 ? "Go to Today" : "Next";

  const body = $("#onboarding-body");
  if (!body) return;
  if (onboardingStep === 0) {
    body.innerHTML = `
      <div class="onboarding-grid">
        <button class="select-card ${onboardingData.role_choice === "myself" ? "is-selected" : ""}" data-role-choice="myself">
          <strong>Let's get started</strong><br/>I'm setting this up for myself.
        </button>
        <button class="select-card ${onboardingData.role_choice === "family" ? "is-selected" : ""}" data-role-choice="family">
          <strong>I'm helping a family member</strong><br/>Set up CareBuddy for a loved one.
        </button>
      </div>
    `;
  } else if (onboardingStep === 1 && onboardingData.role_choice === "family") {
    const members = onboardingData.family_members || [];
    body.innerHTML = `
      <div class="field ob-member-entry">
        <label class="field-label">Family member name</label>
        <div class="field-row" style="gap:.5rem;align-items:flex-end">
          <input id="ob-member-name" class="field-input" type="text" placeholder="e.g. Mom, Dad, Grandma" autocomplete="off"/>
          <button type="button" class="btn-primary ob-add-member-btn" id="ob-add-member">Add</button>
        </div>
      </div>
      ${members.length === 0 ? `<p class="ob-member-hint">Add at least one family member to continue.</p>` : ""}
      <ul class="ob-member-list" id="ob-member-list">
        ${members.map((m, i) => `
          <li class="ob-member-item">
            <span class="ob-member-item__name">${escapeHtml(m)}</span>
            <button type="button" class="ob-member-item__remove" data-remove-member="${i}" aria-label="Remove ${escapeAttr(m)}">✕</button>
          </li>
        `).join("")}
      </ul>
    `;
    const addBtn = $("#ob-add-member");
    const nameInput = $("#ob-member-name");
    const doAdd = () => {
      const name = nameInput.value.trim();
      if (!name) return;
      const current = onboardingData.family_members || [];
      if (!current.includes(name)) {
        saveOnboarding({ family_members: [...current, name] });
      }
      nameInput.value = "";
      renderOnboarding();
    };
    addBtn?.addEventListener("click", doAdd);
    nameInput?.addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); doAdd(); } });
    $all("[data-remove-member]", body).forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.dataset.removeMember);
        const current = [...(onboardingData.family_members || [])];
        current.splice(idx, 1);
        saveOnboarding({ family_members: current });
        renderOnboarding();
      });
    });
  } else if (onboardingStep === 1) {
    body.innerHTML = `
      <div class="onboarding-card">
        <h3 style="margin:0 0 .5rem">You're setting this up for yourself</h3>
        <p style="margin:0;color:var(--t-1)">CareBuddy will guide you step by step through your daily routine, medications, and appointments.</p>
      </div>
    `;
  } else if (onboardingStep === 2) {
    const options = [
      "Taking medications on time",
      "Remembering appointments",
      "Knowing what to do today",
      "Family peace of mind",
    ];
    body.innerHTML = `
      <div class="onboarding-grid">
        ${options.map(opt => `
          <button class="select-card ${onboardingData.help_with.includes(opt) ? "is-selected" : ""}" data-help-option="${escapeAttr(opt)}">${escapeHtml(opt)}</button>
        `).join("")}
      </div>
    `;
  } else if (onboardingStep === 3) {
    body.innerHTML = `
      <div class="field-row">
        <div class="field">
          <label class="field-label">Preferred wake time</label>
          <input id="ob-wake-time" type="time" class="field-input" value="${escapeAttr(onboardingData.wake_time)}"/>
        </div>
        <div class="field">
          <label class="field-label">Morning medication time</label>
          <input id="ob-med-time" type="time" class="field-input" value="${escapeAttr(onboardingData.med_time)}"/>
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label class="field-label">Appointment reminder preference</label>
          <select id="ob-appt-reminder" class="field-input">
            ${["24 hours before", "2 hours before", "15 minutes before"].map(x => `<option value="${escapeAttr(x)}" ${onboardingData.appointment_reminder === x ? "selected" : ""}>${escapeHtml(x)}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label class="field-label">Daily wellness task</label>
          <input id="ob-wellness-task" type="text" class="field-input" value="${escapeAttr(onboardingData.wellness_task)}" />
        </div>
      </div>
    `;
  } else if (onboardingStep === 4) {
    body.innerHTML = `
      <p class="single-view-intro">Skippable. You can always add medications later.</p>
      <div class="field-row">
        <div class="field"><label class="field-label">Medication name</label><input id="ob-med-name" class="field-input" type="text" value="${escapeAttr(onboardingData.medication_name)}" /></div>
        <div class="field"><label class="field-label">Dosage</label><input id="ob-med-dose" class="field-input" type="text" value="${escapeAttr(onboardingData.medication_dosage)}" /></div>
      </div>
      <div class="field-row">
        <div class="field"><label class="field-label">Time</label><input id="ob-med-time-2" class="field-input" type="time" value="${escapeAttr(onboardingData.medication_time)}" /></div>
        <div class="field"><label class="field-label">Days</label><input id="ob-med-days" class="field-input" type="text" value="${escapeAttr(onboardingData.medication_days)}" /></div>
      </div>
      <div class="field"><label class="field-label">Instructions</label><input id="ob-med-inst" class="field-input" type="text" value="${escapeAttr(onboardingData.medication_instructions)}" /></div>
    `;
  } else if (onboardingStep === 5) {
    body.innerHTML = `
      <p class="single-view-intro">Skippable. You can always add appointments later.</p>
      <div class="field-row">
        <div class="field"><label class="field-label">Appointment title</label><input id="ob-appt-title" class="field-input" type="text" value="${escapeAttr(onboardingData.appointment_title)}" /></div>
        <div class="field"><label class="field-label">Date & time</label><input id="ob-appt-dt" class="field-input" type="datetime-local" value="${escapeAttr(onboardingData.appointment_datetime)}" /></div>
      </div>
      <div class="field-row">
        <div class="field"><label class="field-label">Location</label><input id="ob-appt-location" class="field-input" type="text" value="${escapeAttr(onboardingData.appointment_location)}" /></div>
        <div class="field"><label class="field-label">Preparation notes</label><input id="ob-appt-notes" class="field-input" type="text" value="${escapeAttr(onboardingData.appointment_notes)}" /></div>
      </div>
    `;
  } else if (onboardingStep === 6) {
    const modes = [
      ["light_support", "Light Support", "Alerts only for missed important tasks."],
      ["active_support", "Active Support", "Family sees daily progress and critical alerts."],
      ["caregiver_mode", "Caregiver Mode", "Family can help manage medications and appointments."],
    ];
    body.innerHTML = `
      <div class="onboarding-grid">
        ${modes.map(([id, name, desc]) => `
          <button class="select-card ${onboardingData.visibility_mode === id ? "is-selected" : ""}" data-visibility-mode="${id}">
            <strong>${name}</strong><br/>${desc}
          </button>
        `).join("")}
      </div>
    `;
  } else if (onboardingStep === 7) {
    body.innerHTML = `
      <div class="field-row">
        <div class="field">
          <label class="field-label">Text size</label>
          <select id="ob-text-size" class="field-input">
            ${["normal", "large", "extra_large"].map(x => `<option value="${x}" ${onboardingData.text_size === x ? "selected" : ""}>${escapeHtml(x.replace("_", " "))}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label class="field-label">Accessibility options</label>
          <label class="field-checkbox"><input id="ob-high-contrast" type="checkbox" ${onboardingData.high_contrast ? "checked" : ""}/> High contrast</label>
          <label class="field-checkbox"><input id="ob-reduce-motion" type="checkbox" ${onboardingData.reduce_motion ? "checked" : ""}/> Reduce motion</label>
          <label class="field-checkbox"><input id="ob-voice-prompts" type="checkbox" ${onboardingData.voice_prompts_enabled ? "checked" : ""}/> Voice prompts</label>
        </div>
      </div>
    `;
  } else {
    body.innerHTML = `
      <div class="onboarding-card">
        <h3>You're all set. Let's make today feel easier.</h3>
        <p>CareBuddy will guide your day with gentle reminders and calm support.</p>
      </div>
    `;
  }

  $all("[data-role-choice]", body).forEach(btn => {
    btn.addEventListener("click", () => {
      saveOnboarding({ role_choice: btn.dataset.roleChoice });
      renderOnboarding();
    });
  });
  $all("[data-help-option]", body).forEach(btn => {
    btn.addEventListener("click", () => {
      const value = btn.dataset.helpOption;
      const has = onboardingData.help_with.includes(value);
      const next = has ? onboardingData.help_with.filter(x => x !== value) : [...onboardingData.help_with, value];
      saveOnboarding({ help_with: next.length ? next : ["Knowing what to do today"] });
      renderOnboarding();
    });
  });
  $all("[data-visibility-mode]", body).forEach(btn => {
    btn.addEventListener("click", () => {
      saveOnboarding({ visibility_mode: btn.dataset.visibilityMode });
      renderOnboarding();
    });
  });
}

// ── Dashboard ──────────────────────────────────

async function loadDashboard() {
  const d = await api("/api/dashboard");
  const p = d.persona;
  const prefs = loadUiPrefs();

  // Greeting
  const friendlyName = p.name?.trim() || "friend";
  $("#today-greeting").textContent = `${getGreeting()}, ${friendlyName} 🌿`;
  $("#today-date").textContent = `Today is ${fmtLongDate()}.`;

  // Profile
  const profileKv = $("#profile-kv");
  if (profileKv) {
    profileKv.innerHTML = [
      ["Name",  p.name || '<span class="badge">Not set</span>'],
      ["Age",   p.age || '<span class="badge">Not set</span>'],
      ["Language", escapeHtml(p.language)],
      ["Timezone", escapeHtml(p.timezone || "UTC")],
      ["Style",    escapeHtml(p.reminder_style)],
      ["Family mode", escapeHtml((prefs.visibility_mode || "light_support").replaceAll("_", " "))],
    ].map(([k,v]) => `<dt>${k}</dt><dd>${v.includes("<") ? v : escapeHtml(v)}</dd>`).join("");
  }

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
      <div class="nr-title">Next up: ${escapeHtml(nr.title)} at ${escapeHtml(nr.reminder_time)}</div>
      <div class="nr-meta">${escapeHtml(fmtDate(nr.reminder_date))} · ${kindBadge(nr.kind)}</div>
      <div style="margin-top:.6rem;display:flex;gap:.4rem;flex-wrap:wrap">
        <button class="today-item__btn" id="hero-mark-done" type="button">Mark done</button>
        <button class="today-item__snooze" id="hero-snooze" type="button">Remind me later</button>
      </div>
    `;
    $("#hero-mark-done")?.addEventListener("click", async () => {
      await api(`/api/reminders/${nr.id}`, { method: "PATCH", body: JSON.stringify({ status: "completed" }) });
      toast("Great job. Marked as done.");
      await Promise.all([loadDashboard(), loadMedicationsView(), loadAppointmentsView(), loadProgressView(), loadSidebarUpcoming()]);
    });
    $("#hero-snooze")?.addEventListener("click", async () => {
      await snoozeReminder(nr);
    });
  } else {
    nextBadge.hidden = true;
    nextEl.innerHTML = `<div class="nr-empty">A quiet day today 🌿 You can add a medication, appointment, or routine whenever you're ready.</div>`;
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
      const label = reminderStatusLabel(r);
      const done = label === "completed";
      const missed = label === "missed";
      const li = document.createElement("li");
      li.className = "today-item" + (done ? " today-item--done" : "");
      li.innerHTML = `
        <span class="today-item__time">${escapeHtml(r.reminder_time)}</span>
        <span class="today-item__name">${escapeHtml(r.title)}${missed ? " — gently missed, you can reset now." : ""}</span>
        <span class="today-item__kind">${kindBadge(r.kind)}</span>
        <span class="badge ${missed ? "badge--amber" : (done ? "badge--green" : "badge")}">${escapeHtml(label)}</span>
        <button class="today-item__btn" data-rid="${r.id}" data-done="${done}">
          ${done ? "✓ Done" : "Mark done"}
        </button>
        ${done ? "" : `<button class="today-item__snooze" data-snooze="${r.id}">Remind me later</button>`}
      `;
      li.querySelector("button").addEventListener("click", async (ev) => {
        const btn = ev.currentTarget;
        const isDone = btn.dataset.done === "true";
        const newStatus = isDone ? "pending" : "completed";
        await api(`/api/reminders/${r.id}`, { method: "PATCH", body: JSON.stringify({ status: newStatus }) });
        toast(isDone ? "Marked pending." : "Marked complete.");
        await Promise.all([loadDashboard(), loadMedicationsView(), loadAppointmentsView(), loadProgressView(), loadSidebarUpcoming()]);
      });
      li.querySelector('[data-snooze]')?.addEventListener("click", async () => {
        await snoozeReminder(r);
      });
      list.appendChild(li);
    }
  }

  const todayRows = d.today_reminders || [];
  const medsToday = todayRows.filter(r => classifyTaskType(r) === "medication");
  const apptsToday = todayRows.filter(r => classifyTaskType(r) === "appointment");
  const medsTodayEl = $("#today-medications");
  const apptsTodayEl = $("#today-appointments");

  if (medsTodayEl) {
    medsTodayEl.innerHTML = medsToday.length
      ? medsToday.map(m => `
        <article class="info-card">
          <p class="info-card__title">${escapeHtml(m.title)}</p>
          <p class="info-card__meta">Dosage / instructions: ${escapeHtml(m.notes || "Not added yet")}</p>
          <p class="info-card__meta">Scheduled for ${escapeHtml(m.reminder_time)}</p>
        </article>
      `).join("")
      : `<p class="cal-empty">No medications due today.</p>`;
  }

  if (apptsTodayEl) {
    apptsTodayEl.innerHTML = apptsToday.length
      ? apptsToday.map(a => `
        <article class="info-card">
          <p class="info-card__title">${escapeHtml(a.title)}</p>
          <p class="info-card__meta">${escapeHtml(a.reminder_time)}${a.place ? ` · ${escapeHtml(a.place)}` : ""}</p>
          <p class="info-card__meta">Prep reminder: ${escapeHtml(a.notes || "Bring your medication list and arrive a little early.")}</p>
        </article>
      `).join("")
      : `<p class="cal-empty">No appointments scheduled for today.</p>`;
  }

  // Today-only progress
  const progressEl = $("#progress-widget");
  const completedToday = todayRows.filter(r => r.status === "completed").length;
  const pendingToday = todayRows.filter(r => r.status !== "completed").length;
  progressEl.innerHTML = `
    <p><strong>${completedToday} completed today</strong></p>
    <p class="muted">${pendingToday} task${pendingToday === 1 ? "" : "s"} remaining</p>
    <p class="muted">Keep going at your own pace.</p>
  `;

  const encourageEl = $("#today-encouragement");
  if (encourageEl) {
    encourageEl.textContent = pendingToday === 0
      ? "You handled everything for today. Great work."
      : "You're doing great today.";
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

async function loadMedicationsView() {
  renderMemberSelector("member-selector-wrap-medications", "medications");
  const rows = await api("/api/reminders");
  const prefs = loadUiPrefs();
  const mode = prefs.visibility_mode || "light_support";
  simulateReminderEscalation(rows, mode);
  const allMeds = rows.filter(r => classifyTaskType(r) === "medication");
  const meds = filterByMember(allMeds);
  const el = $("#medications-list");
  if (!el) return;
  const memberLabel = selectedMember ? ` for ${selectedMember}` : "";
  if (!meds.length) {
    el.innerHTML = `<p class="cal-empty">No medications added yet${memberLabel}. CareBuddy can help you remember when you're ready.</p>`;
    return;
  }
  const taskMeta = loadTaskMeta();
  el.innerHTML = meds.map(m => {
    const stage = getReminderEscalationStage(m);
    const status = reminderStatusLabel(m);
    const isCompleted = status === "completed";
    const sameMed = allMeds.filter(x => x.title === m.title);
    const takenCount = sameMed.filter(x => x.status === "completed").length;
    const dosage = (m.notes || "Not set").trim() || "Not set";
    const memberFor = taskMeta[m.id]?.member || "";
    const memberTag = isInFamilyMode() && memberFor ? `<span class="badge badge--member">👤 ${escapeHtml(memberFor)}</span>` : "";
    const statusBadgeHtml = isCompleted
      ? `<span class="badge badge--green info-card__status-badge">✓ Taken</span>`
      : status === "missed"
        ? `<span class="badge badge--amber info-card__status-badge">⚠ Missed</span>`
        : `<span class="badge info-card__status-badge">Pending</span>`;
    return `
    <article class="info-card${isCompleted ? " info-card--completed" : ""}" data-med-id="${m.id}">
      <div class="info-card__title-row">
        <p class="info-card__title">${escapeHtml(m.title)} ${memberTag}</p>
        ${statusBadgeHtml}
      </div>
      <p class="info-card__meta">Dosage: ${escapeHtml(dosage)}</p>
      <p class="info-card__meta">Schedule: ${escapeHtml(m.schedule_summary || "Not set")}</p>
      <p class="info-card__meta">Next dose: ${escapeHtml(fmtDate(m.reminder_date))} at ${escapeHtml(m.reminder_time)}</p>
      <p class="info-card__meta">Adherence: ${takenCount}/${sameMed.length} doses taken${stage === 2 ? " · Reminder sent (15m)." : ""}${stage === 3 ? " · Final reminder sent (45m)." : ""}</p>
      <div class="info-card__actions">
        <button class="today-item__btn${isCompleted ? " today-item__btn--undo" : ""}" data-med-done="${m.id}">
          ${isCompleted ? "↩ Undo" : "Mark taken"}
        </button>
        ${!isCompleted ? `<button class="today-item__snooze" data-med-snooze="${m.id}">Remind me later</button>` : ""}
      </div>
    </article>
  `;
  }).join("");

  $all("[data-med-done]", el).forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.medDone);
      await api(`/api/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ status: "completed" }) });
      toast("Medication marked as taken.");
      await Promise.all([loadDashboard(), loadMedicationsView(), loadProgressView(), loadFamilyView(), loadSidebarUpcoming()]);
    });
  });
  $all("[data-med-snooze]", el).forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.medSnooze);
      const m = meds.find(x => x.id === id);
      if (!m) return;
      await snoozeReminder(m);
      await Promise.all([loadMedicationsView(), loadProgressView(), loadFamilyView(), loadSidebarUpcoming()]);
    });
  });
}

async function loadAppointmentsView() {
  renderMemberSelector("member-selector-wrap-appointments", "appointments");
  const rows = await api("/api/reminders");
  const allAppts = rows.filter(r => classifyTaskType(r) === "appointment");
  const appts = filterByMember(allAppts);
  const el = $("#appointments-list");
  if (!el) return;
  const memberLabel = selectedMember ? ` for ${selectedMember}` : "";
  if (!appts.length) {
    el.innerHTML = `<p class="cal-empty">No appointments coming up${memberLabel}. Add one so CareBuddy can help you prepare.</p>`;
    return;
  }
  const now = new Date();
  const upcoming = appts
    .filter(a => new Date(`${a.reminder_date}T${a.reminder_time}:00`) >= now)
    .sort((a, b) => `${a.reminder_date}T${a.reminder_time}`.localeCompare(`${b.reminder_date}T${b.reminder_time}`));
  const past = appts
    .filter(a => new Date(`${a.reminder_date}T${a.reminder_time}:00`) < now)
    .sort((a, b) => `${b.reminder_date}T${b.reminder_time}`.localeCompare(`${a.reminder_date}T${a.reminder_time}`));

  const apptTaskMeta = loadTaskMeta();
  const appointmentCard = (a, showActions = true) => {
    const memberFor = apptTaskMeta[a.id]?.member || "";
    const memberTag = isInFamilyMode() && memberFor ? `<span class="badge badge--member">👤 ${escapeHtml(memberFor)}</span>` : "";
    const isCompleted = a.status === "completed";
    const apptStatusBadge = isCompleted
      ? `<span class="badge badge--green info-card__status-badge">✓ Completed</span>`
      : `<span class="badge info-card__status-badge">Upcoming</span>`;
    return `
    <article class="info-card${isCompleted ? " info-card--completed" : ""}">
      <div class="info-card__title-row">
        <p class="info-card__title">${escapeHtml(a.title)} ${memberTag}</p>
        ${apptStatusBadge}
      </div>
      <p class="info-card__meta">${escapeHtml(fmtDate(a.reminder_date))} at ${escapeHtml(a.reminder_time)}${a.place ? ` · ${escapeHtml(a.place)}` : ""}</p>
      <p class="info-card__meta">Prep notes: ${escapeHtml(a.notes || "Bring your medication list and arrive a little early.")}</p>
      <p class="info-card__meta">Schedule: ${escapeHtml(a.schedule_summary || "One-time event")}</p>
      ${showActions ? `<div class="info-card__actions">
        <button class="today-item__btn${isCompleted ? " today-item__btn--undo" : ""}" data-appt-done="${a.id}">
          ${isCompleted ? "↩ Undo" : "Mark complete"}
        </button>
        ${!isCompleted ? `<button class="today-item__snooze" data-appt-snooze="${a.id}">Remind me later</button>` : ""}
      </div>` : ""}
    </article>
  `;
  };

  el.innerHTML = `
    <article class="info-card">
      <p class="info-card__title">Upcoming appointments</p>
      <p class="info-card__meta">${upcoming.length ? `${upcoming.length} scheduled` : "No upcoming appointments."}</p>
    </article>
    ${upcoming.length ? upcoming.map(a => appointmentCard(a, true)).join("") : `<p class="cal-empty">No upcoming appointments.</p>`}
    <article class="info-card">
      <p class="info-card__title">Past appointments</p>
      <p class="info-card__meta">${past.length ? `${past.length} in your history` : "No past appointments yet."}</p>
    </article>
    ${past.length ? past.map(a => appointmentCard(a, false)).join("") : `<p class="cal-empty">No past appointments yet.</p>`}
  `;
  $all("[data-appt-done]", el).forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.apptDone);
      await api(`/api/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ status: "completed" }) });
      toast("Appointment marked complete.");
      await Promise.all([loadDashboard(), loadAppointmentsView(), loadProgressView(), loadFamilyView(), loadSidebarUpcoming()]);
    });
  });
  $all("[data-appt-snooze]", el).forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.apptSnooze);
      const a = appts.find(x => x.id === id);
      if (!a) return;
      await snoozeReminder(a);
      await Promise.all([loadAppointmentsView(), loadProgressView(), loadFamilyView(), loadSidebarUpcoming()]);
    });
  });
}

async function loadProgressView() {
  renderMemberSelector("member-selector-wrap-progress", "progress");
  const allRows = await api("/api/reminders");
  const rows = filterByMember(allRows);
  const completed = rows.filter(r => r.status === "completed").length;
  const total = rows.length || 1;
  const meds = rows.filter(r => classifyTaskType(r) === "medication");
  const medsCompleted = meds.filter(r => r.status === "completed").length;
  const medRate = meds.length ? Math.round((medsCompleted / meds.length) * 100) : 0;
  const appts = rows.filter(r => classifyTaskType(r) === "appointment");
  const apptDone = appts.filter(r => r.status === "completed").length;
  const apptRate = appts.length ? Math.round((apptDone / appts.length) * 100) : 0;
  const weeklyRows = rows.filter(r => {
    const dt = new Date(`${r.reminder_date}T${r.reminder_time}:00`);
    const diffDays = (Date.now() - dt.getTime()) / 86400000;
    return diffDays >= 0 && diffDays <= 7;
  });
  const weeklyCompleted = weeklyRows.filter(r => r.status === "completed").length;
  const weeklyRate = weeklyRows.length ? Math.round((weeklyCompleted / weeklyRows.length) * 100) : 0;
  const streak = Math.min(7, Math.max(1, Math.round((medRate + apptRate) / 30)));
  const el = $("#progress-summary-view");
  if (!el) return;
  const memberHeading = selectedMember ? ` — ${selectedMember}` : "";
  el.innerHTML = `
    <div class="single-view-list">
      <article class="info-card">
        <p class="info-card__title">Organized days streak${memberHeading}: ${streak} day${streak === 1 ? "" : "s"} 🌿</p>
        <p class="info-card__meta">Gentle achievements build long-term consistency.</p>
      </article>
      <article class="info-card">
        <p class="info-card__meta">Completed tasks this week: <strong>${weeklyCompleted}</strong> of <strong>${weeklyRows.length || 0}</strong></p>
        <p class="info-card__meta">Medication consistency: <strong>${medRate}%</strong></p>
        <p class="info-card__meta">Appointment completion: <strong>${apptRate}%</strong></p>
        <p class="info-card__meta">Weekly trends: <strong>${weeklyRate}%</strong> completion rate this week.</p>
        <p class="info-card__meta">All-time completion: <strong>${completed}</strong> of <strong>${rows.length}</strong>.</p>
      </article>
    </div>
  `;
}

async function loadFamilyView() {
  renderMemberSelector("member-selector-wrap-family", "family");
  const allRows = await api("/api/reminders");
  const prefs = loadUiPrefs();
  const mode = prefs.visibility_mode || "light_support";
  simulateReminderEscalation(allRows, mode);
  const rows = filterByMember(allRows);
  const today = new Date();
  const missedCritical = rows.filter(r => {
    if (classifyTaskType(r) !== "medication" || r.status === "completed") return false;
    const dt = new Date(`${r.reminder_date}T${r.reminder_time}:00`);
    return dt < today && isCriticalTask(r);
  });
  const completed = rows.filter(r => r.status === "completed").length;
  const total = rows.length;
  const familyMode = isInFamilyMode();
  const noteKey = selectedMember || "general";
  const note = getFamilyNote(noteKey) || (familyMode ? "" : "Your family is thinking of you today ❤️");

  const family = $("#family-overview");
  if (family) {
    const medicationRows = rows.filter(r => classifyTaskType(r) === "medication");
    const appointmentRows = rows.filter(r => classifyTaskType(r) === "appointment");
    const medicationCompletion = medicationRows.filter(r => r.status === "completed").length;
    const medicationTotal = medicationRows.length || 1;
    const appointmentCompletion = appointmentRows.filter(r => r.status === "completed").length;
    const appointmentTotal = appointmentRows.length || 1;
    const memberHeading = selectedMember ? ` (${selectedMember})` : "";
    const summaryBlock = mode === "light_support"
      ? `<p class="info-card__meta">Light Support only shows critical missed reminders.</p>`
      : `<p class="info-card__meta">Medication completion: ${Math.round((medicationCompletion / medicationTotal) * 100)}%</p>
         <p class="info-card__meta">Appointment completion: ${Math.round((appointmentCompletion / appointmentTotal) * 100)}%</p>`;
    const manageBlock = mode === "caregiver_mode"
      ? `<div class="info-card__actions">
           <button class="btn-primary" id="family-manage-meds" type="button">Manage medications</button>
           <button class="btn-primary" id="family-manage-appts" type="button">Manage appointments</button>
         </div>`
      : `<p class="info-card__meta">Schedule editing is available in Caregiver Mode.</p>`;

    const overviewHtml = `
      <article class="info-card">
        <p class="info-card__title">${completed >= Math.max(1, Math.floor(total * 0.6)) ? `On track today${memberHeading}` : `Today is a little off track${memberHeading}`}</p>
        <p class="info-card__meta">${completed} of ${total} tasks completed.</p>
        <p class="info-card__meta">Visibility mode: ${escapeHtml(mode.replaceAll("_", " "))}</p>
        ${summaryBlock}
      </article>`;
    const alertsHtml = `
      <article class="info-card">
        <p class="info-card__title">Alerts${memberHeading}</p>
        <p class="info-card__meta">${missedCritical.length ? `${missedCritical.length} critical medication reminder(s) may need follow-up.` : "No critical alerts."}</p>
      </article>`;
    const medsHtml = `
      <article class="info-card">
        <p class="info-card__title">Medications${memberHeading}</p>
        <p class="info-card__meta">${medicationCompletion} of ${medicationRows.length || 0} medication tasks completed.</p>
      </article>`;
    const apptsHtml = `
      <article class="info-card">
        <p class="info-card__title">Appointments${memberHeading}</p>
        <p class="info-card__meta">${appointmentCompletion} of ${appointmentRows.length || 0} appointment tasks completed.</p>
      </article>`;
    const privacyHtml = `
      <article class="info-card">
        <p class="info-card__title">Privacy / Visibility</p>
        <p class="info-card__meta">Current mode: ${escapeHtml(mode.replaceAll("_", " "))}</p>
        <p class="info-card__meta">The senior should be informed whenever family visibility changes.</p>
      </article>`;
    const noteTitle = familyMode
      ? (selectedMember ? `Note for ${escapeHtml(selectedMember)}` : "Notes for family members")
      : "Note from your family";
    const notesHtml = `
      <article class="info-card">
        <p class="info-card__title">${noteTitle}</p>
        <p class="info-card__meta">${escapeHtml(note || "No note yet.")}</p>
      </article>`;

    const tabMap = {
      overview: `${overviewHtml}${alertsHtml}`,
      alerts: alertsHtml,
      medications: medsHtml,
      appointments: apptsHtml,
      privacy: `${privacyHtml}<article class="info-card"><p class="info-card__title">Family permissions</p>${manageBlock}</article>`,
      notes: notesHtml,
    };

    family.innerHTML = `<div class="single-view-list">${tabMap[activeFamilyTab] || tabMap.overview}</div>`;
    $("#family-manage-meds")?.addEventListener("click", async () => {
      setActiveView("medications");
      await loadMedicationsView();
    });
    $("#family-manage-appts")?.addEventListener("click", async () => {
      setActiveView("appointments");
      await loadAppointmentsView();
    });
  }
  $all(".family-subnav__btn").forEach(btn => {
    btn.classList.toggle("is-active", btn.dataset.familyTab === activeFamilyTab);
  });

  const noteInput = $("#family-note-input");
  const saveBtn = $("#btn-save-family-note");
  if (noteInput) {
    noteInput.readOnly = false;
    noteInput.disabled = false;
    noteInput.value = note;
    noteInput.placeholder = selectedMember ? `Write a note for ${selectedMember}…` : "Write a short encouraging message…";
    noteInput.title = "";
    noteInput.style.opacity = "";
    noteInput.style.cursor = "";
  }
  if (saveBtn) {
    saveBtn.hidden = false;
    saveBtn.disabled = false;
  }
}

// ── Chat ───────────────────────────────────────

async function loadChatHistory() {
  const log = $("#chat-log");
  if (!log) return;
  const { messages } = await api("/api/chat/history");
  const boot = await api("/api/bootstrap?session_id=" + encodeURIComponent(sessionId));
  const emptyState = $("#chat-empty-state");
  if (emptyState) {
    const name = boot.persona?.name?.trim() || "friend";
    emptyState.textContent = `Hello ${name}, how can I help today?`;
  }
  log.innerHTML = "";
  const hasMessages = messages.length > 0;
  if (emptyState) emptyState.hidden = hasMessages;
  for (const m of messages) appendMessage(m.role, m.content, false);
  log.scrollTop = log.scrollHeight;
}

function appendMessage(role, content, scroll = true) {
  const log = $("#chat-log");
  if (!log) return;
  $("#chat-empty-state")?.setAttribute("hidden", "hidden");
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

function appendImageMessage(file, scroll = true) {
  const log = $("#chat-log");
  if (!log || !file) return;
  $("#chat-empty-state")?.setAttribute("hidden", "hidden");
  const outer = document.createElement("div");
  outer.className = "msg msg--user";
  const timeStr = ts();
  const imageUrl = URL.createObjectURL(file);
  outer.innerHTML = `
    <div class="msg__body">
      <div class="msg__image-bubble">
        <img class="msg__image-preview" src="${escapeAttr(imageUrl)}" alt="Uploaded image preview" />
        <div class="msg__image-caption">Image uploaded</div>
      </div>
      <span class="msg__time">${timeStr}</span>
    </div>
    <div class="msg__avatar">You</div>`;
  log.appendChild(outer);
  const img = outer.querySelector(".msg__image-preview");
  img?.addEventListener("load", () => URL.revokeObjectURL(imageUrl), { once: true });
  img?.addEventListener("error", () => URL.revokeObjectURL(imageUrl), { once: true });
  if (scroll) log.scrollTop = log.scrollHeight;
}

function appendLoading() {
  const log = $("#chat-log");
  if (!log) return null;
  $("#chat-empty-state")?.setAttribute("hidden", "hidden");
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

async function buildMockAssistantReply(text) {
  const ask = (text || "").toLowerCase();
  const rows = await api("/api/reminders");
  const meds = rows.filter(r => classifyTaskType(r) === "medication");
  const appts = rows.filter(r => classifyTaskType(r) === "appointment");
  const routines = rows.filter(r => classifyTaskType(r) === "routine");
  if (ask.includes("what do i need") || ask.includes("today")) {
    const nextThree = rows
      .filter(r => r.status !== "completed")
      .sort((a, b) => `${a.reminder_date}T${a.reminder_time}`.localeCompare(`${b.reminder_date}T${b.reminder_time}`))
      .slice(0, 3);
    if (!nextThree.length) {
      return "A quiet day today 🌿 You do not have any pending tasks right now.";
    }
    const list = nextThree.map(r => `${r.title} at ${r.reminder_time}`).join(", ");
    return `You have ${nextThree.length} important thing${nextThree.length > 1 ? "s" : ""} today: ${list}. I'll remind you when each one is coming up.`;
  }
  if (ask.includes("why do i take")) {
    const medName = meds[0]?.title || "this medication";
    return `${medName} is commonly used to support your treatment plan. I can help explain this in simple terms, but you should follow your doctor or pharmacist's instructions.`;
  }
  if (ask.includes("appointment") || ask.includes("bring")) {
    const next = appts.sort((a, b) => `${a.reminder_date}T${a.reminder_time}`.localeCompare(`${b.reminder_date}T${b.reminder_time}`))[0];
    if (!next) return "You do not have an upcoming appointment saved right now.";
    return `Your next appointment is ${next.title} on ${fmtDate(next.reminder_date)} at ${next.reminder_time}. You may want to bring your insurance card and medication list.`;
  }
  if (ask.includes("organized") || ask.includes("help")) {
    return "You're doing a good job staying organized. Let's focus on one next step at a time.";
  }
  return `You currently have ${meds.length} medication task(s), ${appts.length} appointment task(s), and ${routines.length} routine task(s). Here's what's next: ${rows.find(r => r.status !== "completed")?.title || "You're all caught up."}`;
}

async function sendChatMessage(text) {
  const loading = appendLoading();
  const btn = $("#chat-send");
  if (!btn) return;
  btn.disabled = true;
  try {
    const out = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) });
    loading?.remove();
    appendMessage("assistant", ensureMedicalSafetyText(text, out.reply));
  } catch (e) {
    loading?.remove();
    const mock = await buildMockAssistantReply(text);
    appendMessage("assistant", ensureMedicalSafetyText(text, mock));
    toast("Using mock assistant response while live AI is unavailable.", true);
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
  if (!input) return;
  const chatForm = $("#chat-form");
  const chatImage = $("#chat-image");
  if (!chatForm || !chatImage) return;
  const voiceBtn = $("#chat-voice-btn");
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let isListening = false;

  if (voiceBtn) {
    if (SpeechRecognition) {
      recognition = new SpeechRecognition();
      recognition.lang = document.documentElement.lang || "en-US";
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      recognition.addEventListener("result", (event) => {
        const transcript = Array.from(event.results)
          .map(result => result[0]?.transcript || "")
          .join(" ")
          .trim();
        if (!transcript) return;
        input.value = transcript;
        autoGrow(input);
      });

      recognition.addEventListener("end", () => {
        isListening = false;
        voiceBtn.setAttribute("aria-pressed", "false");
        voiceBtn.title = "Use voice input";
      });

      recognition.addEventListener("error", () => {
        isListening = false;
        voiceBtn.setAttribute("aria-pressed", "false");
        voiceBtn.title = "Use voice input";
        toast("Voice input is unavailable right now.", true);
      });

      voiceBtn.addEventListener("click", () => {
        if (!recognition) return;
        if (isListening) {
          recognition.stop();
          return;
        }
        try {
          recognition.start();
          isListening = true;
          voiceBtn.setAttribute("aria-pressed", "true");
          voiceBtn.title = "Listening… tap to stop";
          input.focus();
        } catch {
          toast("Voice input is unavailable right now.", true);
        }
      });
    } else {
      voiceBtn.addEventListener("click", () => {
        toast("Voice input is coming soon on this device.");
      });
    }
  }

  input.addEventListener("input", () => autoGrow(input));
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      chatForm.requestSubmit();
    }
  });

  chatForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    autoGrow(input);
    appendMessage("user", text);
    await sendChatMessage(text);
  });

  chatImage.addEventListener("change", async (ev) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    appendImageMessage(file);
    const loading = appendLoading();
    try {
      const res = await fetch("/api/chat/image", {
        method: "POST",
        headers: { "X-Session-Id": sessionId },
        body: fd,
      });
      const data = await res.json();
      loading?.remove();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      appendMessage("assistant", ensureMedicalSafetyText("medicine label image", data.reply));
    } catch (e) {
      loading?.remove();
      toast(e.message, true);
    }
  });
}

function setupAssistantPrompts() {
  $all(".assistant-prompt-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const prompt = btn.dataset.prompt || "";
      const input = $("#chat-input");
      if (!input) return;
      setActiveView("assistant");
      input.value = prompt;
      input.focus();
      autoGrow(input);
    });
  });
}

function setupAssistantStandalone() {
  // Dedicated assistant tab uses the main chat composer.
}

function setupFamilyTabs() {
  $all(".family-subnav__btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      activeFamilyTab = btn.dataset.familyTab || "overview";
      await loadFamilyView();
    });
  });
}

function setupPrimaryNav() {
  $all(".primary-nav__btn, .bottom-nav__btn, .sidebar-nav-item").forEach(btn => {
    btn.addEventListener("click", async () => {
      const view = btn.dataset.view || "today";
      setActiveView(view);
      if (view === "medications") await loadMedicationsView();
      if (view === "appointments") await loadAppointmentsView();
      if (view === "progress") await loadProgressView();
      if (view === "family") await loadFamilyView();
      if (view === "assistant") setupAssistantStandalone();
    });
  });
  const route = getRouteViewFromUrl();
  if (route) setActiveView(route, { updateUrl: false });
  window.addEventListener("popstate", async () => {
    const next = getRouteViewFromUrl() || "today";
    setActiveView(next, { updateUrl: false });
    if (next === "medications") await loadMedicationsView();
    if (next === "appointments") await loadAppointmentsView();
    if (next === "progress") await loadProgressView();
    if (next === "family") await loadFamilyView();
    if (next === "assistant") setupAssistantStandalone();
  });
}

function setupTodayStackedCards() {
  const todayCol = $("#view-today .col-left");
  if (!todayCol) return;

  todayCol.classList.add("today-stack");
  const widgets = $all(".widget", todayCol);
  widgets.forEach((widget) => {
    if (widget.dataset.stackedReady === "true") return;
    const header = $(".widget__header", widget);
    const title = $(".widget__title", widget);
    if (!header || !title) return;

    const body = document.createElement("div");
    body.className = "stacked-body";

    while (widget.children.length > 1) {
      body.appendChild(widget.children[1]);
    }
    widget.appendChild(body);

    const titleText = title.textContent?.trim() || "Section";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "stacked-title-btn";
    trigger.setAttribute("aria-expanded", "false");
    trigger.innerHTML = `
      <span class="stacked-title-btn__label">${escapeHtml(titleText)}</span>
      <span class="stacked-title-btn__chevron" aria-hidden="true">▾</span>
    `;

    title.textContent = "";
    title.appendChild(trigger);
    widget.classList.add("widget--stacked");
    widget.dataset.stackedReady = "true";

    trigger.addEventListener("click", () => {
      const expanded = widget.classList.toggle("is-expanded");
      trigger.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
  });
}

function setupExtraActions() {
  $("#btn-add-medication")?.addEventListener("click", () => {
    $("#btn-open-reminder")?.click();
    $("#form-reminder")?.kind && ($("#form-reminder").kind.value = "medicine");
  });
  $("#btn-add-appointment")?.addEventListener("click", () => {
    $("#btn-open-reminder")?.click();
    $("#form-reminder")?.kind && ($("#form-reminder").kind.value = "general");
  });
  $("#btn-save-family-note")?.addEventListener("click", async () => {
    const input = $("#family-note-input");
    const note = input?.value?.trim();
    if (!note) {
      toast("Please enter a short note first.", true);
      return;
    }
    const noteKey = selectedMember || "general";
    saveFamilyNote(noteKey, note);
    localStorage.setItem(FAMILY_NOTE_KEY, note);
    toast(selectedMember ? `Note saved for ${selectedMember}.` : "Family note saved.");
    await Promise.all([loadFamilyView(), loadDashboard()]);
  });
}

function captureOnboardingStepInputs() {
  if (onboardingStep === 3) {
    saveOnboarding({
      wake_time: $("#ob-wake-time")?.value || onboardingData.wake_time,
      med_time: $("#ob-med-time")?.value || onboardingData.med_time,
      appointment_reminder: $("#ob-appt-reminder")?.value || onboardingData.appointment_reminder,
      wellness_task: $("#ob-wellness-task")?.value?.trim() || onboardingData.wellness_task,
    });
  }
  if (onboardingStep === 4) {
    saveOnboarding({
      medication_name: $("#ob-med-name")?.value?.trim() || "",
      medication_dosage: $("#ob-med-dose")?.value?.trim() || "",
      medication_time: $("#ob-med-time-2")?.value || onboardingData.medication_time,
      medication_days: $("#ob-med-days")?.value?.trim() || onboardingData.medication_days,
      medication_instructions: $("#ob-med-inst")?.value?.trim() || "",
    });
  }
  if (onboardingStep === 5) {
    saveOnboarding({
      appointment_title: $("#ob-appt-title")?.value?.trim() || "",
      appointment_datetime: $("#ob-appt-dt")?.value || "",
      appointment_location: $("#ob-appt-location")?.value?.trim() || "",
      appointment_notes: $("#ob-appt-notes")?.value?.trim() || "",
    });
  }
  if (onboardingStep === 7) {
    saveOnboarding({
      text_size: $("#ob-text-size")?.value || onboardingData.text_size,
      high_contrast: !!$("#ob-high-contrast")?.checked,
      reduce_motion: !!$("#ob-reduce-motion")?.checked,
      voice_prompts_enabled: !!$("#ob-voice-prompts")?.checked,
    });
  }
}

async function finalizeOnboarding() {
  saveOnboarding({ completed: true });
  if (onboardingData.role_choice === "family" && onboardingData.family_members?.length > 0) {
    saveFamilyMembers(onboardingData.family_members);
  }
  const uiPrefs = {
    visibility_mode: onboardingData.visibility_mode,
    text_size: onboardingData.text_size,
    high_contrast: onboardingData.high_contrast,
    reduce_motion: onboardingData.reduce_motion,
    voice_prompts_enabled: onboardingData.voice_prompts_enabled,
  };
  saveUiPrefs(uiPrefs);
  applyAccessibilityFromPrefs(uiPrefs);

  try {
    const boot = await api("/api/bootstrap?session_id=" + encodeURIComponent(sessionId));
    await api("/api/persona", {
      method: "PUT",
      body: JSON.stringify({
        name: boot.persona.name || (onboardingData.role_choice === "family" ? "Loved one" : "Mary"),
        age: boot.persona.age || "74",
        language: boot.persona.language || "English",
        timezone: boot.persona.timezone || "UTC",
        reminder_style: boot.persona.reminder_style || "gentle",
        notification_channel: boot.notification_channel || "email",
        notification_destination: boot.notification_destination || "",
      }),
    });

    const todayIso = new Date().toISOString().slice(0, 10);
    if (onboardingData.medication_name) {
      const medPayload = {
        kind: "medicine",
        title: onboardingData.medication_name,
        reminder_date: todayIso,
        reminder_time: onboardingData.medication_time || "08:30",
        place: "Home",
        notes: `${onboardingData.medication_dosage || ""} ${onboardingData.medication_instructions || ""}`.trim(),
        schedule_type: "daily",
        schedule_detail: onboardingData.medication_days || "",
      };
      await api("/api/reminders", {
        method: "POST",
        body: JSON.stringify(medPayload),
      });
      const medId = await findCreatedReminderId(medPayload);
      if (medId) {
        upsertTaskMeta(medId, { task_type: "medication", is_critical: true, reminder_offsets: [15, 45] });
      }
    }
    if (onboardingData.appointment_title && onboardingData.appointment_datetime) {
      const dt = new Date(onboardingData.appointment_datetime);
      const isoDate = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
      const t = `${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
      const apptPayload = {
        kind: "general",
        title: onboardingData.appointment_title,
        reminder_date: isoDate,
        reminder_time: t,
        place: onboardingData.appointment_location || "",
        notes: onboardingData.appointment_notes || "",
        schedule_type: "once",
        schedule_detail: "",
      };
      await api("/api/reminders", {
        method: "POST",
        body: JSON.stringify(apptPayload),
      });
      const apptId = await findCreatedReminderId(apptPayload);
      if (apptId) {
        upsertTaskMeta(apptId, { task_type: "appointment", is_critical: false, reminder_offsets: [1440, 120, 15] });
      }
    }
  } catch (e) {
    toast(`Onboarding saved, but some setup steps did not finish: ${e.message}`, true);
  }

  setActiveView("today");
  await Promise.all([
    loadDashboard(),
    loadMedicationsView(),
    loadAppointmentsView(),
    loadProgressView(),
    loadFamilyView(),
    loadSidebarUpcoming(),
  ]);
  toast("Welcome to CareBuddy. You're all set.");
}

function setupOnboarding() {
  loadOnboarding();
  // Sync family_members from onboardingData into dedicated storage if needed
  if (onboardingData.role_choice === "family" && onboardingData.family_members?.length > 0) {
    const stored = getFamilyMembers();
    if (stored.length === 0) saveFamilyMembers(onboardingData.family_members);
  }
  if (!onboardingData.completed) {
    setActiveView("onboarding");
  }
  renderOnboarding();
  $("#onboarding-back")?.addEventListener("click", () => {
    captureOnboardingStepInputs();
    onboardingStep = Math.max(0, onboardingStep - 1);
    renderOnboarding();
  });
  $("#onboarding-next")?.addEventListener("click", async () => {
    captureOnboardingStepInputs();
    if (onboardingStep === 1 && onboardingData.role_choice === "family") {
      if (!onboardingData.family_members || onboardingData.family_members.length === 0) {
        toast("Please add at least one family member to continue.", true);
        return;
      }
      saveFamilyMembers(onboardingData.family_members);
    }
    if (onboardingStep < ONBOARDING_STEPS.length - 1) {
      onboardingStep += 1;
      renderOnboarding();
      return;
    }
    await finalizeOnboarding();
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
    f.reminder_offsets.value = "1440,120,15";
    f.is_critical.checked = true;
    // Show "For member" field only in family mode
    const forMemberField = $("#field-for-member");
    const forMemberSelect = $("#reminder-for-member");
    const members = getFamilyMembers();
    const showMemberField = onboardingData.role_choice === "family" && members.length > 0;
    if (forMemberField) forMemberField.style.display = showMemberField ? "" : "none";
    if (showMemberField && forMemberSelect) {
      forMemberSelect.innerHTML = `<option value="">— select member —</option>` +
        members.map(m => `<option value="${escapeAttr(m)}" ${selectedMember === m ? "selected" : ""}>${escapeHtml(m)}</option>`).join("");
    }
    openModal("#modal-reminder");
  };

  $("#btn-open-reminder")?.addEventListener("click", openReminder);
  $("#btn-open-reminder-tab")?.addEventListener("click", openReminder);

  const openSettings = async () => {
    const boot = await api("/api/bootstrap?session_id=" + encodeURIComponent(sessionId));
    fillSettingsForm(boot);
    openModal("#modal-settings");
  };
  $("#btn-open-settings")?.addEventListener("click", openSettings);
  $("#btn-open-settings-top")?.addEventListener("click", openSettings);

  const btnEditProfile = $("#btn-edit-profile");
  if (btnEditProfile) {
    btnEditProfile.addEventListener("click", async () => {
      const boot = await api("/api/bootstrap?session_id=" + encodeURIComponent(sessionId));
      fillSettingsForm(boot);
      openModal("#modal-settings");
    });
  }

  $("#btn-retake-setup")?.addEventListener("click", () => {
    if (!confirm("Retake your 9-step personal setup now?")) return;
    onboardingStep = 0;
    onboardingData = { ...ONBOARDING_DEFAULTS, completed: false };
    localStorage.setItem(ONBOARDING_KEY, JSON.stringify(onboardingData));
    closeModals();
    setActiveView("onboarding");
    renderOnboarding();
    toast("Personal setup restarted.");
  });

  const reminderForm = $("#form-reminder");
  const settingsForm = $("#form-settings");
  if (!reminderForm || !settingsForm) return;

  reminderForm.addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    const offsets = String(f.reminder_offsets.value || "")
      .split(",")
      .map(x => Number(x.trim()))
      .filter(x => Number.isFinite(x) && x >= 0);
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
      const createdId = await findCreatedReminderId(payload);
      if (createdId) {
        const taskTypeMap = {
          medicine: "medication",
          general: "appointment",
          routine: "routine",
          family_note: "family_note",
        };
        const forMember = (f.for_member?.value || "").trim();
        upsertTaskMeta(createdId, {
          task_type: taskTypeMap[f.kind.value] || "routine",
          reminder_offsets: offsets,
          is_critical: !!f.is_critical.checked,
          member: forMember,
        });
      }
      toast("Reminder saved.");
      closeModals();
      await Promise.all([loadDashboard(), loadMedicationsView(), loadAppointmentsView(), loadProgressView(), loadSidebarUpcoming()]);
    } catch (e) {
      toast(e.message, true);
    }
  });

  settingsForm.addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    const uiPrefs = {
      visibility_mode: f.visibility_mode.value,
      text_size: f.text_size.value,
      high_contrast: f.high_contrast.checked,
      reduce_motion: f.reduce_motion.checked,
      voice_prompts_enabled: f.voice_prompts_enabled.checked,
      reminder_sound: f.reminder_sound.value,
      reminder_frequency: f.reminder_frequency.value,
      snooze_duration: Number(f.snooze_duration.value || 15),
      family_alert_delay: Number(f.family_alert_delay.value || 45),
    };
    saveUiPrefs(uiPrefs);
    applyAccessibilityFromPrefs(uiPrefs);
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
    const maskedValue = (f.openai_api_key.dataset.maskedValue || "").trim();
    if (key && key !== maskedValue) payload.openai_api_key = key;
    try {
      await api("/api/persona", { method: "PUT", body: JSON.stringify(payload) });
      toast("Settings saved.");
      closeModals();
      await Promise.all([loadDashboard(), loadMedicationsView(), loadFamilyView()]);
    } catch (e) {
      toast(e.message, true);
    }
  });
}

// ── Reminder cards ─────────────────────────────

function reminderCard(r, prefix) {
  const uid = `${prefix}-${r.id}`;
  const taskType = classifyTaskType(r);
  const offsets = reminderOffsets(r).join(",");
  const critical = isCriticalTask(r);
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
            <option value="general">Appointment</option>
            <option value="routine">Routine</option>
            <option value="family_note">Family note</option>
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
        <div class="field">
          <label class="field-label">Task type</label>
          <select class="field-input" data-field="task_type" id="${uid}-task-type">
            <option value="medication">Medication</option>
            <option value="appointment">Appointment</option>
            <option value="routine">Routine</option>
            <option value="family_note">Family note</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">Reminder offsets (min)</label>
          <input class="field-input" type="text" data-field="reminder_offsets" id="${uid}-offsets" value="${escapeAttr(offsets)}" />
          <label class="field-checkbox"><input type="checkbox" data-field="is_critical" id="${uid}-critical" ${critical ? "checked" : ""}/> Critical task</label>
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
      const offsets = String(card.querySelector('[data-field="reminder_offsets"]').value || "")
        .split(",")
        .map(x => Number(x.trim()))
        .filter(x => Number.isFinite(x) && x >= 0);
      const metaPatch = {
        task_type: card.querySelector('[data-field="task_type"]').value,
        reminder_offsets: offsets,
        is_critical: !!card.querySelector('[data-field="is_critical"]').checked,
      };
      try {
        await api(`/api/reminders/${rid}`, { method: "PATCH", body: JSON.stringify(payload) });
        upsertTaskMeta(rid, metaPatch);
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
    const rowsMeta = loadTaskMeta();
    const rowMeta = rowsMeta[id] || {};
    const taskTypeEl = card.querySelector('[data-field="task_type"]');
    const kindEl = card.querySelector('[data-field="kind"]');
    const inferred = kindEl?.value === "medicine"
      ? "medication"
      : kindEl?.value === "general"
        ? "appointment"
        : (kindEl?.value || "routine");
    if (taskTypeEl) taskTypeEl.value = rowMeta.task_type || inferred;
  });
}

async function loadAllReminders() {
  const stack = $("#all-reminders");
  if (!stack) return;
  const rows = await api("/api/reminders");
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
  if (!body || !dateCtr) return;
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
  if (!sidebar || !scrim || !toggle) return;
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
    applyTheme(localStorage.getItem(THEME_KEY) || "dark");
    applyAccessibilityFromPrefs();
    const boot = await ensureSession();
    await loadMeta();
    fillSettingsForm(boot);

    const hint = $("#api-key-hint");
    if (boot.has_server_openai_key) {
      hint.textContent = "Server API key is active.";
    } else {
      hint.innerHTML = `Open <strong>Settings</strong> to add your OpenAI key.`;
    }

    setupThemeToggle();
    setupTabs();
    setupModals();
    setupChat();
    setupAssistantPrompts();
    setupAssistantStandalone();
    setupFamilyTabs();
    setupExtraActions();
    setupOnboarding();
    setupPrimaryNav();
    setupTodayStackedCards();
    setupCalendarMode();
    setupSidebar();

    await Promise.all([
      loadDashboard(),
      loadMedicationsView(),
      loadAppointmentsView(),
      loadProgressView(),
      loadFamilyView(),
      loadChatHistory(),
      loadSidebarUpcoming(),
    ]);
  } catch (e) {
    toast(e.message || "Failed to start", true);
    console.error(e);
  }
}

init();
