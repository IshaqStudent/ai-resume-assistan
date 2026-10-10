"""Resume ATS Score & Improvement Checker.

Upload a resume (PDF, DOCX or TXT), optionally paste a job description, and get:
  * an overall ATS score (0-100) with a category breakdown
  * strengths, prioritised improvements and missing keywords

UI: Streamlit  |  AI: Google Gemini (Flash model)
"""

import io
import json
import os
import re

import streamlit as st
from docx import Document
from pypdf import PdfReader

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DEFAULT_MODEL = "gemini-3.7-flash"  # override with GEMINI_MODEL in secrets/env
MAX_FILE_MB = 5
MAX_RESUME_CHARS = 20_000
MAX_JD_CHARS = 8_000
MIN_RESUME_CHARS = 150

# Category -> weight (weights sum to 1.0). The overall score is computed here
# from the AI's category scores so the maths is transparent and consistent.
CATEGORY_WEIGHTS = {
    "Formatting & Parsability": 0.20,
    "Keywords & Relevance": 0.25,
    "Work Experience Impact": 0.25,
    "Structure & Sections": 0.15,
    "Clarity & Language": 0.15,
}

PROMPT_TEMPLATE = """You are an expert ATS (Applicant Tracking System) analyst and professional resume reviewer.

Evaluate the resume text below. {jd_instruction}

Score each category from 0 to 100 using these exact category names:
{categories}

Scoring guidance:
- Formatting & Parsability: clean text, standard headings, consistent dates, no signs of tables/columns/graphics breaking extraction.
- Keywords & Relevance: relevant hard skills, tools, and role keywords{jd_scoring}.
- Work Experience Impact: action verbs, quantified achievements, results over duties.
- Structure & Sections: contact info, summary, experience, education, skills, sensible order and length.
- Clarity & Language: concise, specific, free of typos, grammar issues, clichés and filler.
Be honest and calibrated: an average resume scores 55-70; reserve 85+ for excellent ones.

Return ONLY valid JSON (no markdown fences, no commentary) with exactly this shape:
{{
  "category_scores": {{ "<category name>": <integer 0-100>, ... }},
  "summary": "<2-3 sentence overall assessment>",
  "strengths": ["<short point>", ...],
  "improvements": [
    {{"priority": "High|Medium|Low", "issue": "<what is wrong>", "fix": "<specific action>", "example": "<optional rewritten example or empty string>"}}
  ],
  "missing_keywords": ["<keyword>", ...]
}}
Give 3-5 strengths, 5-8 improvements ordered by priority, and up to 15 missing keywords.

{jd_block}RESUME TEXT:
\"\"\"
{resume}
\"\"\"
"""


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #
def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from a PDF, DOCX or TXT file."""
    name = filename.lower()
    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError("This PDF is password-protected.")
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = "\n".join(pages)
    elif name.endswith(".docx"):
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:  # resumes often keep content in tables
            for row in table.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        text = "\n".join(parts)
    elif name.endswith(".txt"):
        text = data.decode("utf-8", errors="ignore")
    else:
        raise ValueError("Unsupported file type. Please upload a PDF, DOCX or TXT file.")
    return clean_text(text)


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Gemini helpers
# --------------------------------------------------------------------------- #
def build_prompt(resume: str, job_description: str = "") -> str:
    jd = job_description.strip()
    if jd:
        jd_instruction = "A target job description is provided; judge relevance against it."
        jd_scoring = ", matched against the job description"
        jd_block = f'JOB DESCRIPTION:\n"""\n{jd[:MAX_JD_CHARS]}\n"""\n\n'
    else:
        jd_instruction = "No job description is provided; judge against general best practice for the role the resume targets."
        jd_scoring = " typical for the candidate's target role"
        jd_block = ""
    categories = "\n".join(f"- {c}" for c in CATEGORY_WEIGHTS)
    return PROMPT_TEMPLATE.format(
        jd_instruction=jd_instruction,
        categories=categories,
        jd_scoring=jd_scoring,
        jd_block=jd_block,
        resume=resume[:MAX_RESUME_CHARS],
    )


def parse_json_response(raw: str) -> dict:
    """Parse model output into a dict, tolerating code fences / stray text."""
    if not raw or not raw.strip():
        raise ValueError("The AI returned an empty response.")
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError("Could not parse the AI response as JSON.")


def _clamp_score(value) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def normalize_result(data: dict) -> dict:
    """Validate/clean the model output and compute the weighted overall score."""
    if not isinstance(data, dict):
        raise ValueError("Unexpected AI response format.")

    raw_scores = data.get("category_scores") or {}
    lowered = {str(k).strip().lower(): v for k, v in raw_scores.items()}
    category_scores = {c: _clamp_score(lowered.get(c.lower(), 0)) for c in CATEGORY_WEIGHTS}
    overall = _clamp_score(sum(category_scores[c] * w for c, w in CATEGORY_WEIGHTS.items()))

    improvements = []
    for item in data.get("improvements") or []:
        if not isinstance(item, dict):
            continue
        priority = str(item.get("priority", "Medium")).strip().capitalize()
        if priority not in ("High", "Medium", "Low"):
            priority = "Medium"
        improvements.append(
            {
                "priority": priority,
                "issue": str(item.get("issue", "")).strip(),
                "fix": str(item.get("fix", "")).strip(),
                "example": str(item.get("example", "") or "").strip(),
            }
        )
    order = {"High": 0, "Medium": 1, "Low": 2}
    improvements.sort(key=lambda i: order[i["priority"]])

    def as_list(key):
        val = data.get(key) or []
        return [str(v).strip() for v in val if str(v).strip()] if isinstance(val, list) else []

    return {
        "overall": overall,
        "category_scores": category_scores,
        "summary": str(data.get("summary", "")).strip(),
        "strengths": as_list("strengths"),
        "improvements": improvements,
        "missing_keywords": as_list("missing_keywords"),
    }


def get_secret(name: str, default: str = "") -> str:
    """Read from Streamlit secrets, then environment variables."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass  # no secrets.toml available (e.g. local run)
    return os.environ.get(name, default)


