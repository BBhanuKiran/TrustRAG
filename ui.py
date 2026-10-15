import os
from html import escape
from pathlib import Path

import streamlit as st

from answering import (
    ABSTENTION,
    DEFAULT_EVIDENCE_THRESHOLD,
    DEFAULT_OLLAMA_MODEL,
    LocalModelError,
    answer_with_local_model,
    get_ollama_models,
)
from rag_engine import EvidenceIndex, InvalidDocumentError


ROOT_DIR = Path(__file__).parent
DATABASE_PATH = ROOT_DIR / "data" / "local-trustrag.sqlite3"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

st.set_page_config(
    page_title="TrustRAG — Evidence Workspace",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --ink: #13242d;
        --muted: #667982;
        --teal: #087e78;
        --teal-dark: #075f5a;
        --line: #dce7e6;
        --paper: #f5f8f7;
    }
    html, body, [class*="css"] {
        font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
        color: var(--ink);
    }
    .stApp { background: linear-gradient(180deg, #f5f8f7 0%, #fbfcfb 48%); }
    [data-testid="stHeader"] { background: rgba(245, 248, 247, 0.9); }
    [data-testid="stSidebar"] {
        background: #102b32;
        border-right: 1px solid #21444a;
    }
    [data-testid="stSidebar"] * { color: #eaf4f2; }
    [data-testid="stSidebar"] [data-baseweb="select"] * { color: #13242d; }
    h1, h2, h3 { font-family: 'Segoe UI', 'Inter', Arial, sans-serif; letter-spacing: -0.035em; }
    h1 { font-size: clamp(2.15rem, 4vw, 3.2rem) !important; }
    .brand {
        color: #d5eeea; font: 800 1.35rem 'Segoe UI', Arial, sans-serif;
        letter-spacing: -0.04em; margin: 0.4rem 0 0.15rem;
    }
    .brand span { color: #70d5c4; }
    .side-note { color: #adc4c4; font-size: 0.88rem; line-height: 1.55; }
    .eyebrow {
        color: var(--teal); font-weight: 700; letter-spacing: .14em;
        text-transform: uppercase; font-size: .76rem;
    }
    .hero-copy { color: var(--muted); font-size: 1.08rem; max-width: 800px; }
    .trust-banner {
        padding: 1rem 1.15rem; border: 1px solid #c5e8df; border-radius: 14px;
        background: linear-gradient(100deg, #eaf8f4, #f5fbf8);
        color: #235750; margin: .7rem 0 1.3rem;
    }
    .citation-card {
        background: white; border: 1px solid var(--line); border-radius: 14px;
        padding: 1rem 1.1rem; margin: .6rem 0;
    }
    .citation-meta { color: var(--teal-dark); font-weight: 700; font-size: .9rem; }
    .citation-text { color: #344951; line-height: 1.65; margin-top: .45rem; }
    div[data-testid="stMetric"] {
        background: white; border: 1px solid var(--line); padding: 1rem 1.1rem;
        border-radius: 14px; box-shadow: 0 4px 14px rgba(14, 44, 49, .035);
    }
    .stButton > button[kind="primary"], .stFormSubmitButton > button {
        border: 0; border-radius: 9px; font-weight: 700; background: var(--teal);
    }
    .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover {
        background: var(--teal-dark); color: white;
    }
    div[data-testid="stExpander"] {
        border: 1px solid var(--line); border-radius: 12px; background: white;
    }
    footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_index() -> EvidenceIndex:
    return EvidenceIndex(DATABASE_PATH)


def render_evidence(evidence: list[dict[str, object]]) -> None:
    if not evidence:
        st.info("No passages met the evidence threshold for this question.")
        return

    sources = {str(item["source"]) for item in evidence}
    if len(sources) > 1:
        st.info(
            "Evidence from multiple documents is shown together so you can compare "
            "their wording. TrustRAG does not automatically label a contradiction."
        )

    for number, item in enumerate(evidence, start=1):
        citation = f"[E{number}]"
        page = item["page"]
        page_text = f" · Page {page}" if page is not None else ""
        score = float(item["score"])
        source = escape(str(item["source"]))
        text = escape(str(item["text"]))
        st.markdown(
            f"""
            <div class="citation-card">
                <div class="citation-meta">{citation} &nbsp; {source}{page_text}
                &nbsp; · &nbsp; Relevance {score:.0%}</div>
                <div class="citation-text">{text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_sidebar() -> tuple[str, int, float, str]:
    with st.sidebar:
        st.markdown('<div class="brand">Trust<span>RAG</span></div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="side-note">Research answers with evidence you can inspect.</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        st.markdown("#### Local answer model")

        try:
            installed_models = get_ollama_models()
            ollama_ready = True
        except LocalModelError:
            installed_models = []
            ollama_ready = False
            st.warning("Ollama is offline. Evidence search still works.")

        if installed_models:
            default_model = (
                DEFAULT_OLLAMA_MODEL
                if DEFAULT_OLLAMA_MODEL in installed_models
                else installed_models[0]
            )
            selected_model = st.selectbox(
                "Installed Ollama model",
                installed_models,
                index=installed_models.index(default_model),
            )
        else:
            if ollama_ready:
                st.info("Ollama is connected. Pull an answer model to enable grounded answers.")
            selected_model = st.text_input(
                "Ollama model name",
                value=os.getenv("TRUSTRAG_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                help="Install this model with `ollama pull llama3.2:3b`.",
            )

        top_k = st.slider("Evidence passages", min_value=1, max_value=8, value=5)
        threshold = st.slider(
            "Minimum evidence strength",
            min_value=0.0,
            max_value=0.8,
            value=DEFAULT_EVIDENCE_THRESHOLD,
            step=0.05,
            help="Passages below this cosine similarity are excluded from answers.",
        )
        st.divider()
        st.markdown(
            '<div class="side-note">Private by design: PDFs are processed locally. '
            'Only extracted text and embeddings are kept in your local index.</div>',
            unsafe_allow_html=True,
        )
        st.caption("Local demo · Not intended for public exposure without authentication.")

    model_status = (
        "Ready"
        if installed_models
        else "No models"
        if ollama_ready
        else "Offline"
    )
    return selected_model.strip(), top_k, threshold, model_status


selected_model, top_k, evidence_threshold, model_status = render_sidebar()
index = get_index()
documents = index.list_documents()
total_pages = sum(int(document["page_count"]) for document in documents)

st.markdown('<div class="eyebrow">Your evidence-first research workspace</div>', unsafe_allow_html=True)
st.title("Research with receipts.")
st.markdown(
    '<div class="hero-copy">Ask questions across your PDFs. TrustRAG retrieves the '
    'supporting passages, cites the source pages, and abstains when evidence is weak.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="trust-banner"><strong>Evidence before answers.</strong> '
    'Every generated response is paired with inspectable passages. '
    'The local model can still make mistakes—verify important claims against the sources.</div>',
    unsafe_allow_html=True,
)

metric_columns = st.columns(3)
metric_columns[0].metric("Documents indexed", len(documents))
metric_columns[1].metric("Pages in library", total_pages)
metric_columns[2].metric(
    "Local answer model",
    model_status,
)

ask_tab, library_tab, guide_tab = st.tabs(
    ["Ask your documents", "Document library", "How TrustRAG works"]
)

with ask_tab:
    st.subheader("What would you like to research?")
    st.caption("Answers are limited to relevant evidence found in the documents below.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("citations"):
                st.caption(
                    "Sources: "
                    + " · ".join(
                        f"{item['source']} · p. {item['page']}"
                        for item in message["citations"]
                    )
                )
                with st.expander("Inspect supporting evidence"):
                    render_evidence(message["evidence"])

    prompt = st.chat_input(
        "Ask a question about your documents…",
        disabled=not documents,
    )
    if not documents:
        st.info("Add a text-based PDF in the Document library tab to begin.")
    elif prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Finding and checking relevant passages…"):
                try:
                    retrieved = index.search(prompt, top_k=top_k)
                    result = answer_with_local_model(
                        prompt,
                        retrieved,
                        model=selected_model or DEFAULT_OLLAMA_MODEL,
                        evidence_threshold=evidence_threshold,
                    )
                    st.markdown(result["answer"])
                    if result["supported"]:
                        citations = result["citations"]
                        st.caption(
                            "Cited sources: "
                            + " · ".join(
                                f"{item['source']} · p. {item['page']}"
                                for item in citations
                            )
                        )
                    elif result["answer"] == ABSTENTION:
                        st.warning(result["answer"])
                    else:
                        st.error(result["answer"])
                    with st.expander("Inspect retrieved evidence"):
                        render_evidence(result["evidence"])
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": result["answer"],
                        "citations": result["citations"],
                        "evidence": result["evidence"],
                    })
                except LocalModelError as error:
                    st.error(str(error))
                except RuntimeError as error:
                    st.error(f"TrustRAG could not complete this request: {error}")

with library_tab:
    st.subheader("Your document library")
    st.caption("PDFs are processed in memory. TrustRAG keeps indexed text and vectors locally.")
    uploaded_files = st.file_uploader(
        "Add research PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        help="Text-based PDFs up to 20 MB each. Scanned documents need OCR first.",
    )
    if st.button(
        "Index selected PDFs",
        type="primary",
        disabled=not uploaded_files,
        use_container_width=False,
    ):
        for uploaded_file in uploaded_files or []:
            if uploaded_file.size > MAX_UPLOAD_BYTES:
                st.error(f"{uploaded_file.name} exceeds the 20 MB upload limit.")
                continue
            try:
                with st.spinner(f"Extracting and indexing {uploaded_file.name}…"):
                    record = index.add_pdf(
                        Path(uploaded_file.name).name,
                        uploaded_file.getvalue(),
                    )
                st.success(
                    f"Indexed {record['filename']}: {record['page_count']} pages, "
                    f"{record['chunk_count']} searchable passages."
                )
            except InvalidDocumentError as error:
                st.error(f"{uploaded_file.name}: {error}")
            except RuntimeError as error:
                st.error(f"Could not index {uploaded_file.name}: {error}")
        st.rerun()

    if documents:
        st.markdown("#### Indexed sources")
        for document in documents:
            with st.container(border=True):
                detail_columns = st.columns([5, 1.2, 1.2, 1])
                detail_columns[0].markdown(f"**{document['filename']}**")
                detail_columns[0].caption(
                    f"Added {str(document['uploaded_at'])[:10]}"
                )
                detail_columns[1].metric("Pages", document["page_count"])
                detail_columns[2].metric("Passages", document["chunk_count"])
                if detail_columns[3].button(
                    "Remove",
                    key=f"delete_{document['id']}",
                    help="Remove this document and its indexed passages",
                ):
                    index.delete_document(str(document["id"]))
                    st.session_state.messages = []
                    st.rerun()
    else:
        st.info("Your library is empty. Upload a text-based PDF to get started.")

with guide_tab:
    st.subheader("How TrustRAG earns your trust")
    guide_columns = st.columns(3)
    guide_columns[0].markdown(
        "#### 01 · Read\n\nPDF pages are extracted and split into overlapping "
        "passages without losing their original page references."
    )
    guide_columns[1].markdown(
        "#### 02 · Retrieve\n\nA local embedding model finds semantically relevant "
        "passages, even when your wording differs from the source."
    )
    guide_columns[2].markdown(
        "#### 03 · Verify\n\nA local Ollama model drafts a cited response. "
        "Weak evidence triggers an explicit abstention instead."
    )
    st.warning(
        "Citation checks confirm that citations refer to retrieved passages; "
        "they cannot prove every generated claim is entailed by that passage. "
        "Inspect the evidence before relying on consequential answers."
    )
    st.markdown("#### Local model setup")
    st.code("ollama pull llama3.2:3b", language="powershell")
    st.markdown(
        "Install Ollama separately, start it, then refresh TrustRAG. The model "
        "runs on your computer; first-time embedding model use may also need "
        "internet access to download its files."
    )
