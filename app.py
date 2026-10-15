import logging
import os
import re
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from dotenv import load_dotenv

from answering import (
    DEFAULT_EVIDENCE_THRESHOLD,
    LocalModelError,
    answer_with_hosted_model,
    answer_with_local_model,
)
from auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    AccountExistsError,
    AuthRateLimiter,
    AuthStore,
    AuthenticationError,
)
from rag_engine import (
    MAX_INDEXED_DOCUMENTS_PER_USER,
    DocumentLimitError,
    EmbeddingModelError,
    EvidenceIndex,
    InvalidDocumentError,
)
from support import find_support_answer
from web_sources import WebSourceError, fetch_public_url, html_to_text, search_recent_web


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env", override=False)

DATA_DIR = Path(os.getenv("TRUSTRAG_DATA_DIR", str(ROOT_DIR / "data")))
DATABASE_PATH = Path(
    os.getenv("TRUSTRAG_DATABASE_PATH", str(DATA_DIR / "trustrag.sqlite3"))
)
WEB_DIR = ROOT_DIR / "web"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

app = FastAPI(
    title="TrustRAG",
    description=(
        "Private, account-isolated research across files, links, text, images, "
        "and current web search, with evidence citations."
    ),
    version="1.0.0",
)
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

_index: EvidenceIndex | None = None
_auth_store: AuthStore | None = None
_auth_rate_limiter = AuthRateLimiter()
_api_rate_limiter = AuthRateLimiter(attempts=30, window_seconds=60)
_logger = logging.getLogger("trustrag")


def get_index() -> EvidenceIndex:
    global _index

    if _index is None:
        _index = EvidenceIndex(DATABASE_PATH)
    return _index


def get_auth_store() -> AuthStore:
    global _auth_store

    if _auth_store is None:
        secret_key = os.getenv("TRUSTRAG_SECRET_KEY")
        if os.getenv("TRUSTRAG_ENV", "development").casefold() == "production":
            if not secret_key or len(secret_key) < 32:
                raise RuntimeError(
                    "Production requires TRUSTRAG_SECRET_KEY with at least 32 characters."
                )
        else:
            _logger.warning(
                "TRUSTRAG_SECRET_KEY is unset; sessions will be invalidated on restart."
            )
        _auth_store = AuthStore(DATABASE_PATH, secret_key=secret_key)
    return _auth_store


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_auth_rate_limit(request: Request, action: str) -> None:
    key = f"{action}:{_client_address(request)}"
    if not _auth_rate_limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Too many account attempts. Wait a few minutes and try again.",
            headers={"Retry-After": "900"},
        )


def _check_user_rate_limit(user_id: str, action: str) -> None:
    if not _api_rate_limiter.allow(f"{action}:{user_id}"):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Wait a minute and try again.",
            headers={"Retry-After": "60"},
        )


def _valid_email(email: str) -> bool:
    return bool(re.fullmatch(
        r"(?=.{3,254}$)[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
        email.strip(),
    ))


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=get_auth_store().create_session(user_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=os.getenv("TRUSTRAG_ENV", "development").casefold() == "production",
        samesite="strict",
        path="/",
    )


def require_user(request: Request) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")

    user = get_auth_store().get_user_from_session(token)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Your session expired. Please sign in again.",
        )
    return user


CurrentUser = Annotated[dict[str, str], Depends(require_user)]


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class LoginCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class QuestionRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=8)


class AskRequest(QuestionRequest):
    evidence_threshold: float = Field(
        default=DEFAULT_EVIDENCE_THRESHOLD,
        ge=0,
        le=1,
    )
    include_web: bool = True


class SourceTextRequest(BaseModel):
    title: str = Field(default="Pasted notes", min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=1_000_000)


class SourceURLRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class SupportRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


@app.get("/", include_in_schema=False)
def product_website() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/robots.txt", include_in_schema=False)
def robots_txt() -> FileResponse:
    return FileResponse(WEB_DIR / "robots.txt", media_type="text/plain")


