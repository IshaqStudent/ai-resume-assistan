# ai-resume-assistan# 📄 Resume ATS Score & Improvement Checker

Upload a resume (PDF, DOCX or TXT), optionally paste a target job description, and get:

- An overall **ATS score (0–100)** with a five-category breakdown
- **Strengths** and **prioritised improvements** (High / Medium / Low) with example rewrites
- **Missing keywords** to consider
- A downloadable text report

Built with [Streamlit](https://streamlit.io) and the Google Gemini API (Flash model).

## How the score works

Gemini rates five categories from 0–100. The app then computes the overall score with fixed weights:

| Category | Weight |
|---|---|
| Keywords & Relevance | 25% |
| Work Experience Impact | 25% |
| Formatting & Parsability | 20% |
| Structure & Sections | 15% |
| Clarity & Language | 15% |

> This is an AI-based estimate, not the output of a real commercial ATS. Treat it as guidance.

## Run locally

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Get a free API key from [Google AI Studio](https://aistudio.google.com/apikey), then either:

```bash
export GEMINI_API_KEY="your-key"     # Windows PowerShell: $env:GEMINI_API_KEY="your-key"
streamlit run app.py
```

or create `.streamlit/secrets.toml` (never commit this file):

```toml
GEMINI_API_KEY = "your-key"
# GEMINI_MODEL = "gemini-3.7-flash"   # optional: change the model
```

You can also just paste the key into the sidebar when the app is running.

## Configuration

| Setting | Where | Default |
|---|---|---|
| `GEMINI_API_KEY` | secrets or environment variable | none (sidebar input if missing) |
| `GEMINI_MODEL` | secrets or environment variable | `gemini-3.7-flash` |

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (see below).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **Create app** → choose your repo, branch `main`, main file `app.py`.
4. Open **Advanced settings → Secrets** and paste:
   ```toml
   GEMINI_API_KEY = "your-key"
   ```
5. Click **Deploy**. Every `git push` to `main` redeploys automatically.

## Push to GitHub

```bash
echo ".streamlit/secrets.toml
.venv/
__pycache__/
.env" > .gitignore

git init
git add app.py requirements.txt README.md .gitignore
git commit -m "Initial commit: resume ATS checker"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

Create the empty repo on github.com first (no README/license, to avoid conflicts).

## Privacy

Resume text is sent to Google's Gemini API for analysis. The app itself does not store uploaded files.

## Limitations

- Scanned/image-only PDFs have no extractable text and are rejected (an ATS couldn't read them either).
- Very long resumes are truncated to ~20,000 characters.
