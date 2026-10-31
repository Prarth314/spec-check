import hashlib
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import pdfplumber
from starlette.concurrency import run_in_threadpool
from . import store
from .extraction import extract_pdf
from .retrieval import search
from .answering import answer
from .browser_api import router as browser_router
from .runtime import browser_storage

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(app):
    if not browser_storage():
        store.initialize()
    yield


app = FastAPI(title="Spec Check", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(browser_router)


def require_local_storage():
    if browser_storage():
        raise HTTPException(409, "This deployment uses a browser-owned library. Use the /api/browser endpoints.")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_configured": bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")),
            "model": os.getenv("OPENAI_MODEL") or None,
            "storage": "browser" if browser_storage() else "local",
            "max_upload_bytes": 4 * 1024 * 1024 if browser_storage() else MAX_BYTES}


@app.get("/api/documents")
def documents():
    require_local_storage()
    with store.connect() as db:
        rows = [dict(r) for r in db.execute("SELECT id,name,sha256,pages,chunks,warnings,created_at FROM documents ORDER BY created_at,id")]
    for row in rows:
        row["warnings"] = json.loads(row["warnings"])
    return rows


def ingest(content, filename, reindex=False):
    digest = hashlib.sha256(content).hexdigest()
    with store.connect() as db:
        existing = db.execute("SELECT id FROM documents WHERE sha256=?", (digest,)).fetchone()
    if existing and not reindex:
        return {"id": existing["id"], "duplicate": True}
    try:
        pages, chunks, warnings = extract_pdf(content)
    except Exception as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else "Unable to read this PDF. Check that it is valid and not password protected.") from exc
    if existing:
        doc_id = existing["id"]
        with store.connect() as db:
            db.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
            db.executemany("INSERT INTO chunks(document_id,page,kind,text) VALUES(?,?,?,?)",
                           [(doc_id, c["page"], c["kind"], c["text"]) for c in chunks])
            db.execute("UPDATE documents SET pages=?,chunks=?,warnings=? WHERE id=?",
                       (pages, len(chunks), json.dumps(warnings), doc_id))
        return {"id": doc_id, "pages": pages, "chunks": len(chunks), "warnings": warnings, "duplicate": False, "reindexed": True}
    doc_id = uuid.uuid4().hex
    path = store.data_dir() / "pdfs" / f"{doc_id}.pdf"
    path.write_bytes(content)
    try:
        with store.connect() as db:
            db.execute("INSERT INTO documents(id,name,sha256,pages,chunks,warnings) VALUES(?,?,?,?,?,?)",
                       (doc_id, filename, digest, pages, len(chunks), json.dumps(warnings)))
            db.executemany("INSERT INTO chunks(document_id,page,kind,text) VALUES(?,?,?,?)",
                           [(doc_id, c["page"], c["kind"], c["text"]) for c in chunks])
    except Exception:
        path.unlink(missing_ok=True)
        # A simultaneous duplicate upload may have won the unique constraint.
        with store.connect() as db:
            existing = db.execute("SELECT id FROM documents WHERE sha256=?", (digest,)).fetchone()
        if existing:
            return {"id": existing["id"], "duplicate": True}
        raise
    return {"id": doc_id, "pages": pages, "chunks": len(chunks), "warnings": warnings, "duplicate": False}


@app.post("/api/documents", status_code=201)
async def upload(file: UploadFile = File(...)):
    require_local_storage()
    content = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "PDF exceeds the 20 MB upload limit.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(415, "Please upload a valid PDF file.")
    name = (file.filename or "datasheet.pdf").replace("\\", "/").split("/")[-1][:180]
    return await run_in_threadpool(ingest, content, name)


@app.get("/api/documents/{doc_id}/pdf")
def pdf(doc_id: str):
    require_local_storage()
    with store.connect() as db:
        doc = db.execute("SELECT name FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        raise HTTPException(404, "Datasheet not found")
    return FileResponse(store.data_dir() / "pdfs" / f"{doc_id}.pdf", media_type="application/pdf",
                        filename=doc["name"], content_disposition_type="inline")


@app.delete("/api/documents/{doc_id}")
def delete(doc_id: str):
    require_local_storage()
    with store.connect() as db:
        result = db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        if not result.rowcount:
            raise HTTPException(404, "Datasheet not found")
    (store.data_dir() / "pdfs" / f"{doc_id}.pdf").unlink(missing_ok=True)
    return {"deleted": True}


@app.get("/api/documents/{doc_id}/pages/{page_number}.png")
def source_page(doc_id: str, page_number: int):
    require_local_storage()
    with store.connect() as db:
        doc = db.execute("SELECT pages FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        raise HTTPException(404, "Datasheet not found")
    if not 1 <= page_number <= doc["pages"]:
        raise HTTPException(404, "Page not found")
    with pdfplumber.open(store.data_dir() / "pdfs" / f"{doc_id}.pdf") as pdf:
        page = pdf.pages[page_number - 1]
        resolution = min(120, 1800 * 72 / max(page.width, page.height))
        bitmap = page.to_image(resolution=resolution).original
        buffer = io.BytesIO()
        bitmap.save(buffer, format="PNG")
        bitmap.close()
    return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control":"private, max-age=3600"})


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    document_ids: list[str] = Field(min_length=1, max_length=8)


@app.post("/api/ask")
async def ask(request: Question):
    require_local_storage()
    ids = list(dict.fromkeys(request.document_ids))
    with store.connect() as db:
        found = {r[0] for r in db.execute(f"SELECT id FROM documents WHERE id IN ({','.join('?' for _ in ids)})", ids)}
    if found != set(ids):
        raise HTTPException(404, "One or more selected datasheets no longer exist.")
    evidence = await run_in_threadpool(search, request.question, ids)
    result = await answer(request.question, evidence)
    return {**result, "question": request.question, "evidence": evidence}