@app.middleware("http")
async def set_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if os.getenv("TRUSTRAG_ENV", "development").casefold() == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    if request.url.path.startswith("/api/") or request.url.path in {
        "/documents",
        "/search",
        "/ask",
        "/models",
    }:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def public_status() -> dict[str, object]:
    hosted_configured = bool(os.getenv("TRUSTRAG_LLM_API_KEY"))
    development_mode = (
        os.getenv("TRUSTRAG_ENV", "development").casefold() != "production"
    )
    using_hosted_provider = hosted_configured or not development_mode
    return {
        "status": "ok",
        "answer_service_configured": (
            hosted_configured
            if using_hosted_provider
            else True
        ),
        "answer_provider": (
            "hosted"
            if using_hosted_provider
            else "local Ollama"
        ),
        "answer_model": (
            os.getenv("TRUSTRAG_LLM_MODEL", "gpt-4o-mini")
            if using_hosted_provider
            else os.getenv("TRUSTRAG_OLLAMA_MODEL", "llama3.2:3b")
        ),
    }


@app.post("/api/auth/register", status_code=201)
def register_account(
    credentials: Credentials,
    request: Request,
    response: Response,
) -> dict[str, object]:
    _check_auth_rate_limit(request, "register")
    if not _valid_email(credentials.email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    try:
        user = get_auth_store().register(
            str(credentials.email),
            credentials.password,
        )
    except AccountExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    _set_session_cookie(response, user["id"])
    return {"user": {"id": user["id"], "email": user["email"]}}


@app.post("/api/auth/login")
def login_account(
    credentials: LoginCredentials,
    request: Request,
    response: Response,
) -> dict[str, object]:
    _check_auth_rate_limit(request, "login")
    if not _valid_email(credentials.email):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    try:
        user = get_auth_store().authenticate(
            str(credentials.email),
            credentials.password,
        )
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error

    _set_session_cookie(response, user["id"])
    return {"user": {"id": user["id"], "email": user["email"]}}


@app.get("/api/auth/me")
def current_account(user: CurrentUser) -> dict[str, object]:
    return {"user": {"id": user["id"], "email": user["email"]}}


@app.delete("/api/auth/me", status_code=204)
def delete_account(user: CurrentUser, response: Response) -> None:
    if not get_auth_store().delete_account(user["id"]):
        raise HTTPException(status_code=404, detail="Account not found.")
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=os.getenv("TRUSTRAG_ENV", "development").casefold() == "production",
        samesite="strict",
        path="/",
    )


@app.post("/api/auth/logout", status_code=204)
def logout_account(request: Request, response: Response) -> None:
    get_auth_store().revoke_session(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=os.getenv("TRUSTRAG_ENV", "development").casefold() == "production",
        samesite="strict",
        path="/",
    )


@app.post("/api/support")
def help_center(request: SupportRequest) -> dict[str, object]:
    return find_support_answer(request.query)


@app.get("/models")
def list_answer_configuration(user: CurrentUser) -> dict[str, object]:
    del user
    return {
        "provider": (
            "OpenAI-compatible API"
            if os.getenv("TRUSTRAG_LLM_API_KEY")
            else "Local Ollama"
        ),
        "model": (
            os.getenv("TRUSTRAG_LLM_MODEL", "gpt-4o-mini")
            if os.getenv("TRUSTRAG_LLM_API_KEY")
            else os.getenv("TRUSTRAG_OLLAMA_MODEL", "llama3.2:3b")
        ),
        "configured": bool(os.getenv("TRUSTRAG_LLM_API_KEY")),
    }


@app.post("/documents", status_code=201)
async def upload_document(
    file: Annotated[
        UploadFile,
        File(description="A PDF, text file, or image source to index"),
    ],
    user: CurrentUser,
) -> dict[str, object]:
    _check_user_rate_limit(user["id"], "upload")
    try:
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        supported_text = {".txt", ".md", ".csv", ".html", ".htm"}
        supported_images = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
        if suffix != ".pdf" and suffix not in supported_text | supported_images:
            raise HTTPException(
                status_code=415,
                detail=(
                    "Supported files are PDFs, TXT, Markdown, CSV, HTML, PNG, "
                    "JPEG, WEBP, and TIFF images."
                ),
            )

        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "File exceeds the "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."
                ),
            )

        _check_document_capacity(user["id"])
        if suffix == ".pdf":
            return await run_in_threadpool(
                get_index().add_pdf,
                filename,
                content,
                user["id"],
            )
        if suffix in supported_images:
            return await run_in_threadpool(
                get_index().add_image,
                filename,
                content,
                user["id"],
            )
        text = content.decode("utf-8-sig", errors="replace")
        if suffix in {".html", ".htm"}:
            text, title = html_to_text(text)
            filename = title[:200] or filename
        return await run_in_threadpool(
            get_index().add_text,
            filename,
            text,
            user["id"],
        )
    except InvalidDocumentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except DocumentLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except EmbeddingModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    finally:
        await file.close()


