import streamlit as st
import openai
import os
import re
import logging
import io
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import markdown
from docx import Document
from PyPDF2 import PdfReader
from fpdf import FPDF
from pydantic import BaseModel

# Configurazione iniziale
########################################

# 1) Configurazione Streamlit (DEVE ESSERE LA PRIMA ISTRUZIONE DOPO LE IMPORT)
st.set_page_config(
    page_title="Revisione Documenti",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="📄"
)

# 2) Carica variabili d'ambiente
load_dotenv()

class Settings(BaseModel):
    OPENROUTER_API_KEY: str

# Carica le variabili d'ambiente
settings = Settings(OPENROUTER_API_KEY=os.getenv("OPENROUTER_API_KEY"))

# 3) Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 4) Recupera la chiave API
API_KEY = settings.OPENROUTER_API_KEY
if not API_KEY:
    st.error("⚠️ Errore: API Key di OpenRouter non trovata! Impostala come variabile d'ambiente.")
    st.stop()

# Verifica la validità della chiave API
try:
    client = openai.OpenAI(api_key=API_KEY, base_url="https://openrouter.ai/api/v1")
    test_response = client.chat.completions.create(
        model="google/gemini-2.0-pro-exp-02-05:free",
        messages=[{"role": "system", "content": "Test"}]
    )
    if not test_response:
        st.error("⚠️ Errore: Chiave API non valida!")
        st.stop()
except Exception as e:
    st.error(f"⚠️ Errore di connessione all'API: {e}")
    st.stop()

# Pattern critici per la revisione
CRITICAL_PATTERNS = [
    r"\bIlias Contreas\b", r"\bIlias\b", r"\bContreas\b", r"\bJoey\b", r"\bMya\b",
    r"\bmia moglie\b", r"\bmia figlia\b", r"\bShake Your English\b", r"\bBarman PR\b",
    r"\bStairs Club\b", r"\bil mio socio\b", r"\bio e il mio socio\b", r"\bil mio corso\b",
    r"\bla mia accademia\b", r"\bintervista\b", r"Mi chiamo .*? la mia esperienza personale\.",
    r"\bflair\b", r"\bfiglio di papà\b", r"\bhappy our\b",
]
compiled_patterns = [re.compile(p, re.IGNORECASE) for p in CRITICAL_PATTERNS]

# Opzioni di tono per la riscrittura
TONE_OPTIONS = {
    "Stile originale": "Mantieni lo stesso stile e struttura del testo originale.",
    "Formale": "Riscrivi in modo formale e professionale, adatto a documenti ufficiali.",
    "Informale": "Riscrivi in modo amichevole e colloquiale, adatto a comunicazioni informali.",
    "Tecnico": "Riscrivi con linguaggio tecnico e preciso, adatto ad un manuale tecnico.",
    "Narrativo": "Riscrivi in modo descrittivo e coinvolgente stile racconto.",
    "Pubblicitario": "Riscrivi in modo persuasivo, come una pubblicità.",
    "Giornalistico": "Riscrivi in tono chiaro e informativo.",
}

# Funzioni di supporto
########################################

def ai_convert_first_singular_to_plural(text):
    if not text.strip():
        return ""
    prompt = (
        "Riscrivi il seguente testo modificando esclusivamente il modo di interloquire da prima persona singolare a prima persona plurale. "
        "Mantieni invariato il contenuto e il senso logico.\n\n"
        f"Testo originale:\n{text}"
    )
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.0-pro-exp-02-05:free",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=500,
            timeout=10
        )
        if response and hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content.strip()
        logger.error("⚠️ Errore: Nessun testo valido restituito dall'API.")
        return ""
    except Exception as e:
        logger.error(f"⚠️ Errore nell'elaborazione: {e}")
        return ""

