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

# Aggiungi uno snippet CSS per una grafica moderna
st.markdown(
    """
    <style>
    .main {
        background-color: #f9f9f9;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    .header-title {
        font-size: 2.5rem;
        color: #333333;
        margin-bottom: 0.5rem;
    }
    .header-description {
        font-size: 1.2rem;
        color: #555555;
        margin-bottom: 2rem;
    }
    </style>
    """, unsafe_allow_html=True
)

########################################
# 1) Carica variabili d'ambiente (solo Python)
########################################
load_dotenv()

########################################
# 2) Configura la pagina con un layout moderno
########################################
st.set_page_config(page_title="Revisione Documenti 2.0", layout="wide")

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
# Definizione dei pattern critici e opzioni di tono
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

TONE_OPTIONS = {
    "Stile originale": "Mantieni lo stesso stile del testo originale, stessa struttura della frase.",
    "Formale": "Riscrivi in modo formale e professionale.",
    "Informale": "Riscrivi in modo amichevole e colloquiale rivolto a un lettore giovane.",
    "Tecnico": "Riscrivi con linguaggio tecnico e preciso.",
    "Narrativo": "Riscrivi in stile descrittivo e coinvolgente.",
    "Pubblicitario": "Riscrivi in modo persuasivo, come una pubblicità.",
    "Giornalistico": "Riscrivi in tono chiaro e informativo.",
}

########################################
# Funzioni di supporto (conversione, estrazione contesto, etc.)
########################################
def convert_first_singular_to_plural(text):
    replacements = {
        r'\b[Ii]o\b': 'noi',
        r'\b[Mm]io\b': 'nostro',
        r'\b[Mm]ia\b': 'nostra',
        r'\b[Mm]iei\b': 'nostri',
        r'\b[Mm]ie\b': 'nostre',
        r'\b[Mm]i\b': 'ci',
    }
    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text)
    return text

def extract_context(blocks, selected_block):
    try:
        index = blocks.index(selected_block)
    except ValueError:
        logger.error("Blocco non trovato.")
        return "", ""
    prev_block = blocks[index - 1] if index > 0 else ""
    next_block = blocks[index + 1] if index < len(blocks) - 1 else ""
    return prev_block, next_block

def ai_rewrite_text(text, prev_text, next_text, tone):
    prompt = (
        f"Contesto:\nPrecedente: {prev_text}\nTesto: {text}\nSuccessivo: {next_text}\n\n"
        f"Riscrivi il 'Testo' in tono '{tone}'. Rimuovi eventuali dettagli personali. "
        "Rispondi con UNA sola frase."
    )
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.0-pro-exp-02-05:free",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=50
        )
        if response and hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content.strip()
        error_message = "⚠️ Errore: Nessun testo valido restituito dall'API."
        logger.error(error_message)
        return error_message
    except Exception as e:
        error_message = f"⚠️ Errore: {e}"
        logger.error(error_message)
        return error_message

def process_html_content(html_content, modifications, highlight=False):
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup.find_all(["p", "span", "div", "li", "a", "h5"]):
        if tag.string:
            original = tag.string.strip()
            if original in modifications:
                mod_text = modifications[original]
                if highlight:
                    new_tag = soup.new_tag("span", style="background-color: #ffeaa7; font-weight: bold;")
                    new_tag.string = mod_text
                    tag.string.replace_with("")
                    tag.append(new_tag)
                else:
                    tag.string.replace_with(mod_text)
    return str(soup)

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
# Sidebar per impostazioni e modalità
########################################
st.sidebar.title("Impostazioni")
st.sidebar.info(
    "Benvenuto in Revisione Documenti 2.0!\n\n"
    "Carica un documento e scegli la modalità di revisione.\n"
    "Puoi rivedere blocchi specifici o applicare una conversione globale."
)
modalita = st.sidebar.radio(
    "Modalità di revisione:",
    ("Revisiona blocchi corrispondenti", "Conversione intera (solo)", "Revisiona blocchi e applica conversione globale")
)
global_conversion = modalita == "Revisiona blocchi e applica conversione globale"