@app.post("/sources/text", status_code=201)
def add_pasted_text(
    request: SourceTextRequest,
    user: CurrentUser,
) -> dict[str, object]:
    _check_user_rate_limit(user["id"], "upload")
    _check_document_capacity(user["id"])
    try:
        return get_index().add_text(
            request.title.strip() or "Pasted notes",
            request.text,
            user["id"],
        )
    except DocumentLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except InvalidDocumentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except EmbeddingModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/sources/url", status_code=201)
def add_url_source(
    request: SourceURLRequest,
    user: CurrentUser,
) -> dict[str, object]:
    _check_user_rate_limit(user["id"], "upload")
    _check_document_capacity(user["id"])
    try:
        fetched = fetch_public_url(request.url)
        content = fetched.content
        content_type = fetched.content_type
        source_url = fetched.final_url
        path_name = Path(urlsplit(source_url).path).name
        if content_type == "application/pdf":
            filename = path_name or "linked-document.pdf"
            return get_index().add_pdf(
                filename,
                content,
                user["id"],
                source_type="link",
                source_url=source_url,
            )
        if content_type in {"text/html", "application/xhtml+xml"}:
            html = content.decode(fetched.encoding, errors="replace")
            text, title = html_to_text(html)
            filename = title[:200] or path_name or urlsplit(source_url).hostname or "Web page"
            return get_index().add_text(
                filename,
                text,
                user["id"],
                source_type="link",
                source_url=source_url,
            )
        if content_type.startswith("text/"):
            filename = path_name or "linked-text.txt"
            text = content.decode(fetched.encoding, errors="replace")
            return get_index().add_text(
                filename,
                text,
                user["id"],
                source_type="link",
                source_url=source_url,
            )
        if content_type.startswith("image/"):
            filename = path_name or f"linked-image.{content_type.split('/', 1)[1]}"
            return get_index().add_image(
                filename,
                content,
                user["id"],
                source_type="link",
                source_url=source_url,
            )
        raise HTTPException(
            status_code=415,
            detail=(
                "That link is not a supported PDF, web page, text file, or image."
            ),
        )
    except WebSourceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except InvalidDocumentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except DocumentLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except EmbeddingModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _check_document_capacity(user_id: str) -> None:
    if get_index().count_documents(user_id) >= MAX_INDEXED_DOCUMENTS_PER_USER:
        raise HTTPException(
            status_code=413,
            detail=(
                "This account has reached the "
                f"{MAX_INDEXED_DOCUMENTS_PER_USER}-source limit."
            ),
        )


@app.get("/documents")
def list_documents(user: CurrentUser) -> list[dict[str, object]]:
    return get_index().list_documents(user["id"])


@app.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, user: CurrentUser) -> None:
    if not get_index().delete_document(document_id, user["id"]):
        raise HTTPException(status_code=404, detail="Document not found.")


@app.post("/search")
def search_evidence(
    request: QuestionRequest,
    user: CurrentUser,
) -> dict[str, object]:
    try:
        evidence = get_index().search(
            request.query,
            top_k=request.top_k,
            user_id=user["id"],
        )
    except EmbeddingModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {
        "query": request.query,
        "evidence": evidence,
        "has_evidence": bool(evidence),
    }


@app.post("/ask")
def ask_question(
    request: AskRequest,
    user: CurrentUser,
) -> dict[str, object]:
    _check_user_rate_limit(user["id"], "ask")
    try:
        evidence = get_index().search(
            request.query,
            top_k=request.top_k,
            user_id=user["id"],
        )
        web_result_count = 0
        if request.include_web:
            web_results = search_recent_web(request.query, limit=3)
            ranked_web_results = get_index().rank_sources(
                request.query,
                web_results,
                top_k=3,
            )
            web_result_count = len(ranked_web_results)
            evidence.extend(ranked_web_results)
        if (
            os.getenv("TRUSTRAG_LLM_API_KEY")
            or os.getenv("TRUSTRAG_ENV", "development").casefold() == "production"
        ):
            result = answer_with_hosted_model(
                request.query,
                evidence,
                evidence_threshold=request.evidence_threshold,
            )
        else:
            result = answer_with_local_model(
                request.query,
                evidence,
                evidence_threshold=request.evidence_threshold,
            )
    except LocalModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except WebSourceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except EmbeddingModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {
        "query": request.query,
        "web_search_included": request.include_web,
        "web_sources_count": web_result_count,
        **result,
    }
