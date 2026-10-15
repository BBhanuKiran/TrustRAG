const API = "";
const views = [...document.querySelectorAll(".view")];
const navButtons = [...document.querySelectorAll("[data-view]")];
const authCard = document.getElementById("auth-card");
const authForm = document.getElementById("auth-form");
const authFeedback = document.getElementById("auth-feedback");
const authSubmit = document.getElementById("auth-submit");
const questionInput = document.getElementById("question-input");
const researchMessages = document.getElementById("research-messages");
const supportMessages = document.getElementById("support-messages");
let account = null;
let authMode = "login";
let conversation = [];

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    credentials: "same-origin",
    ...options,
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string"
      ? payload.detail
      : `Request failed (${response.status}).`;
    throw new Error(detail);
  }
  return payload;
}

function showNotice(message, kind = "") {
  const notice = document.getElementById("global-notice");
  notice.textContent = message;
  notice.className = `notice ${kind}`;
  notice.hidden = !message;
}

function showView(name) {
  if ((name === "documents" || name === "workspace") && !account) {
    authCard.hidden = false;
    document.getElementById("signed-out-hint").hidden = false;
    name = "workspace";
    showNotice("Sign in or create an account to open your private document workspace.");
  } else {
    showNotice("");
  }

  for (const view of views) {
    view.classList.toggle("active", view.id === `${name}-view`);
  }
  for (const button of document.querySelectorAll(".nav-link[data-view]")) {
    button.classList.toggle("active", button.dataset.view === name);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

for (const button of navButtons) {
  button.addEventListener("click", () => showView(button.dataset.view));
}

function addMessage(container, text, role, details = null) {
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "Y" : container === supportMessages ? "?" : "T";

  const body = document.createElement("div");
  body.className = "message-body";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.append(paragraph);

  if (details?.citations?.length) {
    const sources = document.createElement("div");
    sources.className = "source-line";
    sources.append(document.createTextNode("Cited sources: "));
    for (const [index, item] of details.citations.entries()) {
      if (index) sources.append(document.createTextNode(" · "));
      const label = `${item.source}${item.page ? ` · p. ${item.page}` : ""}`;
      if (item.url) {
        const link = document.createElement("a");
        link.href = item.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = label;
        sources.append(link);
      } else {
        sources.append(document.createTextNode(label));
      }
    }
    body.append(sources);
  }
  if (details?.web_search_included) {
    const searchNote = document.createElement("small");
    searchNote.className = "web-search-note";
    searchNote.textContent = `Fresh web search included · ${details.web_sources_count} source${details.web_sources_count === 1 ? "" : "s"} retrieved`;
    body.append(searchNote);
  }
  if (details?.evidence?.length) {
    const evidenceList = document.createElement("div");
    evidenceList.className = "evidence-list";
    const summary = document.createElement("b");
    summary.textContent = `Inspect retrieved evidence (${details.evidence.length})`;
    evidenceList.append(summary);
    for (const [index, item] of details.evidence.entries()) {
      const card = document.createElement("article");
      card.className = "evidence-card";
      const meta = document.createElement("b");
      const location = item.page ? ` · Page ${item.page}` : "";
      meta.textContent = `[E${index + 1}] ${item.source}${location} · Relevance ${Math.round(Number(item.score) * 100)}%`;
      const excerpt = document.createElement("p");
      excerpt.textContent = item.text;
      card.append(meta, excerpt);
      if (item.url) {
        const link = document.createElement("a");
        link.href = item.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "Open original source";
        card.append(link);
      }
      evidenceList.append(card);
    }
    body.append(evidenceList);
  }

  article.append(avatar, body);
  container.append(article);
  container.scrollTop = container.scrollHeight;
  return article;
}

function updateAuthenticationView() {
  const signedIn = Boolean(account);
  document.getElementById("user-email").hidden = !signedIn;
  document.getElementById("user-email").textContent = account?.email ?? "";
  document.getElementById("logout-button").hidden = !signedIn;
  document.getElementById("delete-account").hidden = !signedIn;
  document.getElementById("auth-open").hidden = signedIn;
  document.getElementById("auth-card").hidden = signedIn;
  document.getElementById("signed-out-hint").hidden = signedIn;
  document.getElementById("workspace-panel").hidden = !signedIn;
  document.getElementById("library-signin").hidden = signedIn;
  document.getElementById("library-content").hidden = !signedIn;
  document.getElementById("question-input").disabled = !signedIn;
  if (signedIn) {
    document.getElementById("library-signin").hidden = true;
  }
}

function setAuthMode(mode) {
  authMode = mode;
  const signingUp = mode === "register";
  document.getElementById("auth-title").textContent = signingUp
    ? "Create your private workspace"
    : "Sign in to start researching";
  document.getElementById("auth-description").textContent = signingUp
    ? "Choose a strong password. Your document library is private to your account."
    : "Sign in to access your own documents, evidence, and research.";
  document.getElementById("auth-password").autocomplete = signingUp
    ? "new-password"
    : "current-password";
  document.getElementById("auth-password").minLength = signingUp ? 12 : 1;
  document.getElementById("auth-submit").textContent = signingUp
    ? "Create account"
    : "Sign in securely";
  document.getElementById("auth-mode-toggle").textContent = signingUp
    ? "Already have an account? Sign in"
    : "New to TrustRAG? Create an account";
  authFeedback.textContent = signingUp
    ? "Passwords must be at least 12 characters."
    : "";
}

function openAuth(mode = "login") {
  setAuthMode(mode);
  authCard.hidden = false;
  document.getElementById("signed-out-hint").hidden = false;
  document.getElementById("auth-email").focus();
  document.getElementById("auth-card").scrollIntoView({ behavior: "smooth", block: "center" });
}

document.getElementById("auth-open").addEventListener("click", () => openAuth());
document.getElementById("hero-signup").addEventListener("click", () => openAuth("register"));
document.getElementById("hint-signup").addEventListener("click", () => openAuth("register"));
document.querySelectorAll("[data-open-auth]").forEach((button) => {
  button.addEventListener("click", () => openAuth());
});
document.getElementById("auth-mode-toggle").addEventListener("click", () => {
  setAuthMode(authMode === "login" ? "register" : "login");
});

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authFeedback.textContent = "";
  authSubmit.disabled = true;
  const payload = {
    email: document.getElementById("auth-email").value.trim(),
    password: document.getElementById("auth-password").value,
  };
  try {
    const result = await api(`/api/auth/${authMode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    account = result.user;
    document.getElementById("auth-password").value = "";
    updateAuthenticationView();
    await refreshLibrary();
    showView("workspace");
    showNotice(`Welcome${account.email ? `, ${account.email}` : ""}. Your private workspace is ready.`, "success");
  } catch (error) {
    authFeedback.textContent = error.message;
  } finally {
    authSubmit.disabled = false;
  }
});

document.getElementById("logout-button").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch {
    // The local state is cleared even if the logout request cannot reach the server.
  }
  account = null;
  conversation = [];
  researchMessages.replaceChildren();
  addMessage(
    researchMessages,
    "Welcome. Add a PDF to your library, then ask a specific question about what it says. I’ll show the source and page so you can check my work.",
    "assistant",
  );
  updateAuthenticationView();
  showView("workspace");
  showNotice("You have been signed out.");
});

document.getElementById("delete-account").addEventListener("click", async () => {
  if (!account) return;
  const confirmed = window.confirm(
    `Permanently delete ${account.email}, all active sessions, and every indexed document? This cannot be undone.`,
  );
  if (!confirmed) return;
  const button = document.getElementById("delete-account");
  button.disabled = true;
  try {
    await api("/api/auth/me", { method: "DELETE" });
    account = null;
    conversation = [];
    researchMessages.replaceChildren();
    addMessage(
      researchMessages,
      "Welcome. Add a PDF to your library, then ask a specific question about what it says. I’ll show the source and page so you can check my work.",
      "assistant",
    );
    updateAuthenticationView();
    showView("workspace");
    showNotice("Your account, sessions, and indexed documents were deleted.", "success");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

async function refreshLibrary() {
  if (!account) return;
  const list = document.getElementById("document-list");
  list.replaceChildren();
  try {
    const documents = await api("/documents");
    const totalPages = documents.reduce((sum, document) => sum + Number(document.page_count), 0);
    document.getElementById("document-count").textContent = String(documents.length);
    document.getElementById("page-count").textContent = String(totalPages);
    document.getElementById("library-count").textContent = `${documents.length} source${documents.length === 1 ? "" : "s"}`;
    document.getElementById("library-empty").hidden = documents.length > 0;
    for (const sourceRecord of documents) {
      const row = document.createElement("article");
      row.className = "document-row";
      const icon = document.createElement("div");
      icon.className = "document-icon";
      icon.textContent = String(sourceRecord.source_type || "source").toUpperCase().slice(0, 4);
      const info = document.createElement("div");
      info.className = "document-info";
      const name = document.createElement("b");
      name.textContent = sourceRecord.filename;
      const details = document.createElement("small");
      const pageSummary = Number(sourceRecord.page_count) > 0
        ? `${sourceRecord.page_count} pages · `
        : "";
      details.textContent = `${String(sourceRecord.source_type || "source").toUpperCase()} · ${pageSummary}${sourceRecord.chunk_count} passages · Added ${String(sourceRecord.uploaded_at).slice(0, 10)}`;
      info.append(name, details);
      if (sourceRecord.source_url) {
        const original = document.createElement("a");
        original.href = sourceRecord.source_url;
        original.target = "_blank";
        original.rel = "noopener noreferrer";
        original.textContent = "Open original link";
        info.append(original);
      }
      const ask = document.createElement("button");
      ask.className = "button button-secondary";
      ask.type = "button";
      ask.textContent = "Ask about sources";
      ask.addEventListener("click", () => {
        showView("workspace");
        questionInput.focus();
      });
      const remove = document.createElement("button");
      remove.className = "button button-quiet";
      remove.type = "button";
      remove.textContent = "Delete";
      remove.setAttribute("aria-label", `Delete ${sourceRecord.filename}`);
      remove.addEventListener("click", async () => {
        if (!window.confirm(`Delete "${sourceRecord.filename}" and its indexed passages?`)) return;
        remove.disabled = true;
        try {
          await api(`/documents/${encodeURIComponent(sourceRecord.id)}`, { method: "DELETE" });
          showNotice("Source and indexed passages deleted.", "success");
          await refreshLibrary();
        } catch (error) {
          showNotice(error.message, "error");
          remove.disabled = false;
        }
      });
      row.append(icon, info, ask, remove);
      list.append(row);
    }
    filterLibrary();
  } catch (error) {
    showNotice(error.message, "error");
  }
}

function filterLibrary() {
  const query = document.getElementById("library-search").value.trim().toLowerCase();
  for (const row of document.querySelectorAll(".document-row")) {
    row.hidden = !row.querySelector(".document-info b").textContent.toLowerCase().includes(query);
  }
}

document.getElementById("library-search").addEventListener("input", filterLibrary);
document.getElementById("source-files").addEventListener("change", (event) => {
  const files = [...event.target.files];
  document.getElementById("selected-files").textContent = files.length
    ? files.map((file) => `${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`).join(" · ")
    : "No files selected";
  document.getElementById("upload-submit").disabled = files.length === 0;
});

document.getElementById("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = [...document.getElementById("source-files").files];
  const submit = document.getElementById("upload-submit");
  const feedback = document.getElementById("upload-feedback");
  if (!files.length) return;
  submit.disabled = true;
  let completed = 0;
  const failures = [];
  for (const file of files) {
    if (file.size > 20 * 1024 * 1024) {
      failures.push(`${file.name}: exceeds the 20 MB limit.`);
      continue;
    }
    const form = new FormData();
    form.append("file", file);
    feedback.textContent = `Indexing ${file.name}…`;
    try {
      const document = await api("/documents", { method: "POST", body: form });
      completed += 1;
      showNotice(`Indexed ${document.filename}: ${document.page_count} pages and ${document.chunk_count} passages.`, "success");
    } catch (error) {
      failures.push(`${file.name}: ${error.message}`);
    }
  }
  document.getElementById("source-files").value = "";
  document.getElementById("selected-files").textContent = "No files selected";
  feedback.textContent = failures.join(" ");
  feedback.style.color = failures.length ? "#a83c38" : "var(--accent-strong)";
  submit.textContent = failures.length ? "Upload completed with errors" : "Upload and index";
  submit.disabled = false;
  if (completed) await refreshLibrary();
});

document.getElementById("url-source-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const feedback = document.getElementById("url-feedback");
  button.disabled = true;
  feedback.textContent = "Fetching and indexing the linked source…";
  try {
    const source = await api("/sources/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: document.getElementById("source-url").value.trim() }),
    });
    feedback.textContent = `Indexed ${source.filename} (${source.chunk_count} passages).`;
    form.reset();
    await refreshLibrary();
  } catch (error) {
    feedback.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.getElementById("text-source-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const feedback = document.getElementById("text-feedback");
  button.disabled = true;
  feedback.textContent = "Saving and indexing your text…";
  try {
    const source = await api("/sources/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: document.getElementById("source-title").value.trim() || "Pasted notes",
        text: document.getElementById("source-text").value,
      }),
    });
    feedback.textContent = `Indexed ${source.filename} (${source.chunk_count} passages).`;
    form.reset();
    await refreshLibrary();
  } catch (error) {
    feedback.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function submitQuestion(question) {
  const trimmed = question.trim();
  if (!trimmed || !account) return;
  addMessage(researchMessages, trimmed, "user");
  conversation.push({ role: "user", content: trimmed });
  const includeWebSearch = document.getElementById("include-web-search").checked;
  const pending = addMessage(
    researchMessages,
    includeWebSearch
      ? "Searching your private sources and the web for current evidence…"
      : "Searching your private sources and checking citations…",
    "assistant",
  );
  const formButton = document.querySelector("#question-form button[type='submit']");
  if (formButton) formButton.disabled = true;
  try {
    const result = await api("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: trimmed, top_k: 5, include_web: includeWebSearch }),
    });
    pending.remove();
    addMessage(researchMessages, result.answer, "assistant", result);
    conversation.push({ role: "assistant", content: result.answer, citations: result.citations ?? [] });
  } catch (error) {
    pending.remove();
    addMessage(researchMessages, error.message, "assistant");
  } finally {
    if (formButton) formButton.disabled = false;
    questionInput.value = "";
  }
}

document.getElementById("question-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitQuestion(questionInput.value);
});
document.querySelectorAll(".suggestion[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.dataset.question;
    showView("workspace");
    questionInput.focus();
  });
});

document.getElementById("export-chat").addEventListener("click", () => {
  if (!conversation.length) {
    showNotice("Ask a research question before exporting a conversation.");
    return;
  }
  const markdown = [
    "# TrustRAG research conversation",
    "",
    `Exported ${new Date().toLocaleString()}`,
    "",
    ...conversation.flatMap((message) => [
      `## ${message.role === "user" ? "Question" : "TrustRAG answer"}`,
      "",
      message.content,
      ...(message.citations?.length
        ? ["", `Sources: ${message.citations.map((item) => `${item.source}, page ${item.page}`).join("; ")}`]
        : []),
      "",
    ]),
    "> Verify important claims against the original cited document pages.",
  ].join("\n");
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "trustrag-research.md";
  link.click();
  URL.revokeObjectURL(url);
});

