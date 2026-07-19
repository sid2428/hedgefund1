# Mosaic — Production Engineering Spec

**Repo:** github.com/sid2428/hedgefund1
**Goal:** Take Mosaic from a single-commit prototype to a system that survives scrutiny from someone who builds these for a living.

---

## 0. Framing — read this first

You asked for "production ready in HFT." One honest correction before the spec, because getting this wrong is the fastest way to lose a technical reader.

**Mosaic is not a high-frequency trading system and shouldn't claim to be.** HFT means microsecond-scale market making — kernel bypass, FPGAs, colocated racks, nanosecond timestamping. Applying that vocabulary to a system that reads 10-Ks would read as someone who has heard the words but not done the work. Any quant engineer would spot it in one line of your README.

What *is* true, and is a genuinely competitive engineering problem:

1. **Filing-to-signal latency is a real race.** EDGAR's Public Dissemination Service pushes accepted filings to subscribers, and acceptance-to-dissemination usually takes no longer than two minutes. Firms compete hard on what happens in the seconds after that. Sub-second parse-to-signal on an 8-K is a legitimate, defensible engineering target.
2. **Hedge-fund-grade data correctness is a much higher bar than typical web engineering** — point-in-time reconstruction, bitemporality, no lookahead, deterministic replay, full audit lineage. This is where the real difficulty lives, and where Mosaic can be genuinely excellent.

So the standard this spec targets: **buy-side research infrastructure**, not HFT. Say that in the README and you gain credibility instead of spending it.

---

## 1. Pipeline — the node graph

The current README shows seven boxes. That's a sketch. Here is the production topology: **17 nodes**, each with one responsibility, an explicit latency budget, and a defined failure mode.

```
                                  ┌─────────────┐
                                  │ 01 WATCHER  │  EDGAR feed, new accessions
                                  └──────┬──────┘
                                         ▼
                                  ┌─────────────┐
                                  │ 02 FETCHER  │  token-bucket, backoff, UA
                                  └──────┬──────┘
                                         ▼
                                  ┌─────────────┐
                                  │ 03 VAULT    │  content-addressed, immutable
                                  └──────┬──────┘
                                         ▼
                                  ┌─────────────┐
                                  │ 04 ROUTER   │  form-type + item segmentation
                                  └──────┬──────┘
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
                  ┌─────────────┐                 ┌─────────────┐
                  │ 05 XBRL     │                 │ 07 SEGMENT  │
                  │    LOADER   │                 │  narrative  │
                  └──────┬──────┘                 └──────┬──────┘
                         ▼                               ▼
                  ┌─────────────┐                 ┌─────────────┐
                  │ 06 NORMALIZE│                 │ 08 EXTRACT  │  LLM, schema-bound
                  └──────┬──────┘                 └──────┬──────┘
                         │                               ▼
                         │                        ┌─────────────┐
                         │                        │ 09 GROUNDER │  citation gate ★
                         │                        └──────┬──────┘
                         └───────────────┬───────────────┘
                                         ▼
                                  ┌─────────────┐
                                  │ 10 RESOLVER │  entity resolution
                                  └──────┬──────┘
                         ┌───────────────┼───────────────┐
                         ▼               ▼               ▼
                  ┌───────────┐   ┌───────────┐   ┌───────────┐
                  │ 11 DELTA  │   │ 12 EMBED  │   │ 13 GRAPH  │  bitemporal ★
                  └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
                        └───────────────┼───────────────┘
                                        ▼
                                 ┌─────────────┐
                                 │ 14 CONNECTOR│  2nd-degree candidates
                                 └──────┬──────┘
                                        ▼
                                 ┌─────────────┐
                                 │ 15 THESIS   │  as-of clamped generation
                                 └──────┬──────┘
                                        ▼
                                 ┌─────────────┐
                                 │ 16 ADJUDICAT│  contamination + calibration ★
                                 └──────┬──────┘
                                        ▼
                                 ┌─────────────┐
                                 │ 17 LEDGER   │  append-only, replayable ★
                                 └──────┬──────┘
                                        ▼
                                   FastAPI + SSE
```

★ = the four nodes that make this repo interesting. If time is short, build those and stub the rest.

---