def analyze_resume(resume: str, job_description: str, api_key: str, model: str) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=build_prompt(resume, job_description),
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    return normalize_result(parse_json_response(response.text))


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
def score_label(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Needs work"
    return "Poor"


def render_results(result: dict) -> None:
    overall = result["overall"]
    st.divider()
    left, right = st.columns([1, 2])
    with left:
        st.metric("ATS Score", f"{overall} / 100")
        st.progress(overall / 100)
        st.caption(score_label(overall))
    with right:
        if result["summary"]:
            st.write(result["summary"])

    st.subheader("Score breakdown")
    cols = st.columns(len(result["category_scores"]))
    for col, (name, score) in zip(cols, result["category_scores"].items()):
        with col:
            st.metric(name, score)
            st.progress(score / 100)

    if result["strengths"]:
        st.subheader("Strengths")
        for s in result["strengths"]:
            st.markdown(f"- ✅ {s}")

    st.subheader("Suggested improvements")
    icons = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}
    if not result["improvements"]:
        st.info("No improvements returned. Try running the analysis again.")
    for item in result["improvements"]:
        with st.expander(f"{icons[item['priority']]} {item['priority']}: {item['issue'] or 'Improvement'}"):
            if item["fix"]:
                st.markdown(f"**How to fix:** {item['fix']}")
            if item["example"]:
                st.markdown(f"**Example:** {item['example']}")

    if result["missing_keywords"]:
        st.subheader("Missing keywords to consider")
        st.write(", ".join(f"`{k}`" for k in result["missing_keywords"]))

    report = format_report(result)
    st.download_button("Download report (.txt)", report, file_name="ats_report.txt")


def format_report(result: dict) -> str:
    lines = [f"ATS SCORE: {result['overall']}/100 ({score_label(result['overall'])})", ""]
    lines.append(result["summary"])
    lines += ["", "CATEGORY SCORES"]
    lines += [f"- {k}: {v}" for k, v in result["category_scores"].items()]
    lines += ["", "STRENGTHS"] + [f"- {s}" for s in result["strengths"]]
    lines += ["", "IMPROVEMENTS"]
    for i in result["improvements"]:
        lines.append(f"- [{i['priority']}] {i['issue']}\n    Fix: {i['fix']}")
        if i["example"]:
            lines.append(f"    Example: {i['example']}")
    lines += ["", "MISSING KEYWORDS", ", ".join(result["missing_keywords"])]
    return "\n".join(lines)


def main() -> None:
    st.set_page_config(page_title="Resume ATS Checker", page_icon="📄", layout="wide")
    st.title("📄 Resume ATS Score & Improvement Checker")
    st.caption("Upload your resume to get an ATS score and specific, actionable improvements.")

    api_key = get_secret("GEMINI_API_KEY")
    model = get_secret("GEMINI_MODEL", DEFAULT_MODEL)

    with st.sidebar:
        st.header("Settings")
        if not api_key:
            api_key = st.text_input("Gemini API key", type="password", help="Get one at aistudio.google.com")
        else:
            st.success("API key loaded")
        model = st.text_input("Model", value=model)
        st.caption("Your resume is sent to Google's Gemini API for analysis and is not stored by this app.")

    uploaded = st.file_uploader("Upload resume", type=["pdf", "docx", "txt"])
    job_description = st.text_area(
        "Target job description (optional, improves keyword matching)", height=150, max_chars=MAX_JD_CHARS
    )

    if st.button("Analyze resume", type="primary", disabled=uploaded is None):
        if not api_key:
            st.error("Please provide a Gemini API key in the sidebar.")
            return
        if uploaded.size > MAX_FILE_MB * 1024 * 1024:
            st.error(f"File is too large. Maximum size is {MAX_FILE_MB} MB.")
            return
        try:
            resume_text = extract_text(uploaded.name, uploaded.getvalue())
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
            return
        if len(resume_text) < MIN_RESUME_CHARS:
            st.error(
                "Very little text could be extracted. If your resume is a scanned image, "
                "this is exactly what an ATS would see too — export a text-based PDF or DOCX."
            )
            return
        with st.spinner("Analyzing your resume..."):
            try:
                st.session_state["result"] = analyze_resume(resume_text, job_description, api_key, model)
            except Exception as exc:
                st.session_state.pop("result", None)
                st.error(f"Analysis failed: {exc}")
                return

    if "result" in st.session_state:
        render_results(st.session_state["result"])


if __name__ == "__main__":
    main()