async function submitSupportQuestion(query) {
  const trimmed = query.trim();
  if (!trimmed) return;
  addMessage(supportMessages, trimmed, "user");
  const pending = addMessage(supportMessages, "Checking the TrustRAG manual…", "assistant");
  try {
    const result = await api("/api/support", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: trimmed }),
    });
    pending.remove();
    const reply = addMessage(supportMessages, result.answer, "assistant");
    const section = document.createElement("div");
    section.className = "source-line";
    section.textContent = result.supported
      ? `TrustRAG User Manual · ${result.section}`
      : "Manual search · no reliable matching section";
    reply.querySelector(".message-body").append(section);
  } catch (error) {
    pending.remove();
    addMessage(supportMessages, error.message, "assistant");
  }
}

document.getElementById("support-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("support-input");
  submitSupportQuestion(input.value);
  input.value = "";
});
document.querySelectorAll(".support-suggestion").forEach((button) => {
  button.addEventListener("click", () => submitSupportQuestion(button.textContent.replace("↗", "").trim()));
});

const themeToggle = document.getElementById("theme-toggle");
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("trustrag-theme", theme);
  themeToggle.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
}
setTheme(localStorage.getItem("trustrag-theme") === "dark" ? "dark" : "light");
themeToggle.addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

async function initialize() {
  setAuthMode("login");
  try {
    const status = await api("/api/status");
    const configured = Boolean(status.answer_service_configured);
    document.getElementById("answer-service-status").textContent = configured
      ? "Ready"
      : "Admin setup needed";
  } catch {
    document.getElementById("answer-service-status").textContent = "Check connection";
  }
  try {
    const result = await api("/api/auth/me");
    account = result.user;
    updateAuthenticationView();
    await refreshLibrary();
  } catch {
    account = null;
    updateAuthenticationView();
  }
}

initialize();