## 2. Node specifications

### 01 · WATCHER
**Does:** Polls EDGAR for newly accepted filings; emits an accession event.
**Budget:** detect within 5s of availability.
**Notes:** Poll the daily index and the real-time RSS. Deduplicate on accession number — you will see the same filing announced more than once. Keep a high-water mark so a restart doesn't replay the day.
**Fails to:** last known good high-water mark. Never skip forward on error; a gap is worse than a delay.

### 02 · FETCHER
**Does:** Retrieves filing documents under EDGAR's access rules.
**Hard constraints, from SEC's published limits:**
- **10 requests/second per IP**, across all EDGAR domains. Exceed it and you get a 403 and roughly a **10-minute IP block** — every request fails during that window
- A descriptive **User-Agent with a contact email** is mandatory. Generic strings (`python-requests/2.x`, `Mozilla/5.0`) are the most common cause of 403s
**Implementation:** global token bucket at **8 req/s** (not 10 — leave headroom), exponential backoff with jitter, circuit breaker after N consecutive 403s, and on-disk caching so a re-run costs zero requests.
**Also:** for any bulk backfill, use the SEC's bulk files rather than iterating the API. Thousands of individual requests where one archive would do is the single most common way to get blocked.

### 03 · VAULT
**Does:** Stores raw filing bytes, immutably.
**Design:** content-addressed by SHA-256. Path = hash. Write-once, never mutated, never deleted.
**Why it matters:** this is the substrate for point-in-time correctness. Every downstream fact traces to an immutable blob you can re-verify years later. It also makes the entire pipeline replayable without touching EDGAR again.

### 04 · ROUTER
**Does:** Classifies form type (10-K / 10-Q / 8-K / 13F / S-1 / 4) and segments into items.
**Notes:** 8-K item numbers carry most of the signal — Item 1.01 material agreements, 2.02 results, 5.02 officer departures, 7.01 Reg FD. Route by item, not just by form. Different items deserve different latency budgets and different downstream treatment.

### 05 · XBRL LOADER — *the biggest architectural win available to you*

**Do not use an LLM to extract numbers that are already tagged.**

XBRL tagging has been mandatory for SEC financial filings since 2009. The `companyfacts` endpoint returns every structured fact a company has ever filed — revenues, assets, shares outstanding, hundreds more — in a single JSON payload. The `frames` endpoint returns every company reporting a given concept for a given period in one response.

Right now Mosaic routes everything through Groq Llama 3.3. For tagged financials that is slower, more expensive, and **strictly less accurate** than reading the XBRL. An LLM can transpose a digit. The XBRL is the number the company filed.

**Split the responsibility:**
- **Structured financials → XBRL.** Exact, free, instant, auditable.
- **Narrative → LLM.** MD&A, risk factors, footnote text, supplier and customer language, anything the company chose not to tag. This is where the LLM earns its cost, and it is also where the cross-company relationships actually live.

This single change improves accuracy, cuts cost by an order of magnitude, and is a strong README talking point.

### 06 · NORMALIZER
**Does:** Reconciles XBRL concepts to a canonical schema.
**The real work:** XBRL is standardised but not uniform — **revenue alone requires checking four or more different tags** depending on filer and era. You need a concept-mapping layer with an explicit precedence order, plus unit and scale normalisation, and fiscal-calendar alignment so Q3 means the same thing across companies with different year-ends.
**Test this hard.** It is the least glamorous node and the one most likely to silently corrupt everything downstream.

### 07 · SEGMENTER
**Does:** Splits narrative sections and preserves exact character offsets into the vaulted source.
**Critical:** carry `(document_id, char_start, char_end)` through every downstream stage. Node 09 cannot work without it.

### 08 · EXTRACTOR
**Does:** LLM extraction over narrative only. Schema-constrained output.
**Design:** structured outputs / function calling, never free text. Every extracted claim must carry its source span. Cache by `(prompt_hash, model, model_version, document_hash)` — see §3.2.

### 09 · GROUNDER ★ — *the anti-hallucination gate*

**Rule: a claim whose quoted span does not literally occur in the source document is rejected before persistence.**

