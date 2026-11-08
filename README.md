# PromoBridge — AI Generalist Prototype for Kuku

**PromoBridge maps a promotional creative to the most likely canonical show and episode, displays the screenplay evidence that supports the match, flags uncertainty, and exports a traceable handoff manifest.**

> **Demo-data note:** The project currently ships with 11 synthetic screenplay episodes across three fictional shows and a 30-case synthetic evaluation set. They are not Kuku content, not based on Kuku's confidential screenplay pack, and not production performance data. Load permitted screenplays in the app to test a real catalogue locally.

## 1. What it solves

A viewer may discover a microdrama through a Facebook / Instagram / TikTok promo and then be unable to find the promised series after opening the app. PromoBridge targets the operational handoff before release: it checks whether the promo transcript/caption maps to the expected show and episode, and whether the mapping is complete enough for downstream deep-link or catalogue operations.

The prototype does **not** diagnose Kuku's internal root cause, repair the consumer app, generate deep links, prove regional availability, ingest video, or claim conversion lift.

## 2. Features

- Load a built-in synthetic catalogue or upload one screenplay file per episode.
- Supported input formats: TXT, Markdown, DOCX, PDF and JSON.
- Infer show / episode IDs from filenames such as `Show Title - E01 - Episode Title.txt`; edit canonical metadata in the Catalogue tab.
- Parse timestamps and scene boundaries into evidence spans with stable `evidence_id` values and original line offsets.
- Paste a promo transcript, ad caption, displayed title, platform, language and territory.
- Rank up to five candidate episodes using deterministic word TF-IDF, character n-gram TF-IDF, token overlap, fuzzy similarity and exact phrase evidence.
- Apply conservative status rules: `VERIFIED`, `NEEDS REVIEW`, `NO MATCH`, `METADATA ERROR`.
- Inspect supporting screenplay text, source scene ID, timestamp / line references and score components.
- Approve, select another candidate, or reject the mapping.
- Export a campaign manifest as CSV and the full traceability run as JSON.
- Run a 30-case synthetic gold set and export metrics / case-level results.
- Optional local `all-MiniLM-L6-v2` semantic retrieval for paraphrases (install separately); deterministic lexical retrieval remains the default.
- 100% private and deterministic by default: operates locally without external LLM API keys or data-sharing requirements.

## 3. Quick start (Windows)

1. Install Python 3.11 or newer.
2. Extract the ZIP into a writable folder.
3. Double-click `run_windows.bat` or run these commands in PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

4. Open the local URL printed in the terminal (usually `http://localhost:8501`).
5. Start in **Match a promo** and use the sample transcript below.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

### Sample demo input

- Displayed title: `The Last Promise`
- Transcript: `Stop the ceremony! This groom is already married.`
- Expected result: `THE_LAST_PROMISE_EP_001`, evidence `THE_LAST_PROMISE_EP_001_SC_003`, status `VERIFIED`.

Another useful test:

- Transcript: `A spaceship captain discovers a new planet after the engine fails.`
- Expected result: `NO MATCH`.

## 4. Load a real screenplay catalogue

Use the **Catalogue** tab. Upload one file per episode (TXT, DOCX, PDF or JSON). The filename convention is recommended:

`Canonical Show Title - E01 - Episode Title.txt`

Review the inferred `show_id`, `canonical_title`, `episode_id`, episode number, language, territory, release status and optional destination URL in the editable table. Language and territory default to `Unknown` and can be corrected by the operator. Blank / unknown destination URLs remain `UNKNOWN`; PromoBridge never fabricates a Kuku deep-link.

For best results, screenplay files should include scene timestamps and scene headings, for example:

```text
[00:00:03] SCENE 1 - INT. WEDDING HALL - NIGHT
MAYA: Stop the ceremony. This groom is already married.

[00:00:38] SCENE 2 - INT. BRIDAL ROOM - NIGHT
ARJUN: I can explain what happened.
```

When timestamps are absent, the app still indexes text and returns source line offsets. If no scene markers exist, it uses the full screenplay as a single evidence span and displays a parse warning. For scripts containing scene-start timestamps only, the `end_time` shown for a scene is the next timestamp boundary (an estimate), not an explicit end time read from the screenplay; the final scene has no inferred end time.

## 5. How matching works

1. **Ingest:** Parse each episode and preserve source text, timecodes, evidence IDs and line offsets.
2. **Retrieve:** Compare the promo transcript + caption to every evidence span. The baseline uses word and character TF-IDF, meaningful-token overlap, RapidFuzz token-set similarity and exact phrase detection.
3. **Aggregate:** Keep the strongest evidence span for each episode; add a small title/alias bonus only when an ad title is provided.
4. **Decide:** Apply code-owned thresholds and abstention rules. A score is a ranking signal, not a probability.
5. **Review:** A human operator approves / rejects the mapping and can select a different returned candidate.
6. **Export:** Produce a CSV manifest and JSON audit record.

### Decision rules in this MVP

