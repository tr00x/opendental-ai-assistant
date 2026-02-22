/* ================================================================
   kiosk.js — Patient kiosk: language switching, 3-mode search,
               screen transitions, last-visit display, countdown.
   ================================================================ */

// ── Translations ────────────────────────────────────────────────
const STR = {
  en: {
    tagline:           "Patient Appointment Lookup",
    welcome_title:     "Welcome!",
    welcome_sub:       "Find your appointment using your last name, date of birth, or phone number.",
    lbl_lastname:      "Last Name",
    lbl_lastname_sub:  "Apellido",
    lbl_dob:           "Date of Birth",
    lbl_dob_sub:       "Fecha de Nacimiento",
    lbl_phone:         "Phone Number",
    lbl_phone_sub:     "Número de Teléfono",
    ph_lastname:       "e.g. Smith",
    ph_dob:            "MM/DD/YYYY",
    ph_phone:          "(516) 555-1234",
    btn_search:        "🔍  Find My Appointment",
    btn_searching:     "Searching…",
    or:                "or",
    results_title:     "We found a few matches.",
    results_sub:       "Please select your name:",
    back:              "← Back",
    lbl_provider:      "Provider",
    lbl_room:          "Room",
    lbl_visit:         "Today's visit",
    lbl_last_visit:    "Last visit",
    no_last_visit:     "First visit",
    card_msg:          "Please have a seat — we'll call you shortly 😊",
    card_msg_sub:      "Por favor tome asiento — le llamaremos pronto 😊",
    countdown_label:   "Returning to home screen",
    err_empty:         "Please enter your last name, date of birth, or phone number.",
    err_not_found:     "We don't see you on today's schedule.\nPlease see our receptionist.",
    err_dob:           "Invalid date. Please enter in MM/DD/YYYY format.",
    err_phone_short:   "Please enter at least 7 digits.",
    err_connection:    "Connection error. Please see the receptionist.",
  },
  es: {
    tagline:           "Consulta de Cita del Paciente",
    welcome_title:     "¡Bienvenidos!",
    welcome_sub:       "Encuentre su cita con su apellido, fecha de nacimiento o número de teléfono.",
    lbl_lastname:      "Apellido",
    lbl_lastname_sub:  "Last Name",
    lbl_dob:           "Fecha de Nacimiento",
    lbl_dob_sub:       "Date of Birth",
    lbl_phone:         "Número de Teléfono",
    lbl_phone_sub:     "Phone Number",
    ph_lastname:       "p.ej. García",
    ph_dob:            "MM/DD/AAAA",
    ph_phone:          "(516) 555-1234",
    btn_search:        "🔍  Buscar Mi Cita",
    btn_searching:     "Buscando…",
    or:                "o",
    results_title:     "Encontramos varias coincidencias.",
    results_sub:       "Por favor seleccione su nombre:",
    back:              "← Regresar",
    lbl_provider:      "Doctor/a",
    lbl_room:          "Sala",
    lbl_visit:         "Visita de hoy",
    lbl_last_visit:    "Última visita",
    no_last_visit:     "Primera visita",
    card_msg:          "Por favor tome asiento — le llamaremos pronto 😊",
    card_msg_sub:      "Please have a seat — we'll call you shortly 😊",
    countdown_label:   "Regresando a la pantalla inicial",
    err_empty:         "Por favor ingrese su apellido, fecha de nacimiento o teléfono.",
    err_not_found:     "No encontramos su cita hoy.\nPor favor comuníquese con nuestra recepcionista.",
    err_dob:           "Fecha inválida. Use el formato MM/DD/AAAA.",
    err_phone_short:   "Por favor ingrese al menos 7 dígitos.",
    err_connection:    "Error de conexión. Por favor vea a la recepcionista.",
  },
};

// ── State ────────────────────────────────────────────────────────
let LANG    = localStorage.getItem("kiosk_lang") || "en";
let results = [];
let cdTimer = null;
const COUNTDOWN_TOTAL  = 30;
const CIRCUMFERENCE    = 2 * Math.PI * 30; // r=30 matches SVG

// ── Language ─────────────────────────────────────────────────────
function t(key) { return STR[LANG][key] || key; }

function setLang(lang) {
  LANG = lang;
  localStorage.setItem("kiosk_lang", lang);

  // Toggle button states
  document.querySelectorAll(".lang-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.lang === lang);
  });

  // Update all data-key elements
  document.querySelectorAll("[data-key]").forEach(el => {
    const val = t(el.dataset.key);
    if (el.tagName === "INPUT") {
      el.placeholder = val;
    } else {
      el.textContent = val;
    }
  });

  // Update search button (not disabled, just text)
  const btn = document.getElementById("btn-search");
  if (!btn.disabled) btn.textContent = t("btn_search");
}

