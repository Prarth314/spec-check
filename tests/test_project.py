import io
import json
import pytest
import httpx
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from spec_check.app import app
from spec_check.extraction import extract_pdf, markdown_table
from spec_check.answering import validate_answer


def make_pdf():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    c.drawString(50, 780, "MOTOR-X: Recommended operating supply voltage: 12 V. Stall current: 1.8 A.")
    c.showPage()
    c.drawString(50, 780, "MOTOR-X: Absolute maximum supply voltage: 15 V. Not an operating rating.")
    # Bordered electrical characteristics table.
    for y in (700, 675, 650):
        c.line(50, y, 470, y)
    for x in (50, 250, 350, 470):
        c.line(x, 650, x, 700)
    for x, text in [(60,"Parameter"),(260,"Maximum"),(360,"Unit")]:
        c.drawString(x, 683, text)
    for x, text in [(60,"Junction temperature"),(260,"125"),(360,"C")]:
        c.drawString(x, 658, text)
    c.save()
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEC_CHECK_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with TestClient(app) as client:
        yield client


def upload(client, name="motor.pdf", content=None):
    return client.post("/api/documents", files={"file": (name, content or make_pdf(), "application/pdf")})


def test_extraction_page_boundaries_and_tables():
    pages, chunks, warnings = extract_pdf(make_pdf())
    assert pages == 2
    assert any(c["page"] == 1 and "1.8 A" in c["text"] for c in chunks)
    assert not any(c["page"] == 1 and "15 V" in c["text"] for c in chunks)
    table = next(c for c in chunks if c["kind"] == "table")
    assert table["page"] == 2 and "125" in table["text"] and "| --- |" in table["text"]


def test_rag_lifecycle_without_key(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json()["llm_configured"] is False
    r = upload(client)
    assert r.status_code == 201
    doc_id = r.json()["id"]
    assert upload(client).json()["duplicate"] is True
    assert len(client.get("/api/documents").json()) == 1
    r = client.post("/api/ask", json={"question":"What is the stall current?", "document_ids":[doc_id]})
    result = r.json()
    assert result["status"] == "evidence_only"
    assert result["claims"] == []
    assert "1.8 A" in result["evidence"][0]["text"]
    assert result["evidence"][0]["page"] == 1
    pdf = client.get(f"/api/documents/{doc_id}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    page = client.get(f"/api/documents/{doc_id}/pages/2.png")
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")
    assert client.get(f"/api/documents/{doc_id}/pages/3.png").status_code == 404
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}/pdf").status_code == 404
    assert client.get("/api/documents").json() == []


def test_no_evidence_abstains(client):
    doc_id = upload(client).json()["id"]
    r = client.post("/api/ask", json={"question":"Bluetooth encryption protocol?", "document_ids":[doc_id]})
    assert r.json()["status"] == "abstained" and r.json()["claims"] == []


def test_invalid_upload_and_selection(client):
    assert upload(client,content=b"not pdf").status_code == 415
    assert upload(client,content=b"%PDF-corrupt").status_code == 422
    assert client.post("/api/ask", json={"question":"Voltage?", "document_ids":[]}).status_code == 422
    assert client.post("/api/ask", json={"question":"Voltage?", "document_ids":["missing"]}).status_code == 404
    assert client.get("/api/documents/missing/pdf").status_code == 404


def test_comparison_retrieves_both_documents(client):
    first = upload(client).json()["id"]
    second = upload(client,"motor-b.pdf",make_pdf()+b"\n%different source").json()["id"]
    result = client.post("/api/ask",json={"question":"Compare supply voltage", "document_ids":[first,second]}).json()
    assert {e["document_id"] for e in result["evidence"]} == {first,second}


EVIDENCE = [{"id":7,"text":"Recommended supply voltage is 12 V.","document_id":"doc","name":"motor.pdf","page":4}]
RAW = {"status":"answered","claims":[{"text":"Rated at 12 V.","evidence_ids":[7],"quotes":["supply voltage is 12 V."]}],"missing":""}


def test_citations_use_server_pages():
    result = validate_answer(RAW,EVIDENCE)
    assert result["claims"][0]["citations"][0]["page"] == 4


@pytest.mark.parametrize("ids,quotes", [([999],["supply voltage is 12 V."]),([7],["supply voltage is 1.2 V."]),([7],[]),([7],["12"])])
def test_rejects_hallucinated_quotes_and_ids(ids,quotes):
    raw = {**RAW,"claims":[{**RAW["claims"][0],"evidence_ids":ids,"quotes":quotes}]}
    with pytest.raises(ValueError):
        validate_answer(raw,EVIDENCE)


def test_rejects_unsupported_status():
    with pytest.raises(ValueError):
        validate_answer({**RAW,"status":"probably"},EVIDENCE)


def test_provider_success_and_failure(client,monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test-key")
    monkeypatch.setenv("OPENAI_MODEL","test-model")
    doc_id = upload(client).json()["id"]
    from spec_check.store import connect
    with connect() as db:
        eid = db.execute("SELECT id FROM chunks WHERE page=1").fetchone()[0]
    payload = {"status":"answered","claims":[{"text":"The stall current is 1.8 A.","evidence_ids":[eid],"quotes":["Stall current: 1.8 A."]}],"missing":""}
    async def post(self,url,**kwargs):
        assert kwargs["json"]["response_format"] == {"type":"json_object"}
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(payload)}}]},request=httpx.Request("POST",url))
    monkeypatch.setattr(httpx.AsyncClient,"post",post)
    r = client.post("/api/ask",json={"question":"Stall current?", "document_ids":[doc_id]}).json()
    assert r["status"] == "answered" and r["claims"][0]["citations"][0]["page"] == 1
    payload["claims"][0]["quotes"] = ["Stall current: 18 A."]
    r = client.post("/api/ask",json={"question":"Stall current?", "document_ids":[doc_id]}).json()
    assert r["status"] == "error" and not r["claims"]


