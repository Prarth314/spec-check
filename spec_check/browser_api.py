"""Stateless endpoints for browser-owned libraries on serverless hosting.

No original PDFs, chunks, or per-user database files survive on the server.
The browser submits its own selected corpus with each question.
"""
import hashlib
import io
import json
from typing import Literal
import pdfplumber
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool
from .answering import answer
from .extraction import extract_pdf
from .retrieval import rank_chunks

router = APIRouter(prefix="/api/browser", tags=["Browser workspace"])
# Leave room for multipart framing under Vercel's 4.5 MB request limit.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_CORPUS_BYTES = 3 * 1024 * 1024


async def read_pdf(file):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Hosted uploads support PDFs up to 4 MB. Use the local app for larger files.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(415, "Please upload a valid PDF file.")
    return content


def extract_document(content, filename):
    try:
        pages, chunks, warnings = extract_pdf(content)
    except Exception as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else "Unable to extract this PDF. Check that it is valid and not password protected.") from exc
    if len(chunks) > 6000 or any(len(c["text"]) > 20000 for c in chunks):
        raise HTTPException(422, "This PDF has unusually large tables. Split it into smaller PDFs before uploading.")
    result = {"id": hashlib.sha256(content).hexdigest(), "name": filename,
              "sha256": hashlib.sha256(content).hexdigest(), "pages": pages,
              "chunks": len(chunks), "warnings": warnings, "extracted_chunks": chunks}
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_CORPUS_BYTES:
        raise HTTPException(422, "This PDF has too much extracted text for hosted search. Split it into smaller PDFs.")
    return result


@router.post("/extract")
async def extract(file: UploadFile = File(...)):
    content = await read_pdf(file)
    name = (file.filename or "datasheet.pdf").replace("\\", "/").split("/")[-1][:180]
    return await run_in_threadpool(extract_document, content, name)


class BrowserChunk(BaseModel):
    page: int = Field(ge=1, le=500)
    kind: Literal["text", "table"]
    # Older browser libraries may contain empty table artifacts. Retrieval ignores
    # these, so tolerate them while the extractor stops creating new empty chunks.
    text: str = Field(max_length=20000)


class BrowserDocument(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=180)
    pages: int = Field(ge=1, le=500)
    chunks: list[BrowserChunk] = Field(min_length=1, max_length=6000)

    @model_validator(mode="after")
    def pages_exist(self):
        if not any(chunk.text.strip() for chunk in self.chunks):
            raise ValueError("Document has no searchable text")
        if any(chunk.page > self.pages for chunk in self.chunks):
            raise ValueError("Chunk refers to a page outside its document")
        return self


class BrowserQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    documents: list[BrowserDocument] = Field(min_length=1, max_length=8)


@router.post("/ask")
async def ask(request: BrowserQuestion):
    ids = [doc.id for doc in request.documents]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Each selected document must be unique.")
    if len(request.model_dump_json().encode("utf-8")) > MAX_CORPUS_BYTES:
        raise HTTPException(413, "The selected datasheets contain too much text. Select fewer datasheets for this question.")
    rows = []
    for doc in request.documents:
        for chunk in doc.chunks:
            rows.append({"id": len(rows) + 1, "document_id": doc.id, "name": doc.name, **chunk.model_dump()})
    evidence = await run_in_threadpool(rank_chunks, request.question, rows, ids)
    result = await answer(request.question, evidence)
    return {**result, "question": request.question, "evidence": evidence}


def render_page(content, page_number):
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if not 1 <= page_number <= len(pdf.pages):
                raise HTTPException(404, "Page not found")
            page = pdf.pages[page_number - 1]
            resolution = min(120, 1800 * 72 / max(page.width, page.height))
            bitmap = page.to_image(resolution=resolution).original
            try:
                buffer = io.BytesIO()
                bitmap.save(buffer, format="PNG")
            finally:
                bitmap.close()
            return buffer.getvalue()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "Unable to render this PDF page.") from exc


@router.post("/render")
async def render(page: int = 1, file: UploadFile = File(...)):
    content = await read_pdf(file)
    image = await run_in_threadpool(render_page, content, page)
    return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})
