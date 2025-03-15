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

########################################
# 1) Carica variabili d'ambiente
########################################
load_dotenv()

########################################
# 2) Configurazione Streamlit
########################################
st.set_page_config(page_title="Revisione Documenti", layout="wide")

########################################
# 3) Configurazione logging
########################################
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

########################################
# 4) Recupera la chiave API
########################################
API_KEY = os.getenv("OPENROUTER_API_KEY") or st.secrets.get("OPENROUTER_API_KEY")
if not API_KEY:
    st.error("⚠️ Errore: API Key di OpenRouter non trovata! Impostala come variabile d'ambiente o in st.secrets.")
    st.stop()

client = openai.OpenAI(api_key=API_KEY, base_url="https://openrouter.ai/api/v1")

########################################
# Pattern critici per la revisione
########################################
CRITICAL_PATTERNS = [
    r"\bIlias Contreas\b",
    r"\bIlias\b",
    r"\bContreas\b",
    r"\bJoey\b",
    r"\bMya\b",
    r"\bmia moglie\b",
    r"\bmia figlia\b",
    r"\bShake Your English\b",
    r"\bBarman PR\b",
    r"\bStairs Club\b",
    r"\bil mio socio\b",
    r"\bio e il mio socio\b",
    r"\bil mio corso\b",
    r"\bla mia accademia\b",
    r"\bintervista\b",
    r"Mi chiamo .*? la mia esperienza personale\.",
    r"\bflair\b",
    r"\bfiglio di papà\b",
    r"\bhappy our\b",
]
compiled_patterns = [re.compile(p, re.IGNORECASE) for p in CRITICAL_PATTERNS]

########################################
# Opzioni di tono per la riscrittura (per blocchi)
########################################
TONE_OPTIONS = {
    "Stile originale": "Mantieni lo stesso stile e struttura del testo originale.",
    "Formale": "Riscrivi in modo formale e professionale.",
    "Informale": "Riscrivi in modo amichevole e colloquiale.",
    "Tecnico": "Riscrivi con linguaggio tecnico e preciso.",
    "Narrativo": "Riscrivi in modo descrittivo e coinvolgente.",
    "Pubblicitario": "Riscrivi in modo persuasivo, come una pubblicità.",
    "Giornalistico": "Riscrivi in tono chiaro e informativo.",
}

########################################
# Funzione AI per conversione in plurale
########################################
def ai_convert_first_singular_to_plural(text):
    prompt = (
        "Riscrivi il seguente testo modificando esclusivamente il modo di interloquire da prima persona singolare a prima persona plurale. "
        "Mantieni invariato il contenuto e il senso logico.\n\n"
        f"Testo originale:\n{text}"
    )
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.0-pro-exp-02-05:free",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=500
        )
        if response and hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content.strip()
        logger.error("⚠️ Errore: Nessun testo valido restituito dall'API.")
        return ""
    except Exception as e:
        logger.error(f"⚠️ Errore nell'elaborazione: {e}")
        return ""

########################################
# Funzione per "wrap" del testo convertito in HTML
########################################
def wrap_converted_text(original_html, converted_text):
    """
    Estrae il tag <head> dall'HTML originale e crea un nuovo <body>
    in cui ogni riga (o blocco separato da newline) del testo convertito
    diventa un paragrafo (<p>).
    """
    soup = BeautifulSoup(original_html, "html.parser")
    head = soup.head
    new_body = soup.new_tag("body")
    for line in converted_text.split("\n"):
        if line.strip():
            p = soup.new_tag("p")
            p.string = line.strip()
            new_body.append(p)
    # Se c'era già un body, sostituiscilo, altrimenti aggiungi il nuovo body
    if soup.body:
        soup.body.replace_with(new_body)
    else:
        soup.append(new_body)
    return str(soup)

########################################
# Funzioni di supporto
########################################
def extract_context(blocks, selected_block):
    try:
        index = blocks.index(selected_block)
    except ValueError:
        logger.error("Il blocco selezionato non è presente nella lista.")
        return "", ""
    prev_block = blocks[index - 1] if index > 0 else ""
    next_block = blocks[index + 1] if index < len(blocks) - 1 else ""
    return prev_block, next_block

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

def process_html_content(html_content, modifications, highlight=False):
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup.find_all(["p", "span", "div", "li", "a", "h5"]):
        if tag.string:
            original = tag.string.strip()
            if original in modifications:
                mod_text = modifications[original]
                if highlight:
                    new_tag = soup.new_tag("span", style="background-color: yellow; font-weight: bold;")
                    new_tag.string = mod_text
                    tag.string.replace_with("")
                    tag.append(new_tag)
                else:
                    tag.string.replace_with(mod_text)
    return str(soup)

def generate_html_preview(blocks, modifications, highlight=False):
    html = ""
    for block in blocks:
        mod_text = modifications.get(block, block)
        if highlight:
            html += f'<p><span style="background-color: yellow; font-weight: bold;">{mod_text}</span></p>'
        else:
            html += f"<p>{mod_text}</p>"
    return html

def process_file_content(file_content, file_extension):
    if file_extension == "html":
        html_content = file_content
    elif file_extension == "md":
        html_content = markdown.markdown(file_content)
    else:
        html_content = ""
    if html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        blocks = [tag.string.strip() for tag in soup.find_all(["p", "span", "div", "li", "a", "h5"]) if tag.string]
        return blocks, html_content
    return [], ""

