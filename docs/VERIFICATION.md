# Verification — October 31, 2026

## Automated checks

- 16 tests cover real synthetic-PDF extraction, page boundaries, bordered tables, unit/decimal preservation, upload validation, deduplication, deletion, document-balanced retrieval, no-key evidence mode, no-match abstention, citation IDs and quotes, mocked provider integration, reindexing, benchmark coverage, and ungraded metric handling.
- Browser JavaScript syntax checked with `node --check static/app.js`.
- Python modules compiled with `python -m compileall -q spec_check scripts`.
- Six real manufacturer documents downloaded and indexed. Hashes are recorded in `data/samples/manifest.json` and in benchmark response metadata. The corpus has 533 physical pages. The DRV8833 has two little-text warnings; these remain visible in the library.
- All 24 benchmark questions were sent three times to the local API (72 requests). They returned evidence-only responses without server failures. These are execution checks, not answer-accuracy results. Full records are in `evaluation/runs/retrieval-baseline/`.

## Browser checks

Verified the library, selected a real TMP117 datasheet, submitted an operating-voltage question, and confirmed that physical PDF page 5 appears first in evidence. The interface clearly labels evidence-only mode and does not fabricate an answer without a configured model. Clicking the original-page button opens its source viewer.

The in-app browser does not display embedded PDF plugins. The source viewer therefore renders the requested original page as a PNG on the server, with a separate original-PDF link. Page render dimensions are bounded to 1,800 pixels on the longest edge.

## Pending before final class results

- Confirm funded class API access and an approved model; populate `.env` and validate a live generated answer. Provider integration has only been tested with a mock.
- Complete and independently review gold values, units, conditions, packages, and physical PDF page labels for the 22 positive questions.
- Run the full 72-request benchmark with the configured model and manually score its responses. The negative cases must abstain rather than invent specifications.
- Report exact spec accuracy, citation page-match and support rates with denominators. Current ungraded metrics are null.
- Add a separate paraphrase test set to measure robustness to wording changes.

Lexical retrieval, imperfect merged/table layouts and diagram pinouts remain known limitations. Exact matching of source quotes establishes provenance, not correctness of the model's interpretation.