This is the same pattern you used in Grow (an email or phone is accepted only if it appears in the source row) and in AEGIS (ML may only raise risk, never lift a block). It is the strongest engineering instinct in your portfolio and it should be the spine of Mosaic too: **the model proposes, deterministic code verifies.**

Implementation: exact-match the quoted span against the vaulted document at the claimed offsets. Allow whitespace normalisation and nothing else. On failure, drop the claim, log it, and increment a counter.

**Expose the rejection rate as a first-class metric.** "N% of model-generated claims failed citation verification and were discarded" is a number nobody else publishes, it is genuinely interesting, and it converts a weakness everyone assumes you have into evidence of rigour.

### 10 · RESOLVER
**Does:** Entity resolution. `TSMC` / `Taiwan Semiconductor Manufacturing` / `台積電` / CIK 1046179 → one canonical entity.
**Why it's load-bearing:** your entire product is cross-company edges. If entity resolution is weak, the graph is wrong and every thesis built on it is wrong. Key off CIK where available, LEI where available, and keep a reviewed alias table for the rest. Never fuzzy-match into a merge without a confidence threshold and an audit record.

### 11 · DELTA
**Does:** Diffs a filing against the same company's prior equivalent filing.
**Signal:** risk factor added or removed, supplier or customer named then dropped, guidance language softened, segment reclassified, auditor changed.
**Why it's good:** diffs are cheap, deterministic, need no LLM for detection (only for summarisation), and disclosure changes are a well-established research signal.

### 12 · EMBEDDER — pgvector
**Index:** HNSW. Tuning parameters and their real constraints:
- `m` — connections per node. Range 5–48, **default 16**. Higher = faster queries, slower builds, more memory
- `ef_construction` — build-time candidate list, **default 64**. Higher = better graph quality, slower build
- `ef_search` — query-time candidate list. Tunable per session or transaction; raise for recall, lower for speed

**The trap:** `m` and `ef_construction` **cannot be ALTERed**. Choosing wrong means a full index rebuild. Decide deliberately and write the reasoning into a comment in the migration.

**Also:** the index needs to stay resident in memory. Size `maintenance_work_mem` for the build and check the index actually fits in RAM, or your p99 falls off a cliff and you will blame the wrong component.

### 13 · GRAPH BUILDER ★ — *make it bitemporal*

This is the node that separates a demo from research infrastructure.