// ── Screen transitions ────────────────────────────────────────────
function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}

// ── Error / info messages ─────────────────────────────────────────
function setMsg(text, type = "error") {
  const el = document.getElementById("search-msg");
  if (!text) { el.className = "msg-box hidden"; return; }
  el.className = `msg-box ${type}`;
  el.textContent = text;
}

// ── Search ────────────────────────────────────────────────────────
async function doSearch() {
  const lastname = document.getElementById("input-lastname").value.trim();
  const dob      = document.getElementById("input-dob").value.trim();
  const phone    = document.getElementById("input-phone").value.replace(/\D/g, "");

  if (!lastname && !dob && !phone) {
    setMsg(t("err_empty"));
    return;
  }

  setMsg("");
  const btn = document.getElementById("btn-search");
  btn.textContent = t("btn_searching");
  btn.disabled = true;

  try {
    let url;
    if (lastname) {
      url = `/kiosk/search?q=${encodeURIComponent(lastname)}`;
    } else if (dob) {
      url = `/kiosk/search?dob=${encodeURIComponent(dob)}`;
    } else {
      if (phone.length < 7) {
        setMsg(t("err_phone_short"));
        return;
      }
      url = `/kiosk/search?phone=${encodeURIComponent(phone)}`;
    }

    const res  = await fetch(url);
    const data = await res.json();

    if (data.error === "dob_invalid")   { setMsg(t("err_dob"));         return; }
    if (data.error === "phone_short")   { setMsg(t("err_phone_short"));  return; }
    if (data.error === "db_unavailable"){ setMsg(t("err_connection"));   return; }

    results = data.results || [];

    if (results.length === 0) {
      setMsg(t("err_not_found"), "info");
    } else if (results.length === 1) {
      showCard(results[0]);
    } else {
      showResultsList(results);
    }

  } catch {
    setMsg(t("err_connection"));
  } finally {
    btn.textContent = t("btn_search");
    btn.disabled = false;
  }
}

// ── Results list ──────────────────────────────────────────────────
function showResultsList(apts) {
  document.getElementById("results-title").textContent = t("results_title");
  document.getElementById("results-sub").textContent   = t("results_sub");

  const list = document.getElementById("results-list");
  list.innerHTML = "";

  apts.forEach(apt => {
    const initial     = (apt.PatFName || "?")[0].toUpperCase();
    const displayName = `${apt.PatFName} ${(apt.PatLName || "?")[0]}.`;

    const btn = document.createElement("button");
    btn.className = "result-btn";
    btn.innerHTML = `
      <div class="result-avatar">${initial}</div>
      <span>${displayName}</span>
      <span class="result-time">${apt.time}</span>
    `;
    btn.addEventListener("click", () => showCard(apt));
    list.appendChild(btn);
  });

  showScreen("screen-results");
}

// ── Appointment card ──────────────────────────────────────────────
function showCard(apt) {
  document.getElementById("card-name").textContent = `${apt.PatFName} ${apt.PatLName}`;
  document.getElementById("card-time").textContent = apt.time;

  // Patient photo — replaces the checkmark when available
  const photoWrap = document.getElementById("card-photo-wrap");
  const checkmark = document.getElementById("card-check");
  const photoImg  = document.getElementById("card-photo");

  // Reset: show checkmark, hide photo while loading
  photoWrap.classList.add("hidden");
  checkmark.classList.remove("hidden");
  photoImg.src = "";

  if (apt.pat_num) {
    photoImg.onload = () => {
      checkmark.classList.add("hidden");
      photoWrap.classList.remove("hidden");
    };
    photoImg.onerror = () => {
      photoWrap.classList.add("hidden");
      checkmark.classList.remove("hidden");
    };
    photoImg.src = `/kiosk/photo/${apt.pat_num}`;
  }

  // Detail rows
  const details = document.getElementById("apt-details");
  details.innerHTML = "";

  const rows = [
    { icon: "👨‍⚕️", lbl: t("lbl_provider"), val: apt.provider },
  ];
  if (apt.room) {
    rows.push({ icon: "📍", lbl: t("lbl_room"), val: apt.room });
  }
  rows.push({ icon: "🦷", lbl: t("lbl_visit"), val: apt.procedure });
  rows.push({
    icon: "📅",
    lbl:  t("lbl_last_visit"),
    val:  apt.last_visit || t("no_last_visit"),
  });

  rows.forEach(r => {
    const row = document.createElement("div");
    row.className = "detail-row";
    row.innerHTML = `
      <span class="d-icon">${r.icon}</span>
      <span class="d-lbl">${r.lbl}</span>
      <span class="d-val">${r.val}</span>
    `;
    details.appendChild(row);
  });

  // Card message (language-aware)
  document.getElementById("card-msg-main").textContent = t("card_msg");
  document.getElementById("card-msg-sub").textContent  = t("card_msg_sub");

  showScreen("screen-card");
  startCountdown();
}

