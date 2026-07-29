import { initializeApp } from "https://www.gstatic.com/firebasejs/12.10.0/firebase-app.js"
import { getDatabase, limitToLast, onValue, query, ref } from "https://www.gstatic.com/firebasejs/12.10.0/firebase-database.js"

const config = {
  apiKey: "AIzaSyAm2p01fVffl6FGh46J2xmMzjAA7D4Kl4k",
  authDomain: "genius-final.firebaseapp.com",
  databaseURL: "https://genius-final-default-rtdb.europe-west1.firebasedatabase.app",
  projectId: "genius-final",
  storageBucket: "genius-final.firebasestorage.app",
  messagingSenderId: "607410607791",
  appId: "1:607410607791:web:bb080df6399bebc166a65a"
}

// The website's whole backend (chatbot, contact form, and AI ECG
// analysis) is one combined Flask app (see the SafeBeat_Backend
// folder), deployed for free on Render.com. Replace this with your
// Render service's real URL once it's live, e.g.
// "https://safebeat-backend.onrender.com"
const BACKEND_URL = "https://safebeat-backend.onrender.com"

const menu = document.getElementById("menu")
const nav = document.getElementById("nav")
const openConsole = document.getElementById("open-console")
const closeConsole = document.getElementById("close-console")
const status = document.getElementById("connection-status")
const heartRate = document.getElementById("hr-web")
const spo2 = document.getElementById("spo2-web")
const messages = document.getElementById("messages")
const question = document.getElementById("question")
const chatForm = document.getElementById("chat-form")
const clearChat = document.getElementById("clear-chat")
const contactForm = document.getElementById("contact-form")
const formStatus = document.getElementById("form-status")

let database
let chart
let dataBuffer = Array(150).fill(0)
let lastSignal = 0
let state = "connecting"
let latestHeartRate = null
let latestSpO2 = null
let latestArrhythmiaRisk = null

function showState(next) {
  state = next
  status.className = next
  status.textContent = next === "connected" ? "Unit connected" : next === "disconnected" ? "Disconnected" : "Connecting..."
}

function getValue(value) {
  if (value === null || value === undefined) return "--"
  if (typeof value === "object") return value.status || Object.values(value)[0] || "--"
  return value
}

function toMillivolts(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  const result = ((number / 4095) * 3.3 - ((2048 / 4095) * 3.3)) * 1000
  return Math.max(-1000, Math.min(1000, result))
}

function makeChart() {
  if (chart || !window.Chart) return
  chart = new Chart(document.getElementById("liveEcg"), {
    type: "line",
    data: {
      labels: Array(150).fill(""),
      datasets: [{
        data: dataBuffer,
        borderColor: "#9e5c67",
        borderWidth: 1.6,
        pointRadius: 0,
        tension: .1,
        fill: true,
        backgroundColor: "rgba(158, 92, 103, .10)"
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { display: false },
        y: { min: -1000, max: 1000, ticks: { display: false }, grid: { color: "rgba(158, 92, 103, .10)" } }
      },
      plugins: { legend: { display: false }, tooltip: { enabled: false } }
    }
  })
}

function updateChart() {
  if (!chart) return
  chart.data.datasets[0].data = dataBuffer
  chart.update("none")
}

function addMessage(text, type) {
  const message = document.createElement("p")
  message.className = type
  message.textContent = text
  messages.appendChild(message)
  messages.scrollTop = messages.scrollHeight
  return message
}

function openMonitor() {
  document.body.classList.add("console-open")
  window.scrollTo(0, 0)
  makeChart()
  setTimeout(() => chart && chart.resize(), 100)
}

menu.addEventListener("click", () => {
  const open = nav.classList.toggle("open")
  menu.textContent = open ? "Close" : "Menu"
  menu.setAttribute("aria-expanded", open)
})

nav.querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => {
    nav.classList.remove("open")
    menu.textContent = "Menu"
    menu.setAttribute("aria-expanded", "false")
  })
})