**Every edge and every fact carries two time axes:**
- `valid_time` — when the fact was true in the world (the filing's period)
- `transaction_time` — when your system learned it (ingestion timestamp)

With both, you can answer *"what did the graph look like as known on 15 March 2024?"* — and answer it correctly, excluding everything you only learned afterwards.

**Why this is the highest-value thing in the whole document:** it structurally eliminates lookahead bias. Research on backtest bias is unambiguous that this matters — backtests using restated data systematically outperform the same backtests on as-reported data, and Bailey and López de Prado estimate lookahead bias can inflate annualised returns by **100–500 basis points**. If Mosaic ever generates a historical thesis using facts filed after the as-of date, every result it produces is worthless.

**Also persist the graph.** NetworkX in-memory is fine for a demo and a liability beyond it. Edges to Postgres with provenance on each edge (which filing, which claim, which confidence), rebuild in-memory on boot.

**Ship the endpoint:** `GET /api/graph?as_of=2024-03-15`. It is a small amount of code on top of bitemporality and it is instantly, obviously impressive.

### 14 · CONNECTOR
**Does:** Generates cross-company candidates via 2nd-degree traversal.
**Guard rails:** cap path length, require a minimum edge confidence on every hop, and require **at least two independent filings** supporting any proposed connection. Without those, a graph of this shape generates infinite plausible nonsense.
**Rank before generating.** Don't hand the LLM every candidate — score them (path strength × recency × source independence) and generate on the top N. Cost control and quality control at once.

### 15 · THESIS ENGINE
**Does:** Generates the thesis text over a retrieved, cited evidence set.
**Constraint:** the model sees only evidence dated at or before the as-of timestamp. Context assembly must clamp on `transaction_time`, not just `valid_time`.

### 16 · ADJUDICATOR ★ — *LLM contamination guard*

This is the subtlest node and the one that will most impress anyone serious.

**The problem:** even with perfect point-in-time data plumbing, you have a leak. An LLM pretrained in 2025 already knows how 2019–2023 played out. Ask it to reason about a 2019 filing and it can produce a "prediction" that is really a memory. Recent work is explicit about this: pretraining cutoffs mean models have already seen the outcomes, producing artificially inflated performance that evaporates in live deployment. Researchers now estimate the likelihood a given prompt appeared in the training corpus, and treat a positive correlation between that memorisation score and forecast accuracy as a direct measure of lookahead bias.

**Mitigations to implement, cheapest first:**
1. **Entity anonymisation for historical runs.** Replace tickers and company names with stable pseudonyms before generation. If the model can't identify the firm, it can't retrieve the outcome. This is the documented approach and it's genuinely simple to build
2. **Date stripping** in retrieved context where the date isn't load-bearing
3. **Contamination scoring** — flag any historical thesis where the model's confidence is suspiciously high relative to the evidence actually supplied
4. **Live-forward evaluation** — the only fully honest measure. Timestamp theses on generation, score them later against outcomes. Slow, but it's the number that means something

**Confidence calibration:** derive the score from countable inputs — number of independent filings, source recency, path length, corroboration vs conflict — not from asking the model how sure it is. Then show the breakdown in the API response so it can be audited.

### 17 · LEDGER ★
**Does:** Append-only record of every thesis, its inputs, and its verdict.
**Record per thesis:** input evidence hashes, model + version, prompt hash, graph snapshot id, as-of timestamp, output, confidence breakdown, PM verdict.
**Enables:** exact replay, drift detection when a model version changes, and an honest audit trail. You built precisely this in AEGIS — reuse the design.

---

## 3. Cross-cutting concerns

### 3.1 Point-in-time correctness
Non-negotiable if the system ever touches historical analysis. Beyond bitemporality:
- **Survivorship bias:** your company universe must be as-of too. Backfilling with today's index constituents systematically inflates results, because the losers were removed and the winners added
- **Restatements:** keep as-filed *and* as-restated, and default every query to as-filed
- These biases compound multiplicatively rather than adding — a system with three small biases doesn't have three small problems

### 3.2 Determinism and replay
Cache every model response keyed by `(prompt_hash, model_id, model_version, evidence_hash)`.

Three payoffs: re-runs are free, results are reproducible, and you can prove a thesis was generated from exactly the evidence you claim. Add a `/replay/{thesis_id}` endpoint that regenerates byte-identically — same pattern as AEGIS, and it is a genuinely rare capability in an LLM pipeline.

### 3.3 Idempotency and backpressure
Every stage keyed by `(accession_no, stage, pipeline_version)` so replays are safe and partial failures resume rather than duplicate. Bounded queues with explicit rejection — silent unbounded growth under load is how these systems die.

### 3.4 Observability
Per-node: throughput, p50/p95/p99 latency, error rate, queue depth. Plus four domain metrics that actually matter and that nobody else publishes:

| Metric | Why |
|---|---|
| Citation rejection rate | Direct measure of grounding quality |
| Filing-to-signal latency (p99) | Your competitive claim, measured |
| Entity resolution precision | Silent corrupter of everything downstream |
| Thesis validate/dismiss ratio | The only real ground truth you have |

OpenTelemetry traces spanning accession → thesis. One trace id through 17 nodes is both good engineering and a great screenshot.

### 3.5 Streaming, not polling
Replace `GET /api/jobs/{job_id}` polling with SSE. Better UX, lower load, and a smoother pipeline view:

```
event: stage   {node, state, progress, metric}
event: fact    {company, fact_type, count}
event: edge    {source, target, type, confidence}
event: reject  {claim_id, reason}      ← surface the grounder working
event: done    {thesis_ids}
```

---

## 4. Testing

Currently zero. Minimum credible set:

| Suite | What it covers |
|---|---|
| Golden-file extraction | 4–5 committed real filings, asserted fact output |
| XBRL normalisation | The multi-tag revenue problem, units, scales, fiscal alignment |
| **Grounding** | Fabricated citations **must** be rejected. Name it `test_claim_with_invented_quote_is_rejected` |
| **Bitemporal** | `as_of` query must never return a fact with a later `transaction_time` |
| Entity resolution | Known alias set, plus near-miss pairs that must *not* merge |
| Connector | 2nd-degree paths found, 3rd-degree not returned |
| Determinism | Same inputs → byte-identical thesis |
| Rate limiter | Token bucket never exceeds 8 req/s under concurrency |

Plus CI on every push, coverage badge, and a nightly integration run against a frozen fixture corpus.

---

## 5. Security and ops

- API keys from environment only. `.env.example` committed, `.env` never. Add a secret scanner to CI — your GitHub notifications already show a "possible valid secrets detected" alert on another repo, so this is a live habit worth fixing
- Structured JSON logging, no filing content in logs
- `/health` (liveness) and `/ready` (dependency checks) separated
- Alembic migrations forward-only and tested against a seeded DB
- Pin dependencies; Dependabot on
- Rate limiting on your own API, not just on EDGAR

---

## 6. Phased plan

**Phase 1 — credibility (1 week).** XBRL loader + normaliser. Grounder with rejection metric. Tests for both. LICENSE, README, description, topics. Commit continuously.

**Phase 2 — the differentiator (1–2 weeks).** Bitemporal schema. `as_of` graph endpoint. Graph persistence. Entity resolver with an alias table.

**Phase 3 — rigour (1 week).** Adjudicator with entity anonymisation. Confidence calibration from countable inputs. Ledger + replay endpoint.

**Phase 4 — polish (ongoing).** SSE. OpenTelemetry. Delta detection. pgvector tuning under real volume.

Phases 1 and 2 alone move this from "one commit" to "this person builds real systems."

---

## 7. Claims you'll be able to make honestly

Not marketing — each maps to something above that you can point at in code:

- Structured financials read from XBRL, not inferred by a model
- Every claim carries a verified citation; unverifiable claims are rejected before persistence, at a measured rate
- Bitemporal store — the graph can be reconstructed exactly as it was known on any past date
- Lookahead bias addressed at both the data layer and the model layer
- Deterministic replay of any thesis from its recorded inputs
- EDGAR access inside published rate limits, with backoff and caching
- Filing-to-signal latency measured and published as a p99

That list is stronger than anything most "AI reads SEC filings" projects can say, and every line is defensible under questioning — which is the actual bar.

---

## Sources

- [SEC EDGAR Public Dissemination Service (PDS)](https://www.sec.gov/search-filings/public-dissemination-service-system-contact) — dissemination timing, filing volumes
- [SEC EDGAR PDS Technical Specification](https://www.sec.gov/files/edgar/pds_dissemination_spec.pdf)
- [SEC: new rate control limits to EDGAR websites](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits)
- [SEC EDGAR API rate limits and best practices](https://tldrfiling.com/blog/sec-edgar-api-rate-limits-best-practices) — 10 req/s, User-Agent, block duration
- [SEC EDGAR XBRL API tutorial](https://tldrfiling.com/blog/sec-edgar-xbrl-api-python-tutorial) — companyfacts, frames
- [How to get SEC filing data: 3 methods compared](https://fundamentalshub.com/blog/how-to-get-sec-filing-data) — XBRL vs HTML parsing, multi-tag revenue problem
- [A Taxonomy of Backtest Lies](https://www.susanpotter.net/quant/backtest-bias-taxonomy/) — compounding bias effects
- [Look-ahead bias in backtesting](https://www.pfolio.io/academy/look-ahead-bias) — restated vs as-reported, 100–500bps estimate
- [Detecting Lookahead Bias in LLM Forecasts](https://arxiv.org/abs/2512.23847) — memorisation scoring
- [Look-Ahead-Bench: point-in-time LLMs for finance](https://arxiv.org/pdf/2601.13770)
- [Mitigating Look-Ahead Bias in Financial Backtesting with LLMs](https://arxiv.org/html/2605.24564) — anonymisation, inference-time mitigation
- [HNSW indexes with Postgres and pgvector](https://www.crunchydata.com/blog/hnsw-indexes-with-postgres-and-pgvector) — m, ef_construction, ef_search
- [Tuning pgvector performance](https://www.paradedb.com/learn/postgresql/tuning-pgvector) — memory residency, non-alterable parameters
