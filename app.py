"""
====================================================================
 SafeBeat — Combined Backend (chatbot + ECG AI analysis)
====================================================================
This is the ONE backend server for the SafeBeat website, merging what
used to be two separate local scripts (ai.py + ecg_analysis_api.py)
into a single Flask app that is easy to deploy for free on Hugging
Face Spaces.

ENDPOINTS:
  POST /chat            - SafeBeat assistant chatbot (Groq LLM)
  POST /save_user       - saves a contact-form submission
  POST /analyze_signal  - classifies a raw ECG signal list you send it
  GET  /analyze_latest  - fetches the latest ECG window from Firebase
                           and classifies it with the trained model

WHERE SECRETS COME FROM (set these as "Secrets" in the Hugging Face
Space settings — never commit them to a public repo):
  GROQ_API_KEY        - your Groq API key, for the chatbot
  FIREBASE_KEY_JSON   - the FULL text content of your Firebase service
                         account JSON key file, pasted as one secret
  FIREBASE_DB_URL     - your Firebase Realtime Database URL
                         (e.g. https://genius-final-default-rtdb.europe-west1.firebasedatabase.app/)
====================================================================
"""

import json
import os

import numpy as np
from flask import Flask, jsonify, request
from flask_cors import CORS

from ecg_preprocessing import extract_beat_windows

app = Flask(__name__)
CORS(app)  # allows the Vercel-hosted frontend (a different domain) to call this API

# --------------------------------------------------------------
# Chatbot setup
# --------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
_groq_client = None


def get_groq_client():
    """Builds the Groq client once and reuses it. Wrapped in try/except so
    a library-version mismatch (e.g. an old groq/httpx combo) can never
    crash the whole request with an unhandled 500 — it just falls back
    to reporting the assistant as unavailable, same as a missing key."""
    global _groq_client
    if _groq_client is None and GROQ_API_KEY:
        try:
            from groq import Groq
            _groq_client = Groq(api_key=GROQ_API_KEY)
        except Exception as e:
            print(f"Could not construct Groq client: {e}")
            return None
    return _groq_client


SYSTEM_PROMPT = (
    "You are the SafeBeat project assistant. SafeBeat is a student-built wearable "
    "cardiovascular monitoring system for athletes. It uses embedded sensors and an "
    "ESP32 unit to track ECG activity, heart-rate patterns and blood-oxygen levels "
    "during physical activity. Data can be viewed through a mobile application and "
    "web dashboard. Explain the project clearly, warmly and briefly. Do not claim "
    "that SafeBeat can diagnose, prevent, predict or treat a heart attack. Do not "
    "diagnose users. For chest pain, fainting, severe trouble breathing or a "
    "possible emergency, tell the user to contact local emergency services immediately."
)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"reply": "Please write a question first."}), 400

    client = get_groq_client()
    if not client:
        return jsonify({
            "reply": "The assistant is temporarily unavailable. Please try again later."
        }), 503

    try:
        result = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            max_tokens=300,
        )
        return jsonify({"reply": result.choices[0].message.content})
    except Exception:
        return jsonify({"reply": "The assistant could not respond right now. Please try again shortly."}), 500


# --------------------------------------------------------------
# Contact form
# --------------------------------------------------------------
# Every submission is emailed straight to the SafeBeat team via Resend
# (a free transactional email API — https://resend.com, 100 emails/day
# free, no credit card required, well within this project's volume).
# It's also appended to a local backup log file in case the email send
# ever fails, though Render's free-tier disk isn't guaranteed to persist
# across restarts, so the email is the real source of truth.
CONTACT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contact_messages.jsonl")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
# Where contact-form submissions get emailed to. Defaults to the two
# co-founder addresses already shown on the site; override with the
# CONTACT_RECIPIENT_EMAIL env var if you ever want to change this
# without editing code.
CONTACT_RECIPIENT_EMAILS = os.environ.get(
    "CONTACT_RECIPIENT_EMAIL",
    "amine6ouragini@gmail.com,youssefbrahim445@gmail.com"
).split(",")


