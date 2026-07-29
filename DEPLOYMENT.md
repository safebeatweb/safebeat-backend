# SafeBeat — Free Hosting Guide

This sets up:
- **Frontend** (`SafeBeat_Website/`) → hosted free on **Vercel**
- **Backend** (`SafeBeat_Backend/`) → hosted free on **Render.com**, a plain
  Python web service (no Docker, no credit card required)

You said you already have a GitHub account — everything below builds on that.

---

## Part 1 — Push your code to GitHub

You need **two GitHub repos** (one per project, since they deploy to two
different platforms):

1. Go to https://github.com/new and create a repo called `safebeat-website`.
2. Go to https://github.com/new again and create a second repo called
   `safebeat-backend`.
3. On your own computer, inside the `SafeBeat_Website` folder:
   ```
   git init
   git add .
   git commit -m "Initial website"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/safebeat-website.git
   git push -u origin main
   ```
4. Do the same inside the `SafeBeat_Backend` folder, pushing to
   `safebeat-backend`.

**Important — before pushing SafeBeat_Backend:** make sure `firebase_key.json`
and `.env` are NOT in that folder (the included `.gitignore` already blocks
them, but double-check). Those secrets go into Render's environment variables
instead — never into GitHub.

---

## Part 2 — Deploy the backend to Render.com (free, no card, no Docker)

1. Create a free account at https://render.com — you can sign up with GitHub.
2. Click **New → Web Service**.
3. Connect your `safebeat-backend` GitHub repo.
4. Fill in:
   - **Name**: `safebeat-backend` (this becomes part of your URL)
   - **Region**: whichever is closest to you
   - **Branch**: `main`
   - **Runtime**: **Python 3**
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 app:app`
   - **Instance Type**: **Free**
5. Scroll to **Environment Variables** and add:
   | Key | Value |
   |---|---|
   | `GROQ_API_KEY` | your Groq API key |
   | `FIREBASE_KEY_JSON` | paste the **entire contents** of your Firebase service-account JSON file (Firebase console → Project settings → Service accounts → Generate new private key) |
   | `FIREBASE_DB_URL` | `https://genius-final-default-rtdb.europe-west1.firebasedatabase.app/` |
6. Click **Create Web Service**. Render will install dependencies and start
   the app — the first build can take a few minutes.
7. Once live, your backend URL will look like:
   ```
   https://safebeat-backend.onrender.com
   ```
8. Test it by opening that URL in a browser — you should see:
   ```
   {"status": "SafeBeat backend is running."}
   ```

**Note on free-tier behavior:** Render's free web services spin down after
~15 minutes with no traffic, and the next request "wakes" it back up, taking
roughly 30-50 seconds. This is a normal free-tier tradeoff, not a bug — if a
judge's first click during a demo is slow, that's why. Opening the site a
minute before presenting avoids this.

---

## Part 3 — Point the website at your live backend

1. Open `SafeBeat_Website/script.js`.
2. Find this line near the top:
   ```js
   const BACKEND_URL = "https://YOUR-USERNAME-safebeat-backend.hf.space"
   ```
3. Replace it with your **actual** Render URL from Part 2, step 7, e.g.:
   ```js
   const BACKEND_URL = "https://safebeat-backend.onrender.com"
   ```
4. Commit and push this change to your `safebeat-website` GitHub repo.

---

## Part 4 — Deploy the frontend to Vercel (free)

1. Create a free account at https://vercel.com/signup — sign up with your
   GitHub account (this keeps everything in your own GitHub repos; Vercel
   never takes ownership of your files, it just builds/deploys from them).
2. Click **Add New → Project**.
3. Import your `safebeat-website` GitHub repo.
4. Framework preset: choose **Other** (this is a plain static site, no build
   step needed).
5. Leave Build Command and Output Directory blank/default.
6. Click **Deploy**.
7. After a minute, Vercel gives you a live URL like
   `https://safebeat-website.vercel.app`.

From now on, every time you `git push` to `safebeat-website`, Vercel
automatically redeploys the site — no manual re-upload needed.

---

## Quick recap of the URLs you'll end up with

| Piece | Hosted on | Example URL |
|---|---|---|
| Website | Vercel | `https://safebeat-website.vercel.app` |
| Backend (chat + AI + Firebase) | Render.com | `https://safebeat-backend.onrender.com` |

Both are completely free, no credit card needed for either.
