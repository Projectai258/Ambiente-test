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

def filtra_blocchi(blocchi):
    # Rimuovi duplicati mantenendo l'ordine
    blocchi_unici = list(dict.fromkeys(blocchi))
    return {f"{i}_{b}": b for i, b in enumerate(blocchi_unici) if any(pattern.search(b) for pattern in compiled_patterns)}

# Logica principale
if uploaded_file is not None:
    try:
        file_bytes = uploaded_file.read()
        uploaded_file.seek(0)
        file_extension = uploaded_file.name.split('.')[-1].lower()
        st.success(f"File caricato con successo: {uploaded_file.name}")
    except Exception as e:
        st.error(f"Errore durante la lettura del file: {e}")
        st.stop()

    if modalita == "Riscrittura blocchi critici":
        if file_extension in ["html", "md"]:
            file_content = file_bytes.decode("utf-8")
            blocchi, html_content = process_file_content(file_content, file_extension)
            st.write("Blocchi estratti:", blocchi)  # Debug: mostra i blocchi estratti
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