def send_contact_email(name, email, subject, message):
    """Sends the contact-form submission as an email via Resend. Returns
    True on success, False on any failure (never raises) so a broken
    email integration can never take down the contact form itself."""
    if not RESEND_API_KEY:
        print("RESEND_API_KEY not set — skipping email send, saved to local log only.")
        return False

    try:
        import requests
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                # Resend's free tier requires the "from" address to be on
                # their shared, pre-verified onboarding domain unless you
                # verify your own domain with them.
                "from": "SafeBeat Website <onboarding@resend.dev>",
                "to": CONTACT_RECIPIENT_EMAILS,
                "replyTo": email,
                "subject": f"[SafeBeat contact form] {subject or 'New message'}",
                "text": f"From: {name} <{email}>\n\n{message}",
            },
            timeout=10,
        )
        if response.status_code >= 300:
            print(f"Resend email failed ({response.status_code}): {response.text}")
            return False
        return True
    except Exception as e:
        print(f"Could not send contact email: {e}")
        return False


@app.route("/save_user", methods=["POST"])
def save_user():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    subject = request.form.get("subject", "").strip()
    message = request.form.get("message", "").strip()

    if not name or not email or not message:
        return jsonify({"message": "Please complete your name, email and message."}), 400

    if "@" not in email:
        return jsonify({"message": "Please enter a valid email address."}), 400

    try:
        with open(CONTACT_LOG_PATH, "a") as f:
            f.write(json.dumps({"name": name, "email": email, "subject": subject, "message": message}) + "\n")
    except Exception:
        pass  # don't fail the request just because logging to disk failed

    send_contact_email(name, email, subject, message)

    return jsonify({"message": "Thank you. Your message was saved."})


# --------------------------------------------------------------
# ECG AI analysis
# --------------------------------------------------------------
CLASS_NAMES = ["Normal (N)", "Supraventricular (S)", "Ventricular (V)", "Fusion (F)", "Unknown/Paced (Q)"]

RISK_TIER = {
    "Normal (N)": "normal",
    "Supraventricular (S)": "monitor",
    "Ventricular (V)": "alert",
    "Fusion (F)": "monitor",
    "Unknown/Paced (Q)": "monitor",
}

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "safebeat_ecg_model.tflite")

_interpreter = None
_input_details = None
_output_details = None


def get_interpreter():
    """Loads the lightweight TFLite model once and reuses it. TFLite is
    used instead of full TensorFlow/Keras here specifically so this app
    fits comfortably in the 512MB RAM of a free Render web service —
    the two run the exact same trained network and give matching
    predictions (verified to ~1e-6 precision), TFLite just needs far
    less memory and a much smaller install than full TensorFlow."""
    global _interpreter, _input_details, _output_details
    if _interpreter is None:
        from ai_edge_litert.interpreter import Interpreter
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Could not find {MODEL_PATH}.")
        _interpreter = Interpreter(model_path=MODEL_PATH)
        _interpreter.allocate_tensors()
        _input_details = _interpreter.get_input_details()
        _output_details = _interpreter.get_output_details()
    return _interpreter, _input_details, _output_details


def predict_batch(beats):
    """Runs the TFLite model one beat at a time (TFLite's default
    interpreter doesn't batch the way Keras does) and stacks the
    results back into one array, same shape as the old model.predict()."""
    interpreter, input_details, output_details = get_interpreter()
    outputs = []
    for beat in beats:
        single = beat.reshape(1, *input_details[0]["shape"][1:]).astype(input_details[0]["dtype"])
        interpreter.set_tensor(input_details[0]["index"], single)
        interpreter.invoke()
        outputs.append(interpreter.get_tensor(output_details[0]["index"])[0])
    return np.array(outputs)