openConsole.addEventListener("click", openMonitor)
closeConsole.addEventListener("click", () => {
  document.body.classList.remove("console-open")
  window.scrollTo(0, 0)
})

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"))
    document.querySelectorAll(".console-tab").forEach((item) => item.classList.remove("active"))
    button.classList.add("active")
    document.getElementById(button.dataset.tab).classList.add("active")
  })
})

clearChat.addEventListener("click", () => {
  messages.innerHTML = ""
  addMessage("Hello. I can answer questions about the SafeBeat project. What would you like to know?", "bot-message")
  question.focus()
})

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault()
  const text = question.value.trim()
  if (!text) return

  addMessage(text, "user-message")
  question.value = ""
  question.disabled = true
  const loading = addMessage("Thinking...", "bot-message loading-message")

  try {
    const response = await fetch(`${BACKEND_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    })
    const data = await response.json()
    loading.remove()
    addMessage(data.reply || "I could not answer that right now.", "bot-message")
  } catch (error) {
    loading.remove()
    addMessage("The assistant is unavailable. Run ai.py and check the Groq key in .env.", "bot-message")
  }

  question.disabled = false
  question.focus()
})

try {
  database = getDatabase(initializeApp(config))

  onValue(ref(database, "ECG/status"), (snapshot) => {
    const value = String(snapshot.val() || "").toLowerCase()
    if (value.includes("connected")) {
      lastSignal = Date.now()
      showState("connected")
    }
  }, () => showState("disconnected"))

  onValue(query(ref(database, "ECG/data"), limitToLast(150)), (snapshot) => {
    if (!snapshot.exists()) return
    const data = snapshot.val()
    const values = Object.keys(data).sort((a, b) => Number(a) - Number(b)).map((key) => toMillivolts(data[key]))
    dataBuffer = Array(Math.max(0, 150 - values.length)).fill(0).concat(values.slice(-150))
    lastSignal = Date.now()
    showState("connected")
    updateChart()
  }, () => showState("disconnected"))

  onValue(ref(database, "HeartRate"), (snapshot) => {
    const value = getValue(snapshot.val())
    heartRate.textContent = value
    latestHeartRate = Number(value)
    if (!Number.isFinite(latestHeartRate)) latestHeartRate = null
    runAlertSystem()
  }, () => {
    heartRate.textContent = "--"
    latestHeartRate = null
    runAlertSystem()
  })

  onValue(ref(database, "SpO2"), (snapshot) => {
    const value = getValue(snapshot.val())
    spo2.textContent = value
    latestSpO2 = Number(value)
    if (!Number.isFinite(latestSpO2)) latestSpO2 = null
    runAlertSystem()
  }, () => {
    spo2.textContent = "--"
    latestSpO2 = null
    runAlertSystem()
  })
} catch (error) {
  showState("disconnected")
}

contactForm.addEventListener("submit", async (event) => {
  event.preventDefault()
  const button = contactForm.querySelector("button")
  formStatus.textContent = "Sending..."
  button.disabled = true

  try {
    const response = await fetch(`${BACKEND_URL}/save_user`, {
      method: "POST",
      body: new FormData(contactForm)
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.message)
    contactForm.reset()
    formStatus.textContent = data.message
  } catch (error) {
    formStatus.textContent = error.message || "The message could not be saved."
  }

  button.disabled = false
})

setInterval(() => {
  if (state === "connected" && Date.now() - lastSignal > 5000) showState("disconnected")
}, 1000)

const runAnalysisButton = document.getElementById("run-analysis")
const analysisStatus = document.getElementById("analysis-status")
const analysisResults = document.getElementById("analysis-results")
const analysisRiskBadge = document.getElementById("analysis-risk-badge")
const analysisBeatCount = document.getElementById("analysis-beat-count")
const analysisLabelCounts = document.getElementById("analysis-label-counts")

// Reuses the same combined backend URL declared above for Firebase/chat.
const ANALYSIS_API_URL = BACKEND_URL

if (runAnalysisButton) {
  runAnalysisButton.addEventListener("click", async () => {
    analysisStatus.textContent = "Analyzing latest signal..."
    analysisResults.hidden = true
    runAnalysisButton.disabled = true

    try {
      const response = await fetch(`${ANALYSIS_API_URL}/analyze_latest?window_seconds=10`)
      const data = await response.json()

      if (!response.ok) {
        analysisStatus.textContent = data.error || "The analysis service could not process this request."
        return
      }

      if (data.beats_analyzed === 0) {
        analysisStatus.textContent = data.message || "No heartbeats detected."
        return
      }

      analysisStatus.textContent = ""
      analysisResults.hidden = false
      analysisRiskBadge.textContent = data.overall_risk
      analysisRiskBadge.className = `risk-badge risk-${data.overall_risk}`
      analysisBeatCount.textContent = `${data.beats_analyzed} beats analyzed`

      analysisLabelCounts.innerHTML = ""
      Object.entries(data.label_counts).forEach(([label, count]) => {
        const row = document.createElement("div")
        row.className = "label-count-row"
        row.innerHTML = `<span>${label}</span><strong>${count}</strong>`
        analysisLabelCounts.appendChild(row)
      })
    } catch (error) {
      analysisStatus.textContent =
        "Could not reach the analysis service. Make sure ecg_analysis_api.py is running on port 5001."
    } finally {
      runAnalysisButton.disabled = false
    }
  })
}

// ---------------------------------------------------------------------
// Continuous auto-analysis for the Monitor tab (no button, runs on its
// own). Every few seconds it quietly asks the analysis API "what does
// the last few seconds of signal look like?" and updates a small badge
// under the live ECG chart. This is what should catch an emergency
// pattern automatically while an athlete is training, without anyone
// needing to click anything.
// ---------------------------------------------------------------------
const autoBadge = document.getElementById("auto-analysis-badge")
const autoDetail = document.getElementById("auto-analysis-detail")
const AUTO_ANALYSIS_INTERVAL_MS = 8000 // check every 8 seconds

async function runAutoAnalysis() {
  if (!autoBadge) return // this element only exists on the Monitor tab

  try {
    const response = await fetch(`${ANALYSIS_API_URL}/analyze_latest?window_seconds=10`)
    const data = await response.json()

    if (!response.ok) {
      autoBadge.textContent = "Analysis unavailable"
      autoBadge.className = "risk-badge"
      autoDetail.textContent = data.error || ""
      latestArrhythmiaRisk = null
      runAlertSystem()
      return
    }

    if (data.beats_analyzed === 0) {
      autoBadge.textContent = "No signal detected"
      autoBadge.className = "risk-badge"
      autoDetail.textContent = data.message || ""
      latestArrhythmiaRisk = null
      runAlertSystem()
      return
    }

    autoBadge.textContent =
      data.overall_risk === "alert" ? "Emergency pattern detected" :
      data.overall_risk === "monitor" ? "Irregularity detected" :
      "Rhythm normal"
    autoBadge.className = `risk-badge risk-${data.overall_risk}`
    autoDetail.textContent = `${data.beats_analyzed} beats analyzed in the last 10 seconds`
    latestArrhythmiaRisk = data.overall_risk
    runAlertSystem()
  } catch (error) {
    autoBadge.textContent = "Analysis service offline"
    autoBadge.className = "risk-badge"
    autoDetail.textContent = "Start ecg_analysis_api.py to enable continuous analysis."
    latestArrhythmiaRisk = null
    runAlertSystem()
  }
}

if (autoBadge) {
  runAutoAnalysis()
  setInterval(runAutoAnalysis, AUTO_ANALYSIS_INTERVAL_MS)
}

// ---------------------------------------------------------------------
// Full alert system (below the AI panel on the AI analysis tab).
// Mirrors fig6 / the Results paragraph: it checks the same three
// early-warning signs in sequence — arrhythmia pattern (from the AI
// model), then heart rate (brady/tachycardia), then SpO2 — and combines
// them into one plain verdict: "Athlete safe" unless one of the three
// checks crosses its threshold, in which case it raises an alert.
// ---------------------------------------------------------------------
const HR_LOW_BPM = 40      // below this = bradycardia concern
const HR_HIGH_BPM = 180    // above this = tachycardia concern
const SPO2_LOW_PERCENT = 90 // below this = low oxygen concern

const stepArrhythmiaBadge = document.getElementById("step-arrhythmia-badge")
const stepHrBadge = document.getElementById("step-hr-badge")
const stepSpo2Badge = document.getElementById("step-spo2-badge")
const alertVerdict = document.getElementById("alert-verdict")
const alertVerdictText = document.getElementById("alert-verdict-text")

function setStepBadge(el, tier, label) {
  if (!el) return
  el.textContent = label
  el.className = `step-badge risk-badge risk-${tier}`
}

function runAlertSystem() {
  if (!alertVerdict) return // only present on the AI analysis tab

  // Step 1 — arrhythmia, from the live AI heartbeat classification.
  let arrhythmiaTier = "normal"
  if (latestArrhythmiaRisk === null) {
    setStepBadge(stepArrhythmiaBadge, "monitor", "No data")
  } else {
    arrhythmiaTier = latestArrhythmiaRisk
    setStepBadge(
      stepArrhythmiaBadge,
      arrhythmiaTier,
      arrhythmiaTier === "alert" ? "Irregular" : arrhythmiaTier === "monitor" ? "Watch" : "Normal"
    )
  }

  // Step 2 — heart rate, checked next, same brady/tachy zones as fig13.
  let hrTier = "normal"
  if (latestHeartRate === null) {
    setStepBadge(stepHrBadge, "monitor", "No data")
  } else if (latestHeartRate < HR_LOW_BPM || latestHeartRate > HR_HIGH_BPM) {
    hrTier = "alert"
    setStepBadge(stepHrBadge, "alert", `${latestHeartRate} BPM`)
  } else {
    setStepBadge(stepHrBadge, "normal", `${latestHeartRate} BPM`)
  }

  // Step 3 — SpO2, checked last, same threshold as fig14.
  let spo2Tier = "normal"
  if (latestSpO2 === null) {
    setStepBadge(stepSpo2Badge, "monitor", "No data")
  } else if (latestSpO2 < SPO2_LOW_PERCENT) {
    spo2Tier = "alert"
    setStepBadge(stepSpo2Badge, "alert", `${latestSpO2}%`)
  } else {
    setStepBadge(stepSpo2Badge, "normal", `${latestSpO2}%`)
  }

  // Combine the three checks into one verdict, same logic as the
  // Results paragraph: if any of the three tracked warning signs
  // crosses its safe range, raise an alert; otherwise the athlete
  // is reported safe.
  const tiers = [arrhythmiaTier, hrTier, spo2Tier]
  let verdict = "safe"
  let message = "Athlete safe — all vitals within normal range."

  if (tiers.includes("alert")) {
    verdict = "alert"
    message = "Alert — abnormal reading detected, notify athlete & medical team."
  } else if (tiers.includes("monitor")) {
    verdict = "monitor"
    message = "Monitoring — a reading needs a closer look."
  }

  alertVerdict.className = `alert-verdict ${verdict}`
  alertVerdictText.textContent = message
}


// ---------------------------------------------------------------------
// Personalized diagnostic tab. Calculates each athlete's theoretical
// max heart rate (HRmax = 220 - age, same formula used on the poster's
// Personalized section), tracks the highest live BPM seen since the
// tab was opened, and compares it against the same %HRmax zone table
// from fig12 to show which training zone the athlete is currently in.
// ---------------------------------------------------------------------
const diagnosticAgeInput = document.getElementById("diagnostic-age")
const diagnosticHrmax = document.getElementById("diagnostic-hrmax")
const diagnosticLiveBpm = document.getElementById("diagnostic-live-bpm")
const diagnosticMaxBpm = document.getElementById("diagnostic-max-bpm")
const diagnosticPercent = document.getElementById("diagnostic-percent")
const diagnosticZoneBadge = document.getElementById("diagnostic-zone-badge")
const diagnosticZoneTitle = document.getElementById("diagnostic-zone-title")
const diagnosticZoneDesc = document.getElementById("diagnostic-zone-desc")
const diagnosticZoneRows = document.querySelectorAll(".diagnostic-zone-row")

let maxBpmSeen = 0

// Same 5 zones as fig12 on the poster, in the same order.
const HR_ZONES = [
  { min: 50, max: 60, label: "Very light", tier: "normal", desc: "Recovery and warm-up." },
  { min: 60, max: 70, label: "Light", tier: "normal", desc: "Endurance training." },
  { min: 70, max: 80, label: "Moderate", tier: "normal", desc: "Endurance training." },
  { min: 80, max: 90, label: "Hard", tier: "monitor", desc: "Increased performance capacity." },
  { min: 90, max: 100, label: "Maximum effort", tier: "alert", desc: "High-intensity training and sprints — monitor closely." },
]

function updateDiagnostics() {
  if (!diagnosticHrmax) return // only present on the Diagnostic tab

  if (latestHeartRate !== null && latestHeartRate > maxBpmSeen) {
    maxBpmSeen = latestHeartRate
  }

  diagnosticLiveBpm.textContent = latestHeartRate === null ? "--" : latestHeartRate
  diagnosticMaxBpm.textContent = maxBpmSeen === 0 ? "--" : maxBpmSeen

  const age = Number(diagnosticAgeInput.value)
  diagnosticZoneRows.forEach((row) => row.classList.remove("active"))

  if (!age || age <= 0) {
    diagnosticHrmax.textContent = "--"
    diagnosticPercent.textContent = "--"
    diagnosticZoneBadge.textContent = "--"
    diagnosticZoneBadge.className = "step-badge risk-badge"
    diagnosticZoneTitle.textContent = "Enter age to see the athlete's current training zone"
    diagnosticZoneDesc.textContent = "Compares the live heart rate against the theoretical maximum, using the same zone table as fig12."
    return
  }

  const hrmax = 220 - age
  diagnosticHrmax.textContent = `${hrmax} BPM`

  if (latestHeartRate === null) {
    diagnosticPercent.textContent = "--"
    diagnosticZoneBadge.textContent = "No data"
    diagnosticZoneBadge.className = "step-badge risk-badge risk-monitor"
    diagnosticZoneTitle.textContent = "Waiting for a live heart rate reading"
    diagnosticZoneDesc.textContent = "Once HeartRate starts streaming from Firebase, the athlete's current zone will show here."
    return
  }

  const percent = Math.round((latestHeartRate / hrmax) * 100)
  diagnosticPercent.textContent = `${percent}%`

  let zone = null
  if (percent < 50) {
    zone = { label: "Below training range", tier: "normal", desc: "Resting or very light activity — below the tracked training zones." }
  } else if (percent > 100) {
    zone = { label: "Above HRmax", tier: "alert", desc: "Exceeds the estimated maximum — stop activity and assess immediately." }
  } else {
    zone = HR_ZONES.find((z) => percent >= z.min && percent <= z.max) || HR_ZONES[HR_ZONES.length - 1]
    const rowIndex = HR_ZONES.indexOf(zone)
    if (rowIndex >= 0 && diagnosticZoneRows[rowIndex]) diagnosticZoneRows[rowIndex].classList.add("active")
  }

  diagnosticZoneBadge.textContent = zone.label
  diagnosticZoneBadge.className = `step-badge risk-badge risk-${zone.tier}`
  diagnosticZoneTitle.textContent = `${zone.label} — ${percent}% of HRmax`
  diagnosticZoneDesc.textContent = zone.desc
}

if (diagnosticAgeInput) {
  diagnosticAgeInput.addEventListener("input", updateDiagnostics)
  updateDiagnostics()
  setInterval(updateDiagnostics, 2000)
}