def test_table_preserves_decimal_and_unit():
    text = markdown_table([["Parameter","Max","Unit"],["Vcc","1.2","V"],["Current","200","mA"]])
    assert "| Vcc | 1.2 | V |" in text and "| Current | 200 | mA |" in text


def test_reindex_preserves_document_and_replaces_chunks(client):
    from spec_check.app import ingest
    from spec_check.store import connect
    content = make_pdf()
    first = ingest(content,"motor.pdf")
    with connect() as db:
        db.execute("UPDATE chunks SET text='obsolete extraction'")
    indexed = ingest(content,"motor.pdf",reindex=True)
    assert indexed["id"] == first["id"] and indexed["reindexed"] is True
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM chunks WHERE text='obsolete extraction'").fetchone()[0] == 0


def test_vercel_workspace_never_requires_writable_server_storage(tmp_path, monkeypatch):
    from spec_check import store
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SPEC_CHECK_DATA_DIR", str(tmp_path / "must-not-create"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Hosted requests must not use the local database")
    monkeypatch.setattr(store, "initialize", forbidden)
    monkeypatch.setattr(store, "connect", forbidden)
    with TestClient(app) as hosted:
        assert hosted.get("/").status_code == 200
        assert hosted.get("/static/browser-library.js").status_code == 200
        health = hosted.get("/api/health").json()
        assert health["storage"] == "browser" and health["max_upload_bytes"] == 4 * 1024 * 1024
        assert hosted.get("/api/documents").status_code == 409
        assert hosted.post("/api/ask", json={"question":"Voltage?", "document_ids":["any"]}).status_code == 409
        content = make_pdf()
        result = hosted.post("/api/browser/extract",files={"file":("motor.pdf",content,"application/pdf")})
        assert result.status_code == 200
        doc = result.json()
        assert doc["pages"] == 2 and doc["chunks"] == len(doc["extracted_chunks"])
        question = {"question":"What is the stall current?", "documents":[
            {"id":doc["id"], "name":doc["name"], "pages":doc["pages"], "chunks":doc["extracted_chunks"]}]}
        # Fresh requests reconstruct the corpus from the browser, without server state.
        for _ in range(2):
            answer = hosted.post("/api/browser/ask",json=question).json()
            assert answer["status"] == "evidence_only"
            assert answer["evidence"][0]["page"] == 1
            assert "1.8 A" in answer["evidence"][0]["text"]
        image = hosted.post("/api/browser/render?page=2",files={"file":("motor.pdf",content,"application/pdf")})
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        assert hosted.post("/api/browser/render?page=3",files={"file":("motor.pdf",content,"application/pdf")}).status_code == 404
        question["documents"][0]["chunks"][0]["page"] = 3
        assert hosted.post("/api/browser/ask",json=question).status_code == 422
    assert not (tmp_path / "must-not-create").exists()


def test_hosted_pdf_limits_and_corrupt_input(client, monkeypatch):
    from spec_check import browser_api
    assert client.post("/api/browser/extract",files={"file":("bad.pdf",b"not PDF")}).status_code == 415
    assert client.post("/api/browser/extract",files={"file":("bad.pdf",b"%PDF-broken")}).status_code == 422
    monkeypatch.setattr(browser_api,"MAX_UPLOAD_BYTES",1000)
    assert client.post("/api/browser/extract",files={"file":("large.pdf",make_pdf())}).status_code == 413


def test_vercel_entrypoint_and_python_are_declared():
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    assert config["tool"]["vercel"]["entrypoint"] == "spec_check.app:app"
    assert (root / ".python-version").read_text().strip() == "3.12"