def classify_signal(signal, sample_rate_hz):
    beats, peak_indices = extract_beat_windows(signal, source_rate_hz=sample_rate_hz)

    if beats.shape[0] == 0:
        return {
            "beats_analyzed": 0,
            "message": "No clear heartbeats detected in this signal window. "
                       "Check electrode contact or provide a longer sample.",
            "predictions": [],
        }

    probs = predict_batch(beats)
    pred_indices = np.argmax(probs, axis=1)

    predictions = []
    for i, (idx, prob_row) in enumerate(zip(pred_indices, probs)):
        label = CLASS_NAMES[idx]
        predictions.append({
            "beat_index": i,
            "label": label,
            "risk_tier": RISK_TIER[label],
            "confidence": round(float(prob_row[idx]) * 100, 1),
        })

    tiers_present = [p["risk_tier"] for p in predictions]
    total = len(tiers_present)
    alert_fraction = tiers_present.count("alert") / total
    monitor_fraction = tiers_present.count("monitor") / total

    if alert_fraction >= 0.3:
        overall = "alert"
    elif monitor_fraction >= 0.3 or alert_fraction > 0:
        overall = "monitor"
    else:
        overall = "normal"

    label_counts = {}
    for p in predictions:
        label_counts[p["label"]] = label_counts.get(p["label"], 0) + 1

    return {
        "beats_analyzed": len(predictions),
        "overall_risk": overall,
        "label_counts": label_counts,
        "predictions": predictions,
    }


@app.route("/analyze_signal", methods=["POST"])
def analyze_signal():
    data = request.get_json(silent=True) or {}
    signal = data.get("signal")
    sample_rate_hz = data.get("sample_rate_hz", 50)

    if not signal or not isinstance(signal, list) or len(signal) < sample_rate_hz:
        return jsonify({"error": "Provide at least 1 second of signal as a list under 'signal'."}), 400

    try:
        result = classify_signal(signal, sample_rate_hz)
        return jsonify(result)
    except Exception as e:
        print(f"analyze_signal error: {e}")  # full detail stays in the server logs only
        return jsonify({"error": "A problem occurred while processing this request. Please try again shortly."}), 500


_firebase_initialized = False


def ensure_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return

    import firebase_admin
    from firebase_admin import credentials

    key_json = os.environ.get("FIREBASE_KEY_JSON")
    db_url = os.environ.get("FIREBASE_DB_URL")

    if not key_json or not db_url:
        raise RuntimeError("Firebase is not configured on this server yet.")

    if not firebase_admin._apps:
        cred = credentials.Certificate(json.loads(key_json))
        firebase_admin.initialize_app(cred, {"databaseURL": db_url})

    _firebase_initialized = True


@app.route("/analyze_latest", methods=["GET"])
def analyze_latest():
    window_seconds = float(request.args.get("window_seconds", 10))

    try:
        ensure_firebase()
        from firebase_admin import db as fb_db

        ref = fb_db.reference("ECG/data")
        sample_rate_hz = 50  # matches SAMPLE_INTERVAL_MS = 20 in the ESP32 Firebase sketch
        n_samples = int(window_seconds * sample_rate_hz)
        snapshot = ref.order_by_key().limit_to_last(n_samples).get()

        if not snapshot:
            return jsonify({"error": "No recent ECG data found in Firebase."}), 404

        if isinstance(snapshot, list):
            signal = [v for v in snapshot if v is not None]
        else:
            keys_sorted = sorted(snapshot.keys(), key=lambda k: int(k))
            signal = [snapshot[k] for k in keys_sorted]

        if not signal:
            return jsonify({"error": "No recent ECG data found in Firebase."}), 404

    except Exception as e:
        print(f"analyze_latest Firebase error: {e}")  # full detail stays in the server logs only
        return jsonify({"error": "A problem occurred while fetching live data. Please try again shortly."}), 500

    try:
        result = classify_signal(signal, sample_rate_hz)
        return jsonify(result)
    except Exception as e:
        print(f"analyze_latest classify_signal error: {e}")  # full detail stays in the server logs only
        return jsonify({"error": "A problem occurred while processing this request. Please try again shortly."}), 500


@app.route("/")
def health():
    return jsonify({"status": "SafeBeat backend is running."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))  # 7860 is the default Hugging Face Spaces port
    app.run(host="0.0.0.0", port=port)
