# Spec Check

**CSCE 289 — AI for Engineers**  
**Team:** Yash Gandre, Smera Das Gupta, Prarth Gupta

A local web workspace for asking questions about hardware datasheet PDFs. Upload one or more files, select the relevant parts, ask a question, and inspect the retrieved text/tables and original PDF pages. Optional LLM answers contain citations whose page numbers come from the server's extraction records.

## Run

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) or Python 3.11+.

```powershell
uv sync --python 3.12
uv run uvicorn spec_check.app:app --host 127.0.0.1 --port 8001
```

Open [Spec Check](http://127.0.0.1:8001). The OpenAPI interface is at [API docs](http://127.0.0.1:8001/docs).

On Windows, `./run.ps1` starts the app and sets up dependencies if necessary.

This workspace already has a project-local runtime and virtual environment. You can also run:

```powershell
.venv/Scripts/python.exe -m uvicorn spec_check.app:app --host 127.0.0.1 --port 8001
```

Alternatively, create a virtual environment with Python and install the dependencies with `pip install -r requirements.txt`. Run commands from the project root. For tests also install `pytest` and `reportlab`.

## Enable generated answers

Copy `.env.example` to `.env`, then fill in `OPENAI_API_KEY` and `OPENAI_MODEL` using the model/key approved by the class. Restart the server. The configured model must support Chat Completions and JSON object output. `OPENAI_BASE_URL` can point to a compatible class-provided endpoint. No model or paid account is assumed.

Without both values the app runs in **local evidence mode**. Search works; it does not pretend that excerpts are generated answers. With a model configured, the question and retrieved chunks are sent to the configured provider. The API key stays on the server. PDFs, filenames, chunks, and hashes persist locally in `data/`; they are ignored by Git. The UI's model badge indicates configuration, not verified provider access.

## Sample corpus

```powershell
uv run python scripts/fetch_datasheets.py --ingest
```

Downloads six public manufacturer PDFs (Pololu 25D motors, TMP117, LM35, ADS1115, ATmega328P automotive revision, DRV8833), records SHA-256 hashes, and adds them to the library. The sources are declared in `evaluation/datasheets.json`. Manufacturer revisions can change: freeze the downloaded files/hashes before annotating or reporting results. Downloads may fail because of manufacturer access controls; upload the official PDF manually under the declared filename in that case. `--ingest` is optional if you only want downloads. Use `--reindex` to regenerate sample chunks after changing extraction settings while preserving document IDs. ADS1115 replaces the originally considered LIS3DH because ST's download endpoints repeatedly timed out during setup.

## How it works

1. Validate a PDF (20 MB / 500 page limit); deduplicate by SHA-256.
2. Extract each page's text and bordered tables with pdfplumber. Store tables as Markdown with repeated headers when split.
3. Store page-bounded chunks and document metadata in SQLite.
4. Rank chunks with local BM25 and explicit voltage/current/pinout synonyms, reserving retrieval slots for every selected document.
5. If configured, ask the LLM for structured claims, evidence IDs, and exact source quotes. Reject unknown IDs or quotes that do not match the retrieved text. Attach physical PDF page numbers on the server.
6. Show claims, gaps, evidence excerpts, a rendered image of the original source page, and a full-PDF link. Export the full result as JSON. Source previews work even in browsers without an embedded PDF viewer.

This is a lexical RAG baseline, not embedding-based semantic retrieval. Synonyms address common datasheet wording but do not cover every paraphrase. No OCR or image/graph interpretation is implemented. Borderless tables, merged cells, and diagram pinouts can remain ambiguous. Exact quote validation checks provenance; it cannot prove that a claim follows from its quote. A model may still misinterpret a column, condition, or part. Verify critical ratings in the original PDF. An abstention means **insufficient retrieved evidence**, not proof that the full datasheet lacks the spec.

## Validate

```powershell
uv run pytest -q
node --check static/app.js
```

Tests exercise actual PDF text/table extraction, API ingestion/search/delete, document balancing, unsupported questions, and model response validation with a mocked provider. No paid API calls are used by tests. In restricted environments use a project-local temp directory: `uv run pytest -q --basetemp=.pytest-tmp`.

## Evaluate

`evaluation/questions.json` contains **24 questions across six datasheets**, including pinouts, absolute maximum ratings, thermal limits, comparisons, and negative tests. Most gold answers intentionally start unannotated (`gold: null`) so guessed numbers/pages cannot become a benchmark. Before reporting final accuracy, two team members should verify and populate each gold answer against the frozen PDFs.

```json
{"abstain": false, "expected": "Exact value, unit, part, package and conditions", "pages": [{"file": "tmp117.pdf", "page": 5}]}
```

Use **one-based physical PDF pages**, not printed page labels. Include all acceptable supporting pages in `pages`; the automatic strict page check requires exact equality with the cited page set. If several different page sets are acceptable, grade citation support manually and explain this limitation in your report.

With the server running:

```powershell
uv run python scripts/evaluate.py --repeats 3
# Retrieval-only dry run without a key:
uv run python scripts/evaluate.py --repeats 3 --allow-evidence-only
```

The runner saves full responses and blank grades to `evaluation/runs/<timestamp>/`. Manually grade `exact_spec_correct`, `citation_support_correct`, and (only for negative cases) `abstention_correct` as `true` or `false`, leaving nonapplicable fields `null`. Mark provider errors or unsupported positive-case abstentions incorrect. Grade exact specs against the gold answer, including number/unit, part, package, column type, and conditions. Then:

```powershell
uv run python scripts/report.py evaluation/runs/<timestamp>
```

Reports exact spec accuracy, strict citation page-match, human citation support, negative-test abstention, retrieval page coverage, provider errors, and exact-output consistency across repeats, with explicit denominators. **Null means ungraded/unavailable; evidence mode does not count as answer accuracy.** For question rewording robustness, run a separately annotated paraphrase set; repeating identical questions only measures repeat stability.

## Project files

- `spec_check/`: Python API, extraction, storage, retrieval, answer validation
- `static/`: responsive browser UI with no JavaScript build step
- `docs/DESIGN.md`: scope, architecture, risks, timeline, evaluation protocol
- `evaluation/`: sample manifest and 24-question benchmark template
- `scripts/`: sample download and evaluation/report commands
- `tests/`: deterministic automated tests with synthetic PDF fixtures

This is a local, single-workspace class prototype. It has no authentication or tenant isolation; keep the default loopback binding. Uploads and indexing are bounded but not hardened against hostile PDF resource usage. Hosted multi-user deployment, vector retrieval, OCR, and chart reasoning are future work.

## Implementation references

- [pdfplumber documentation](https://github.com/jsvine/pdfplumber) for text/table extraction.
- [OpenAI structured output documentation](https://developers.openai.com/api/docs/guides/structured-outputs) for JSON object output; the app additionally validates response structure and citation quotes locally.