- `VERIFIED`: score ≥ 0.82, at least four meaningful transcript tokens, exact normalized transcript phrase is present in the evidence, and the top-two margin is at least 0.08.
- `NEEDS REVIEW`: medium score, ambiguity, very short text, or insufficient evidence for the strict verification rule.
- `NO MATCH`: best score < 0.60 or no candidates.
- `METADATA ERROR`: catalogue validation fails (e.g. blank or duplicate IDs, malformed supplied destination URL).

Thresholds are provisional and should be calibrated on manually labelled promos. Even a `VERIFIED` result means the text-to-screenplay match passed prototype rules; it does not mean a show is available to watch or that its deep link works.

## 6. Optional AI upgrades

### Local semantic retrieval (no paid API)

For paraphrases, you can add a local sentence-transformer model. Install the optional dependency set:

```bash
pip install -r requirements-semantic.txt
```

Then restart the app and enable **Use local semantic retrieval** on the Match a promo tab. The first run downloads `sentence-transformers/all-MiniLM-L6-v2`. If model loading fails, the app falls back to lexical matching and labels the fallback in the result reasons. The deterministic evidence rule still governs `VERIFIED`; semantic similarity alone cannot approve a mapping.

## 7. Evaluation

The included `evaluation/gold_set.csv` has 30 synthetic examples:

- 15 exact / direct-dialogue positives
- 5 paraphrase positives (intentionally harder for the lexical baseline)
- 5 ambiguous / generic examples
- 5 unrelated negative examples

Run inside the project folder:

```bash
python -m evaluation.run_eval
python -m pytest -q
```

The script writes case-level results to `raw_outputs/evaluation_run.json`. The current core test suite contains nine tests covering catalogue loading, exact-match retrieval, abstention, timestamp parsing, DOCX ingestion, saved-catalogue round-trip, duplicate IDs and unsafe destination URLs.

**Latest local synthetic evaluation:**

| Metric | Result |
|---|---:|
| Positive examples | 20 |
| Top-1 retrieval accuracy on positives | 100% (20/20) |
| Top-3 recall on positives | 100% (20/20) |
| False `VERIFIED` on ambiguous + negative cases | 0% (0/10) |

Important nuance: the five paraphrase examples were retrieved at rank 1 but conservatively returned `NO MATCH` because paraphrased wording did not meet the exact-evidence verification rule. This is a known limitation, not a hidden success. Adding sentence embeddings or a grounded semantic verifier is the next step, followed by separate calibration on human-labelled data. These numbers are synthetic smoke-test results only and should not be presented as Kuku or production accuracy.

## 8. Project layout

```text
PromoBridge/
├── app.py                       # Streamlit UI and session workflow
├── cli.py                       # Repeatable command-line matcher
├── src/
│   ├── ingest.py                # TXT / DOCX / PDF / JSON parser
│   ├── catalogue.py             # Catalogue loading, editing, validation
│   ├── scoring.py               # Retrieval score and abstention rules
│   └── export.py                # CSV / JSON manifest contracts
├── data/sample_catalogue/       # Synthetic demo scripts
├── evaluation/gold_set.csv      # 30 labelled synthetic test cases
├── evaluation/run_eval.py       # Repeatable evaluation runner
├── raw_outputs/                 # Demo and local run outputs
├── tests/test_core.py           # Unit tests
├── requirements.txt
└── README.md
```

## 9. CLI run (without the Streamlit UI)

The core matcher can be exercised from a terminal after installing `requirements.txt`:

```bash
python cli.py --title "The Last Promise" --transcript "Stop the ceremony! This groom is already married." --output raw_outputs/my_run.json
```

To use your own directory of screenplay files:

```bash
python cli.py --catalogue-dir "./my_screenplays" --transcript "paste promo dialogue here" --title "My Show"
```

Add `--semantic` after installing `requirements-semantic.txt` to use local embeddings from the CLI.

## 10. Known limitations and next steps

**Known limitations:** lexical matching can miss paraphrases; timestamps depend on screenplay formatting; each uploaded file is treated as one episode; no cross-language semantic matching; no video OCR / audio transcription; session edits are not a shared database; regional release availability and deep-link resolution are not verified; the synthetic gold set is small and authored by the prototype builder.

**Next steps for a real pilot:** label 30–100 real promo-to-episode examples; add sentence-transformer retrieval behind the same retrieval interface; create a human-reviewed alias registry; validate destination URLs against an authoritative catalogue; add versioned persistent storage; measure top-1 / top-3 accuracy, false confident matches, evidence validity, operator handling time and actual first-episode starts from campaign click-throughs.

## 11. Privacy and responsible use

- App matching is local by default; do not upload confidential scripts to public hosting.
- Optional external model calls are disabled by default and gated by explicit consent.
- Do not commit `.env`, Streamlit secrets, private screenplays, or raw outputs containing restricted source text.
- Preserve input originals; only parsed and normalized derived records are used for retrieval.
- A human remains responsible for approving campaign mappings.
