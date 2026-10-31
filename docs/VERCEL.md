# Vercel deployment

The repository declares the FastAPI application explicitly in `pyproject.toml`:

```toml
[tool.vercel]
entrypoint = "spec_check.app:app"
```

`.python-version` selects Python 3.12. `vercel.json` selects the FastAPI framework and permits up to 300 seconds for extraction. Keep the Vercel Root Directory at the repository root and leave custom build/install/output commands unset. The Python runtime installs the project dependencies from the tracked manifests and lockfile. No frontend build command is needed.

## Hosted versus local storage

Vercel functions have no durable shared local filesystem. A SQLite database in the source directory would fail on the read-only deployment bundle; using `/tmp` would lose data and break when requests reach different instances.

On Vercel (`VERCEL=1`), Spec Check instead keeps PDF bytes, document metadata and extracted chunks in **IndexedDB in the visitor's browser**. There is no shared document library on the server. The FastAPI lifespan skips SQLite initialization, and local-storage API routes are disabled. Each question submits the selected document chunks to a stateless endpoint, which runs the same BM25 algorithm and optional LLM answering as the local version. Page previews submit the original PDF for a stateless page render.

Libraries persist across reloads on the same browser and origin, subject to browser storage policies. They do not sync between devices or deployment hostnames, and clearing site data removes them. The UI displays this behavior. Original PDFs are sent to the server for extraction and previews; the selected chunks and question also go to the configured model provider when enabled. Browser-provided chunks are user-controlled input, not a server-certified document archive.

Local startup continues to use the existing SQLite/filesystem library and 20 MB upload limit. Set `SPEC_CHECK_HOSTED=1` locally to exercise the browser-backed hosted path without a deployment.

## Hosted limits

- Individual uploads and source-preview requests: **4 MB** per PDF, leaving space for multipart framing under Vercel's 4.5 MB payload ceiling.
- Extracted corpus per upload and per question: **3 MB serialized**. Select fewer documents or split a large PDF if exceeded.
- At most 500 pages per PDF and eight documents per question.
- Large PDFs such as the roughly 5 MB Pololu sample remain usable in the local app. They must be split or reduced before hosted upload. No automatic lossy PDF conversion is performed.

## Model configuration

Set `OPENAI_API_KEY`, `OPENAI_MODEL`, and optionally `OPENAI_BASE_URL` in the Vercel project's environment settings, then redeploy. Never put a provider key in browser JavaScript or Git. Without both key and model, the deployed app supports evidence search and page viewing; it does not claim to generate model answers.

Keep the project's existing Vercel deployment-protection settings. Deployment protection and application model configuration are separate concerns.

## Verification

Check `/api/health`: hosted deployments must report `storage: "browser"` and `max_upload_bytes: 4194304`.

Then upload a PDF below 4 MB, ask a question, inspect a source page, reload and confirm the browser library persists, and remove the test PDF. Automated tests cover stateless extraction/search/rendering with all local database access forced to fail, as well as malformed PDFs and upload limits.

Official references: [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi), [Vercel Functions limits](https://vercel.com/docs/functions/limitations).