// ── Countdown ─────────────────────────────────────────────────────
function startCountdown() {
  stopCountdown();
  let secs = COUNTDOWN_TOTAL;
  updateCD(secs);

  cdTimer = setInterval(() => {
    secs -= 1;
    updateCD(secs);
    if (secs <= 0) { stopCountdown(); resetToWelcome(); }
  }, 1000);
}

function stopCountdown() {
  if (cdTimer) { clearInterval(cdTimer); cdTimer = null; }
}

function updateCD(s) {
  document.getElementById("countdown-num").textContent = s;
  const offset = CIRCUMFERENCE * (1 - s / COUNTDOWN_TOTAL);
  const circle = document.getElementById("countdown-circle");
  circle.style.strokeDasharray  = CIRCUMFERENCE;
  circle.style.strokeDashoffset = offset;
}

// ── Reset ─────────────────────────────────────────────────────────
function resetToWelcome() {
  stopCountdown();
  results = [];
  document.getElementById("input-lastname").value = "";
  document.getElementById("input-dob").value      = "";
  document.getElementById("input-phone").value    = "";
  setMsg("");
  // Reset avatar: hide photo, restore checkmark
  const photoWrap = document.getElementById("card-photo-wrap");
  const checkmark = document.getElementById("card-check");
  const photoImg  = document.getElementById("card-photo");
  if (photoWrap) photoWrap.classList.add("hidden");
  if (checkmark) checkmark.classList.remove("hidden");
  if (photoImg)  photoImg.src = "";
  showScreen("screen-welcome");
  document.getElementById("input-lastname").focus();
}

// ── Input helpers ─────────────────────────────────────────────────
function clearOthers(exceptId) {
  ["input-lastname","input-dob","input-phone"]
    .filter(id => id !== exceptId)
    .forEach(id => { document.getElementById(id).value = ""; });
  setMsg("");
}

function formatDOB(e) {
  const input = e.target;
  const raw   = input.value.replace(/\D/g, "").slice(0, 8);
  let out = raw;
  if (raw.length > 4)      out = `${raw.slice(0,2)}/${raw.slice(2,4)}/${raw.slice(4)}`;
  else if (raw.length > 2) out = `${raw.slice(0,2)}/${raw.slice(2)}`;
  input.value = out;
  clearOthers("input-dob");
}

function formatPhone(e) {
  const input  = e.target;
  const digits = input.value.replace(/\D/g, "").slice(0, 10);
  let out = digits;
  if (digits.length > 6)      out = `(${digits.slice(0,3)}) ${digits.slice(3,6)}-${digits.slice(6)}`;
  else if (digits.length > 3) out = `(${digits.slice(0,3)}) ${digits.slice(3)}`;
  else if (digits.length > 0) out = `(${digits}`;
  input.value = out;
  clearOthers("input-phone");
}

// ── Init ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Language buttons
  document.querySelectorAll(".lang-btn").forEach(btn => {
    btn.addEventListener("click", () => setLang(btn.dataset.lang));
  });

  // Search button
  document.getElementById("btn-search").addEventListener("click", doSearch);

  // Enter key
  ["input-lastname","input-dob","input-phone"].forEach(id => {
    const el = document.getElementById(id);
    el.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
  });

  // Last-name: just clears others
  document.getElementById("input-lastname").addEventListener("input", () => clearOthers("input-lastname"));

  // DOB: auto-format
  document.getElementById("input-dob").addEventListener("input", formatDOB);

  // Phone: auto-format
  document.getElementById("input-phone").addEventListener("input", formatPhone);

  // Back buttons
  document.getElementById("btn-back-results").addEventListener("click", resetToWelcome);
  document.getElementById("btn-back-card").addEventListener("click", () => { stopCountdown(); resetToWelcome(); });

  // Apply current language
  setLang(LANG);
  showScreen("screen-welcome");
  document.getElementById("input-lastname").focus();
});