def process_doc_file(uploaded_file):
    try:
        doc = Document(uploaded_file)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return paragraphs
    except Exception as e:
        st.error(f"Errore nell'apertura del file Word: {e}")
        st.stop()

def process_pdf_file(uploaded_file):
    try:
        pdf_reader = PdfReader(uploaded_file)
    except Exception as e:
        st.error(f"Errore nell'apertura del file PDF: {e}")
        st.stop()
    paragraphs = []
    for page in pdf_reader.pages:
        text = page.extract_text()
        if text:
            paragraphs.extend([line.strip() for line in text.split("\n") if line.strip()])
    return paragraphs

def filtra_blocchi(blocchi):
    return {f"{i}_{b}": b for i, b in enumerate(blocchi) if any(pattern.search(b) for pattern in compiled_patterns)}

def process_pdf_with_overlay(uploaded_file, modifications):
    import fitz  # PyMuPDF
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        blocks = page.get_text("blocks")
        for b in blocks:
            block_text = b[4].strip()
            for original, revised in modifications.items():
                if original in block_text:
                    rect = fitz.Rect(b[0], b[1], b[2], b[3])
                    page.add_redact_annot(rect, fill=(1,1,1))
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                    page.insert_textbox(rect, revised, fontsize=12, fontname="helv", align=1)
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()

########################################
# Modalità di revisione
########################################
modalita = st.radio(
    "Modalità di revisione:",
    ("Riscrittura blocchi critici", "Conversione completa in plurale", "Blocchi critici + conversione completa")
)
global_conversion = modalita in ["Conversione completa in plurale", "Blocchi critici + conversione completa"]

########################################
# Logica principale
########################################
st.title("📄 Revisione Documenti")
st.write("Carica un file (HTML, Markdown, Word o PDF) e scegli come intervenire sul testo.")

uploaded_file = st.file_uploader("📂 Seleziona un file (html, md, doc, docx, pdf)", type=["html", "md", "doc", "docx", "pdf"])

if uploaded_file is not None:
    # Leggi il file una sola volta e salva i byte
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    file_extension = uploaded_file.name.split('.')[-1].lower()
    
    # Modalità "Conversione completa in plurale" (AI su tutto il testo)
    if modalita == "Conversione completa in plurale":
        if file_extension in ["html", "md"]:
            file_content = file_bytes.decode("utf-8")
            if file_extension == "html":
                # Per file HTML, estrai il tag <head> e il contenuto del <body>
                soup = BeautifulSoup(file_content, "html.parser")
                head = soup.head
                if not head:
                    st.error("Il file HTML non contiene un tag <head>.")
                else:
                    body = soup.body
                    if body:
                        original_body_text = body.get_text(separator="\n")
                    else:
                        original_body_text = ""
                    if st.button("Genera Anteprima Conversione Completa in Plurale"):
                        converted_text = ai_convert_first_singular_to_plural(original_body_text)
                        st.session_state.converted_text = converted_text
                    if "converted_text" in st.session_state:
                        st.subheader("📌 Testo Revisionato (Conversione Completa in Plurale)")
                        # Ricrea un nuovo body con il testo convertito, suddividendo per newline
                        final_html = wrap_converted_text(file_content, st.session_state.converted_text)
                        st.components.v1.html(final_html, height=500, scrolling=True)
                        st.download_button("📥 Scarica File Revisionato",
                                           data=final_html.encode("utf-8"),
                                           file_name="document_revised.html",
                                           mime="text/html")
            else:
                # Per Markdown, applica la conversione direttamente
                if st.button("Genera Anteprima Conversione Completa in Plurale"):
                    converted_text = ai_convert_first_singular_to_plural(file_content)
                    st.session_state.converted_text = converted_text
                if "converted_text" in st.session_state:
                    st.subheader("📌 Testo Revisionato (Conversione Completa in Plurale)")
                    st.write(st.session_state.converted_text)
                    st.download_button("📥 Scarica File Revisionato",
                                       data=st.session_state.converted_text.encode("utf-8"),
                                       file_name="document_revised.txt",
                                       mime="text/plain")
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
                st.download_button("📥 Scarica Documento Revisionato",
                                   data=buffer.getvalue(),
                                   file_name="document_revised.docx",
                                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
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
                st.download_button("📥 Scarica PDF Revisionato",
                                   data=buffer.getvalue(),
                                   file_name="document_revised.pdf",
                                   mime="application/pdf")
    
    # Modalità "Riscrittura blocchi critici" o "Blocchi critici + conversione completa"
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
                            mod_blocco = ai_rewrite_text(blocco, prev_blocco, next_bloco, info["tono"])
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
                    st.download_button("📥 Scarica HTML Revisionato",
                                       data=final_content.encode("utf-8"),
                                       file_name="document_revised.html",
                                       mime="text/html")
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
                    st.download_button("📥 Scarica Documento Word Revisionato",
                                       data=buffer.getvalue(),
                                       file_name="document_revised.docx",
                                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
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
                    st.download_button("📥 Scarica PDF Revisionato",
                                       data=revised_pdf,
                                       file_name="document_revised.pdf",
                                       mime="application/pdf")
            else:
                st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel documento PDF.")