def convert_plain_text_to_minimal_html(text):
    paragraphs = "".join(f"<p>{line.strip()}</p>" for line in text.splitlines() if line.strip())
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <title>Documento Revisionato</title>
</head>
<body>
{paragraphs}
</body>
</html>"""

def extract_context(blocks, selected_block):
    try:
        index = blocks.index(selected_block)
        prev_block = blocks[index - 1] if index > 0 else ""
        next_block = blocks[index + 1] if index < len(blocks) - 1 else ""
        return prev_block, next_block
    except ValueError:
        logger.error("Il blocco selezionato non è presente nella lista.")
        return "", ""

def ai_rewrite_text(text, prev_text, next_text, tone):
    prompt = (
        f"Contesto:\nPrecedente: {prev_text}\nTesto: {text}\nSuccessivo: {next_text}\n\n"
        f"Riscrivi il 'Testo' in tono '{tone}'. Rimuovi eventuali dettagli personali o identificabili. "
        "Rispondi con UNA sola frase, senza ulteriori commenti."
    )
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.0-pro-exp-02-05:free",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=50
        )
        if response and hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content.strip()
        logger.error("⚠️ Errore: Nessun testo valido restituito dall'API.")
        return ""
    except Exception as e:
        logger.error(f"⚠️ Errore nell'elaborazione: {e}")
        return ""

def process_file_content(file_content, file_extension):
    if file_extension == "html":
        soup = BeautifulSoup(file_content, "html.parser")
        blocks = [tag.get_text().strip() for tag in soup.find_all(["p", "span", "div", "li", "a", "h5"]) if tag.get_text().strip()]
        return blocks, file_content
    elif file_extension == "md":
        html_content = markdown.markdown(file_content)
        soup = BeautifulSoup(html_content, "html.parser")
        blocks = [tag.get_text().strip() for tag in soup.find_all(["p", "span", "div", "li", "a", "h5"]) if tag.get_text().strip()]
        return blocks, html_content
    return [], ""

def process_doc_file(uploaded_file):
    try:
        doc = Document(uploaded_file)
        return [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    except Exception as e:
        st.error(f"Errore nell'apertura del file Word: {e}")
        st.stop()

def process_pdf_file(uploaded_file):
    try:
        pdf_reader = PdfReader(uploaded_file)
        paragraphs = []
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text:
                paragraphs.extend([line.strip() for line in text.split("\n") if line.strip()])
        return paragraphs
    except Exception as e:
        st.error(f"Errore nell'apertura del file PDF: {e}")
        st.stop()

def filtra_blocchi(blocchi):
    # Rimuovi duplicati mantenendo l'ordine
    blocchi_unici = list(dict.fromkeys(blocchi))
    return {f"{i}_{b}": b for i, b in enumerate(blocchi_unici) if any(pattern.search(b) for pattern in compiled_patterns)}

# Logica principale
########################################

st.title("📄 Revisione Documenti")
st.write("Carica un file (HTML, Markdown, Word o PDF) e scegli come intervenire sul testo.")

# Definizione della modalità
modalita = st.radio(
    "Modalità di revisione:",
    ("Riscrittura blocchi critici", "Conversione completa in plurale", "Blocchi critici + conversione completa"),
    help="Scegli la modalità di revisione più adatta alle tue esigenze."
)

uploaded_file = st.file_uploader("📂 Seleziona un file (html, md, doc, docx, pdf)", type=["html", "md", "doc", "docx", "pdf"])

if uploaded_file is not None:
    try:
        file_bytes = uploaded_file.read()
        uploaded_file.seek(0)
        file_extension = uploaded_file.name.split('.')[-1].lower()
        st.success(f"File caricato con successo: {uploaded_file.name}")
    except Exception as e:
        st.error(f"Errore durante la lettura del file: {e}")
        st.stop()

    if modalita == "Conversione completa in plurale":
        if file_extension in ["html", "md"]:
            file_content = file_bytes.decode("utf-8")
            if file_extension == "html":
                soup = BeautifulSoup(file_content, "html.parser")
                body = soup.body
                original_body_text = body.get_text(separator="\n") if body else file_content
            else:
                original_body_text = file_content

            if st.button("Genera Anteprima Conversione Completa in Plurale"):
                converted_text = ai_convert_first_singular_to_plural(original_body_text)
                st.session_state.converted_text = converted_text

            if "converted_text" in st.session_state:
                st.subheader("📌 Testo Revisionato (Conversione Completa in Plurale)")
                if "<" in st.session_state.converted_text:
                    final_html = st.session_state.converted_text
                else:
                    final_html = convert_plain_text_to_minimal_html(st.session_state.converted_text)
                st.components.v1.html(final_html, height=500, scrolling=True)
                st.download_button(
                    "📥 Scarica File Revisionato",
                    data=final_html.encode("utf-8"),
                    file_name="document_revised.html",
                    mime="text/html"
                )
        elif file_extension in ["doc", "docx"]:
            paragraphs = process_doc_file(io.BytesIO(file_bytes))
            full_text = "\n".join(paragraphs)
            if st.button("Genera Anteprima Conversione Completa in Plurale"):
                converted_text = ai_convert_first_singular_to_plural(full_text)
                st.session_state.converted_text = converted_text

            if "converted_text" in st.session_state:
                st.subheader("📌 Testo Revisionato (Conversione Completa in Plurale)")
                st.write(st.session_state.converted_text)
                new_doc = Document()
                new_doc.add_paragraph(st.session_state.converted_text)
                buffer = io.BytesIO()
                new_doc.save(buffer)
                st.download_button(
                    "📥 Scarica Documento Revisionato",
                    data=buffer.getvalue(),
                    file_name="document_revised.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
        elif file_extension == "pdf":
            paragraphs = process_pdf_file(io.BytesIO(file_bytes))
            full_text = "\n".join(paragraphs)
            if st.button("Genera Anteprima Conversione Completa in Plurale"):
                converted_text = ai_convert_first_singular_to_plural(full_text)
                st.session_state.converted_text = converted_text

            if "converted_text" in st.session_state:
                st.subheader("📌 PDF Revisionato (Conversione Completa in Plurale)")
                pdf = FPDF()
                pdf.add_page()
                pdf.set_auto_page_break(auto=True, margin=15)
                pdf.set_font("Arial", size=12)
                pdf.multi_cell(0, 10, st.session_state.converted_text)
                buffer = io.BytesIO()
                pdf.output(buffer, 'F')
                st.download_button(
                    "📥 Scarica PDF Revisionato",
                    data=buffer.getvalue(),
                    file_name="document_revised.pdf",
                    mime="application/pdf"
                )
    else:
        modifications = {}
        scelte_utente = {}

        if file_extension in ["html", "md"]:
            file_content = file_bytes.decode("utf-8")
            blocchi, html_content = process_file_content(file_content, file_extension)
            blocchi_da_revisionare = filtra_blocchi(blocchi)
            if blocchi_da_revisionare:
                st.subheader("📌 Blocchi da revisionare")
                progress_text = st.empty()
                progress_bar = st.progress(0)
                total = len(blocchi_da_revisionare)
                count = 0
                for uid, blocco in blocchi_da_revisionare.items():
                    st.markdown(f"**{blocco}**")
                    azione = st.radio("Azione per questo blocco:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                    tono = None
                    if azione == "Riscrivi":
                        tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    scelte_utente[blocco] = {"azione": azione, "tono": tono}
                    count += 1
                    progress_bar.progress(count / total)
                    progress_text.text(f"Elaborati {count} di {total} blocchi...")

                if st.button("✍️ Genera Documento Revisionato"):
                    for blocco, info in scelte_utente.items():
                        if info["azione"] == "Riscrivi":
                            prev_blocco, next_blocco = extract_context(blocchi, blocco)
                            mod_blocco = ai_rewrite_text(blocco, prev_blocco, next_blocco, info["tono"])
                            modifications[blocco] = mod_blocco
                        elif info["azione"] == "Elimina":
                            modifications[blocco] = ""
                        else:
                            modifications[blocco] = blocco
                    final_content = process_html_content(html_content, modifications, highlight=True)
                    if global_conversion:
                        final_content = ai_convert_first_singular_to_plural(final_content)
                    st.success("✅ Revisione completata!")
                    st.subheader("🌍 Anteprima con Testo Revisionato")
                    st.components.v1.html(final_content, height=500, scrolling=True)
                    st.download_button(
                        "📥 Scarica HTML Revisionato",
                        data=final_content.encode("utf-8"),
                        file_name="document_revised.html",
                        mime="text/html"
                    )
            else:
                st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel testo.")
        elif file_extension in ["doc", "docx"]:
            paragraphs = process_doc_file(io.BytesIO(file_bytes))
            blocchi_da_revisionare = filtra_blocchi(paragraphs)
            if blocchi_da_revisionare:
                st.subheader("📌 Paragrafi da revisionare")
                progress_text = st.empty()
                progress_bar = st.progress(0)
                total = len(blocchi_da_revisionare)
                count = 0
                for uid, paragrafo in blocchi_da_revisionare.items():
                    st.markdown(f"**{paragrafo}**")
                    azione = st.radio("Azione per questo paragrafo:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                    tono = None
                    if azione == "Riscrivi":
                        tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    scelte_utente[paragrafo] = {"azione": azione, "tono": tono}
                    count += 1
                    progress_bar.progress(count / total)
                    progress_text.text(f"Elaborati {count} di {total} paragrafi...")

                if st.button("✍️ Genera Documento Revisionato"):
                    modifications = {}
                    for paragrafo, info in scelte_utente.items():
                        if info["azione"] == "Riscrivi":
                            prev_par, next_par = extract_context(paragraphs, paragrafo)
                            mod_par = ai_rewrite_text(paragrafo, prev_par, next_par, info["tono"])
                            modifications[paragrafo] = mod_par
                        elif info["azione"] == "Elimina":
                            modifications[paragrafo] = ""
                        else:
                            modifications[paragrafo] = paragrafo
                    full_text = "\n".join([modifications.get(p, p) for p in paragraphs])
                    if global_conversion:
                        full_text = ai_convert_first_singular_to_plural(full_text)
                    new_doc = Document()
                    new_doc.add_paragraph(full_text)
                    buffer = io.BytesIO()
                    new_doc.save(buffer)
                    st.success("✅ Revisione completata!")
                    st.subheader("🌍 Anteprima Testo (Word)")
                    st.download_button(
                        "📥 Scarica Documento Word Revisionato",
                        data=buffer.getvalue(),
                        file_name="document_revised.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
            else:
                st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel documento Word.")
        elif file_extension == "pdf":
            paragraphs = process_pdf_file(io.BytesIO(file_bytes))
            blocchi_da_revisionare = filtra_blocchi(paragraphs)
            if blocchi_da_revisionare:
                st.subheader("📌 Blocchi di testo da revisionare (PDF)")
                progress_text = st.empty()
                progress_bar = st.progress(0)
                total = len(blocchi_da_revisionare)
                count = 0
                for uid, blocco in blocchi_da_revisionare.items():
                    st.markdown(f"**{blocco}**")
                    azione = st.radio("Azione per questo blocco:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                    tono = None
                    if azione == "Riscrivi":
                        tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    scelte_utente[blocco] = {"azione": azione, "tono": tono}
                    count += 1
                    progress_bar.progress(count / total)
                    progress_text.text(f"Elaborati {count} di {total} blocchi...")

                if st.button("✍️ Genera PDF Revisionato"):
                    modifications = {}
                    for blocco, info in scelte_utente.items():
                        if info["azione"] == "Riscrivi":
                            prev_blocco, next_blocco = extract_context(paragraphs, blocco)
                            mod_blocco = ai_rewrite_text(blocco, prev_blocco, next_blocco, info["tono"])
                            modifications[blocco] = mod_blocco
                        elif info["azione"] == "Elimina":
                            modifications[blocco] = ""
                        else:
                            modifications[blocco] = blocco
                    if global_conversion:
                        for key in modifications:
                            modifications[key] = ai_convert_first_singular_to_plural(modifications[key])
                    with st.spinner("🔄 Riscrittura in corso..."):
                        revised_pdf = process_pdf_with_overlay(io.BytesIO(file_bytes), modifications)
                    st.success("✅ Revisione completata!")
                    st.download_button(
                        "📥 Scarica PDF Revisionato",
                        data=revised_pdf,
                        file_name="document_revised.pdf",
                        mime="application/pdf"
                    )
            else:
                st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel documento PDF.")
