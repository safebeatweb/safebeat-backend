---
title: SafeBeat Backend
---

# SafeBeat Backend

Combined Flask backend for the SafeBeat website:

- `POST /chat` — SafeBeat assistant chatbot (Groq LLM)
- `POST /save_user` — saves a contact-form submission
- `POST /analyze_signal` — classifies a raw ECG signal you send it
- `GET /analyze_latest?window_seconds=10` — fetches the latest ECG window from
  Firebase and classifies it with the trained 1D-CNN model (running as a
  lightweight TFLite model, converted from the original Keras/.h5 model —
  same predictions, far less memory, so it fits a free hosting tier)
- `GET /` — health check

## Required environment variables (set as secrets in your host's dashboard)

| Variable name        | Value                                                                 |
|-----------------------|------------------------------------------------------------------------|
| `GROQ_API_KEY`        | Your Groq API key (for the chatbot)                                    |
| `FIREBASE_KEY_JSON`   | The **full text** of your Firebase service-account JSON key file       |
| `FIREBASE_DB_URL`     | Your Firebase Realtime Database URL, e.g. `https://genius-final-default-rtdb.europe-west1.firebasedatabase.app/` |

Never commit these values into any file in this repo — always set them as
environment variables/secrets in your hosting platform's dashboard instead.

## Running locally

```
pip install -r requirements.txt
python3 app.py
```

See `DEPLOYMENT.md` for how to host this for free on Render.com.
