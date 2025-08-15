
import os
import io
import re
import streamlit as st
from pypdf import PdfReader
import pdfplumber
from openai import OpenAI

# ------------------ IMPORTANT (READ) ------------------
# This app does NOT contain your OpenAI API key baked in. That is ON PURPOSE.
# Why? Storing API keys directly inside source files is insecure.
# Instead, on Streamlit Community Cloud you will add your key in Settings → Secrets
# OR set environment variable OPENAI_API_KEY when running locally.
#
# If you absolutely want to run locally and don't want to set env vars:
# - Put a file named `openai_key.txt` in the same folder with only your key on the first line
# - Or set environment variable OPENAI_API_KEY
#
# The app will look for the key in this order:
# 1) os.environ["OPENAI_API_KEY"]
# 2) st.secrets["OPENAI_API_KEY"]
# 3) ./openai_key.txt (local fallback)
# -----------------------------------------------------

# --------- Simple built-in templates (you can edit in the app later) ---------
TEMPLATES = {
    "Textbook (concise)": "Write a concise textbook-style note for the topic. Use headings and short bullets.",
    "5-mark exam answer": "Write a structured 5-mark exam answer: Intro, Etiology/Classification, Mechanism/Pathology, Clinical features/Uses, Management/Steps, High-yield bullets.",
    "10-mark exam answer": "Write a structured 10-mark exam answer: Intro, Classification, Detailed Mechanism/Techniques, Indications, Complications, Comparative notes, Summary.",
    "iOS Notes bullets (short)": "Write short, punchy iOS Notes-friendly bullets. Keep nesting to max 2 levels.",
    "Pharmacology tabular (plain)": "Produce plain-text drug tables: Name, Class, MOA, Uses with mechanism, PK, Adverse effects, Contraindications, Pearls."
}

st.set_page_config(page_title="PDF → Notes (simple)", layout="wide")

st.title("PDF → Notes (choose a style)")
st.write("Upload a PDF, choose a style, and generate notes. (No API key stored in this file.)")

# ---- Get OpenAI key (secure) ----
def load_api_key():
    # 1) environment variable
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key.strip()
    # 2) streamlit secrets (works on Streamlit Cloud)
    try:
        key = st.secrets["OPENAI_API_KEY"]
        if key:
            return key.strip()
    except Exception:
        pass
    # 3) local fallback file
    try:
        with open("openai_key.txt", "r") as f:
            k = f.read().strip()
            if k:
                return k
    except Exception:
        pass
    return None

OPENAI_API_KEY = load_api_key()
if not OPENAI_API_KEY:
    st.warning("OpenAI API key not found. On Streamlit Cloud: go to ••• → Settings → Secrets and add OPENAI_API_KEY. Locally: set env var OPENAI_API_KEY or create openai_key.txt.")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- Sidebar options ----
with st.sidebar:
    st.header("Options")
    style_choice = st.selectbox("Choose note style", list(TEMPLATES.keys()))
    custom_prompt = st.text_area("Or paste custom prompt (optional)", height=120)
    temp = st.slider("Creativity (temperature)", 0.0, 1.0, 0.2, 0.05)
    max_pages = st.slider("Max pages to read from PDF (for speed)", 1, 200, 20)
    st.write("---")
    st.markdown("**Tips:**\n- If PDF is scanned image-only, this app may not extract text well. Use digital PDFs for best results.")

uploaded = st.file_uploader("Upload one PDF", type=["pdf"])
if not uploaded:
    st.info("Upload a PDF to begin. You can create a repo on GitHub and upload this file there for Streamlit Cloud deployment.")
    st.stop()

# ---- Extract text from PDF (combine pypdf and pdfplumber fallback) ----
def extract_text_from_pdf_bytes(pdf_bytes, max_pages=20):
    text_chunks = []
    # try pypdf first
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        n = min(len(reader.pages), max_pages)
        for i in range(n):
            page = reader.pages[i]
            txt = page.extract_text() or ""
            if txt.strip():
                text_chunks.append(txt)
    except Exception:
        pass

    if not text_chunks:
        # fallback to pdfplumber (slower but often works)
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                n = min(len(pdf.pages), max_pages)
                for i in range(n):
                    p = pdf.pages[i]
                    txt = p.extract_text() or ""
                    if txt.strip():
                        text_chunks.append(txt)
        except Exception:
            pass

    return "\n\n".join(text_chunks).strip()

bytes_data = uploaded.read()
raw_text = extract_text_from_pdf_bytes(bytes_data, max_pages=max_pages)
if not raw_text:
    st.error("Couldn't extract text from this PDF. Try a different PDF (digital, not scanned).")
    st.stop()

# ---- Choose prompt ----
if custom_prompt and custom_prompt.strip():
    prompt_template = custom_prompt.strip()
else:
    prompt_template = TEMPLATES.get(style_choice, list(TEMPLATES.values())[0])

st.subheader("Preview prompt (you can edit it)")
prompt_preview = st.text_area("Prompt to send to the model", value=prompt_template + "\n\nUse the PDF text below as source; do NOT invent facts.", height=200)

if st.button("Generate notes from PDF"):
    with st.spinner("Generating... (calls OpenAI)"):
        # Limit input length: send up to first ~3000 tokens of text to keep things fast
        source_excerpt = raw_text[:40000]  # conservative character slice
        # Build messages for chat completion
        system_msg = "You are a helpful medical/dental exam notes assistant. Answer concisely and use the given structure."
        user_msg = f"{prompt_preview}\n\nSOURCE:\n{source_excerpt}\n\nConstraints:\n- Use only info from SOURCE. Don't invent facts.\n- Use headings and bullet points where appropriate."

        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=float(temp),
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            )
            out_text = resp.choices[0].message.content
        except Exception as e:
            st.error(f"OpenAI request failed: {e}")
            st.stop()

        st.success("Done — notes generated below.")
        st.markdown("----")
        st.subheader("Generated Notes")
        st.write(out_text)

        st.download_button("Download notes as .md", data=out_text, file_name="notes.md", mime="text/markdown")
        st.download_button("Download notes as .txt", data=out_text, file_name="notes.txt", mime="text/plain")