########################################
# Logica principale: Caricamento file e interfaccia
########################################
st.markdown("<h1 class='header-title'>📄 Revisione Documenti 2.0</h1>", unsafe_allow_html=True)
st.markdown("<p class='header-description'>Carica il tuo file (HTML, Markdown, Word o PDF) e personalizza la revisione del testo con facilità.</p>", unsafe_allow_html=True)
uploaded_file = st.file_uploader("📂 Seleziona un file (html, md, doc, docx, pdf)", type=["html", "md", "doc", "docx", "pdf"])

if uploaded_file is not None:
    file_extension = uploaded_file.name.split('.')[-1].lower()
    
    if modalita == "Conversione intera (solo)":
        if file_extension in ["html", "md"]:
            file_content = uploaded_file.read().decode("utf-8")
            converted_text = convert_first_singular_to_plural(file_content)
            st.subheader("Anteprima Documento Revisionato")
            if file_extension == "html":
                st.markdown(converted_text, unsafe_allow_html=True)
            else:
                st.write(converted_text)
            if st.button("Scarica Documento Revisionato"):
                st.download_button("Scarica Revisionato", converted_text.encode("utf-8"), "document_revised.html" if file_extension=="html" else "document_revised.txt", "text/html" if file_extension=="html" else "text/plain")
        elif file_extension in ["doc", "docx"]:
            paragraphs = process_doc_file(uploaded_file)
            full_text = "\n".join(paragraphs)
            converted_text = convert_first_singular_to_plural(full_text)
            st.subheader("Anteprima Documento Revisionato")
            st.write(converted_text)
            if st.button("Scarica Documento Revisionato"):
                new_doc = Document()
                new_doc.add_paragraph(converted_text)
                buffer = io.BytesIO()
                new_doc.save(buffer)
                st.download_button("Scarica Documento Revisionato", buffer.getvalue(), "document_revised.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif file_extension == "pdf":
            paragraphs = process_pdf_file(uploaded_file)
            full_text = "\n".join(paragraphs)
            converted_text = convert_first_singular_to_plural(full_text)
            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.set_font("Arial", size=12)
            pdf.multi_cell(0, 10, converted_text)
            buffer = io.BytesIO()
            pdf.output(buffer, 'F')
            st.subheader("Anteprima PDF Revisionato")
            if st.button("Scarica PDF Revisionato"):
                st.download_button("Scarica PDF Revisionato", buffer.getvalue(), "document_revised.pdf", "application/pdf")
    
    else:
        modifications = {}
        scelte_utente = {}
        
        if file_extension in ["html", "md"]:
            file_content = uploaded_file.read().decode("utf-8")
            blocchi, html_content = process_file_content(file_content, file_extension)
            blocchi_da_revisionare = filtra_blocchi(blocchi)
            if blocchi_da_revisionare:
                st.subheader("Blocchi da revisionare")
                progress_text = st.empty()
                progress_bar = st.progress(0)
                total = len(blocchi_da_revisionare)
                count = 0
                for uid, blocco in blocchi_da_revisionare.items():
                    st.markdown(f"**{blocco}**")
                    azione = st.radio("Scegli l'azione:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                    tono = None
                    if azione == "Riscrivi":
                        tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    scelte_utente[blocco] = {"azione": azione, "tono": tono}
                    count += 1
                    progress_bar.progress(count / total)
                    progress_text.text(f"Elaborati {count} di {total} blocchi...")
                
                if st.button("Genera Documento Revisionato"):
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
                        final_content = convert_first_singular_to_plural(final_content)
                    st.success("Revisione completata!")
                    st.subheader("Anteprima Documento Revisionato")
                    st.components.v1.html(final_content, height=500, scrolling=True)
                    st.download_button("Scarica Documento Revisionato", final_content.encode("utf-8"), "document_revised.html", "text/html")
            else:
                st.info("Nessun blocco corrisponde ai criteri di revisione.")
        
        elif file_extension in ["doc", "docx"]:
            paragrafi = process_doc_file(uploaded_file)
            blocchi_da_revisionare = filtra_blocchi(paragrafi)
            if blocchi_da_revisionare:
                st.subheader("Paragrafi da revisionare")
                progress_text = st.empty()
                progress_bar = st.progress(0)
                total = len(blocchi_da_revisionare)
                count = 0
                for uid, paragrafo in blocchi_da_revisionare.items():
                    st.markdown(f"**{paragrafo}**")
                    azione = st.radio("Scegli l'azione:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                    tono = None
                    if azione == "Riscrivi":
                        tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    scelte_utente[paragrafo] = {"azione": azione, "tono": tono}
                    count += 1
                    progress_bar.progress(count / total)
                    progress_text.text(f"Elaborati {count} di {total} paragrafi...")
                
                if st.button("Genera Documento Revisionato"):
                    modifications = {}
                    for paragrafo, info in scelte_utente.items():
                        if info["azione"] == "Riscrivi":
                            prev_par, next_par = extract_context(paragrafi, paragrafo)
                            mod_par = ai_rewrite_text(paragrafo, prev_par, next_par, info["tono"])
                            modifications[paragrafo] = mod_par
                        elif info["azione"] == "Elimina":
                            modifications[paragrafo] = ""
                        else:
                            modifications[paragrafo] = paragrafo
                    full_text = "\n".join([modifications.get(p, p) for p in paragrafi])
                    if global_conversion:
                        full_text = convert_first_singular_to_plural(full_text)
                    new_doc = Document()
                    new_doc.add_paragraph(full_text)
                    buffer = io.BytesIO()
                    new_doc.save(buffer)
                    st.success("Revisione completata!")
                    st.subheader("Anteprima Documento Revisionato")
                    st.download_button("Scarica Documento Revisionato", buffer.getvalue(), "document_revised.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            else:
                st.info("Nessun paragrafo corrisponde ai criteri di revisione.")
        
        elif file_extension == "pdf":
            paragrafi = process_pdf_file(uploaded_file)
            blocchi_da_revisionare = filtra_blocchi(paragrafi)
            if blocchi_da_revisionare:
                st.subheader("Blocchi di testo da revisionare (PDF)")
                progress_text = st.empty()
                progress_bar = st.progress(0)
                total = len(blocchi_da_revisionare)
                count = 0
                for uid, blocco in blocchi_da_revisionare.items():
                    st.markdown(f"**{blocco}**")
                    azione = st.radio("Scegli l'azione:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                    tono = None
                    if azione == "Riscrivi":
                        tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    scelte_utente[blocco] = {"azione": azione, "tono": tono}
                    count += 1
                    progress_bar.progress(count / total)
                    progress_text.text(f"Elaborati {count} di {total} blocchi...")
                
                if st.button("Genera PDF Revisionato"):
                    modifications = {}
                    for blocco, info in scelte_utente.items():
                        if info["azione"] == "Riscrivi":
                            prev_blocco, next_blocco = extract_context(paragrafi, blocco)
                            mod_blocco = ai_rewrite_text(blocco, prev_blocco, next_blocco, info["tono"])
                            modifications[blocco] = mod_blocco
                        elif info["azione"] == "Elimina":
                            modifications[blocco] = ""
                        else:
                            modifications[blocco] = blocco
                    if global_conversion:
                        for key in modifications:
                            modifications[key] = convert_first_singular_to_plural(modifications[key])
                    with st.spinner("Elaborazione in corso..."):
                        revised_pdf = process_pdf_with_overlay(uploaded_file, modifications)
                    st.success("Revisione completata!")
                    st.download_button("Scarica PDF Revisionato", revised_pdf, "document_revised.pdf", "application/pdf")
            else:
                st.info("Nessun blocco corrisponde ai criteri di revisione nel PDF.")
