# Mosaic — Video Prototype Brief for Claude Design

**Deliverable:** A self-running, screen-recordable prototype that plays a scripted **150-second** demo in one unbroken take, with no human interaction after it starts.

**Purpose:** Source footage for a LinkedIn build-in-public post.

**Audience:** Engineers, quant/fintech people, and hiring managers at banks. They have seen forty "AI reads SEC filings" demos this year. This one has to be visibly different in the first five seconds.

---

## 1. The one idea everything hangs on

Most filing tools show you **what is true now**. Mosaic can show you **what was believed then**.

Every fact and every relationship carries two dates: when it was true, and when it became known. That means the entire graph can be rewound.

**So the hero interaction is a time scrubber.** A horizontal timeline runs along the bottom of the screen. Dragging it backwards physically rebuilds the company graph as it stood on that date — edges dissolve because the filing that asserted them hasn't happened yet, nodes drift apart, numbers on screen revert to their originally reported values.

Nobody demos this. Financial dashboards are static snapshots. A graph you can scrub through time is the visual nobody scrolls past, and it is a real capability of the backend rather than a mockup conceit.

**If only one thing gets built well, build the scrubber.**

---

## 2. What is actually real

Build the prototype against these. Every one is implemented and tested in the repo, so the demo is a dramatisation of real behaviour, not an invention.

| Capability | Endpoint | What it demonstrates |
|---|---|---|
| Point-in-time graph | `GET /api/graph/as-of?as_of=` | The scrubber |
| Neighbourhood at a date | `GET /api/graph/as-of/{ticker}?as_of=&radius=` | 2nd-degree hop |
| Edge lineage | `GET /api/graph/history/{a}/{b}` | When a relationship was claimed and dropped |
| Point-in-time financials | `GET /api/companies/{t}/financials/{concept}?as_of=&basis=` | As-reported vs restated |
| Restatement report | `GET /api/analytics/{t}/restatements/{concept}` | Which numbers moved, and in which filing |
| Growth series | `GET /api/analytics/{t}/growth/{concept}` | SQL window functions |
| Reconciliation control | `GET /api/analytics/{t}/controls/balance-sheet` | Assets = liabilities + equity, per period |
| Coverage | `GET /api/analytics/{t}/coverage` | Data completeness per concept |
| Citation grounding | logged `ungrounded_rate` per extraction | Fabricated quotes rejected before storage |

**Run on local fixtures, not live calls.** The recording must be repeatable and cannot depend on EDGAR latency or an LLM being up.

---

## 3. Build this first: DEMO MODE

Not a feature — the whole point.

- One hidden trigger (`Shift+D`, or auto-start after 2s). Never visible in frame.
- All data from local fixtures. Zero network calls. Nothing that can hang mid-take.
- Every transition **time-driven and deterministic**, so a bad take is simply re-shot.
- Hidden `?t=72` seek so a single scene can be re-recorded without replaying everything.
- **Cursor is a simulated in-app element**, not the real pointer. This is what makes it look clean rather than like a person fumbling.
- Total runtime **150s ± 3s**.

If the auto-play harness works, everything else is refinement. If it doesn't, no amount of visual polish yields a usable take.

---

## 4. The 150-second script

| Time | Scene | On screen | Overlay |
|---|---|---|---|
| 0:00–0:07 | **Cold open** | Graph mid-scrub, already moving. Edges materialising. No UI chrome yet. | *Mosaic* |
| 0:07–0:20 | **The claim** | Scrubber slides 2025 → 2021. Graph visibly thins: 34 edges → 11. Counter ticks down live. | "Every other tool shows you today's graph." |
| 0:20–0:30 | **Land it** | Scrub back to 2025. Edges snap in, one at a time, each labelled with the filing that asserted it. | "This one shows you what was known, when." |
| 0:30–0:48 | **Ingest** | Ticker typed. Six pipeline stages light in sequence: `EDGAR → Fetch → XBRL → Extract → Ground → Graph`. Fact counter climbs 0 → 1,247. | "It reads the filings." |
| 0:48–1:02 | **★ Grounding** | Extraction rows stream in. Three turn **red** and slide out of the list, struck through. Rejection counter increments. | "The model wrote a quote that wasn't in the filing. So it was thrown away." |
| 1:02–1:24 | **★★ Graph blooms** | Full force-directed layout. Nodes fly in, edges snap, physics settles over ~4s. **Let it fully settle — do not cut early.** | "1,247 facts. 312 relationships." |
| 1:24–1:44 | **★★★ The 2nd-degree hop** | Camera eases to two distant nodes with no direct edge. Both highlight. A path illuminates through a shared intermediate, pulse travelling along it. Everything else dims to 15%. | "These two have never appeared in the same document." |
| 1:44–2:04 | **Thesis** | Card animates over the dimmed graph. Confidence counts up. Evidence chain expands row by row — each with an exact quote, accession number and filing date. | "Every claim traces to a filing." |
| 2:04–2:22 | **★ Restatement** | Split panel. Left: revenue as filed 2023. Right: same period, restated 2024. The delta highlights in amber. | "This number changed after publication. Most systems only keep the second one." |
| 2:22–2:30 | **Close** | Snap back to the full graph. Scrubber sweeps 2021 → 2025 fast, one continuous rebuild. Logo. | "Mosaic" |

★ = strong. ★★ = money shot. ★★★ = the shot the video exists for.

**30-second cut, if ever needed:** 1:02–1:44 plus the restatement panel.

---

## 5. The scrubber — component spec

This is the piece that deserves disproportionate effort.

- Full-width track along the bottom, ~64px tall, spanning **Jan 2021 → Dec 2025**
- **Filing markers**: small vertical ticks at each filing date. They are the reason the graph changes, so they must be visible
- **Handle**: draws a vertical light beam up through the canvas. Current date in large mono type above it
- **Live counters** beside the date: `nodes 24 · edges 34`, ticking as it moves
- Dragging **re-renders the graph continuously**, not on release. The continuity is the whole effect
- Edges entering: fade in over 300ms with a slight scale-up
- Edges leaving: fade to 0 over 200ms, and the force simulation reheats gently so the layout visibly relaxes
- When the handle crosses a filing marker, that marker **flashes** and any edge it asserted pulses once

**Do not snap to filing dates.** Continuous motion with discrete change events underneath is what makes it feel like a real system rather than a slideshow.

---

## 6. Screens

**Shell** — Left rail: Graph · Theses · Companies · Controls. Top: command input, `as_of` display, a green pipeline dot. Keep chrome minimal; the graph is the star.

**Graph canvas (hero)**
- D3 force-directed, ~45 nodes, ~70 edges
- Node radius 6–22px by fact count; colour by sector
- Edge stroke by type: supplier solid, customer solid+arrow, competitor dashed, shared-risk dotted amber
- Edge width 0.5–3px by confidence
- Ego mode: click a node → 2-degree neighbourhood lit, rest at 15%, 400ms
- Path highlight: animated dash-offset pulse
- Subtle idle drift so the canvas is never fully static

**Pipeline strip** — Six stage cards with state, progress and one live metric each, plus a mono log column streaming filing names. Should feel like watching a real system work.

**Extraction list (grounding scene)** — Rows arrive with company, quote and confidence. Rejected rows turn red, strike through, slide out. A persistent counter reads `verified 41 · rejected 3`.

**Thesis detail** — Statement, confidence with a breakdown, and an evidence chain where **every row carries an exact quoted span, accession number and filing date**. No claim on screen without a citation attached. This is the visual signature.

**Restatement panel** — Two columns, same period, different filing dates. Delta in amber. Both accession numbers visible.

---

## 7. Visual system

Bloomberg-terminal density, Linear-grade polish. Dark, precise, high information, zero decoration.

```
Background      #0A0B0D      Panel          #121317
Panel raised    #1A1C21      Border         #24272E
Text primary    #E8EAED      Secondary      #8B909A     Tertiary  #5A5F68

Accent / verified   #00E5A0    Hypothesis / delta  #FFB020
Rejected / risk     #FF4D4D    Selected / path     #4D9FFF
```

Sector nodes, desaturated so highlights pop:
`#5B8DEF` semis · `#F2A65A` energy · `#8B9AA8` industrials · `#9B7EDE` software · `#4FB3A0` logistics · `#C97B84` materials

**Type** — Inter for UI, JetBrains Mono for tickers, dates, accession numbers, counters. Numbers always tabular-figures so counters don't jitter as they climb.

**Motion** — 200ms state changes, 400ms panels, `cubic-bezier(0.16, 1, 0.3, 1)`. Graph settle 2.5–4s, slow and organic. Counters ease-out, never linear.

**Recording constraints**
- Design at 1920×1080; keep everything critical inside the centre 60% so a 4:5 mobile crop still works
- Minimum on-screen type 15px — LinkedIn video is watched small
- No thin light-on-dark 1px text; it dissolves under video compression
- `#0A0B0D` not pure black — avoids banding

---

## 8. Fixtures

Use real tickers so it reads as legitimate. **Base every quoted span on language that genuinely appears in that filing type, and keep a small `Illustrative demo data` label in a corner.** Do not invent specific financial figures and attribute them to real companies — if the video circulates, fabricated numbers about real public companies is the one thing that turns a good post into a problem.

Needed:
- ~45 companies: ticker, name, sector, fact count
- ~70 edges, each with `known_from` and optional `known_until` — **the scrubber is driven entirely by these two fields**
- A filing timeline 2021–2025 dense enough that scrubbing produces continuous change
- 8–12 theses, one being the hero
- 3 deliberately fabricated extractions for the grounding scene
- One period with an original and a restated figure, both with accession numbers

**Hero narrative:** three companies in different sectors each disclose reliance on the same single-source supplier, and no single filing names all three. Real concentration risk, invisible from one document, and visually perfect — three distant nodes converging on one unremarkable one.

---

## 9. Build order

1. **Demo Mode harness** — auto-play, deterministic timing, simulated cursor
2. **Scrubber + graph binding** — the hero interaction
3. **Graph canvas** — force layout, sector colour, ego highlight
4. **2nd-degree path highlight** — the money shot
5. Grounding list, thesis card, restatement panel
6. Pipeline strip
7. Polish

Steps 1–4 are the video. Everything after is enrichment.

---

## 10. What makes this different

Say this to Claude Design explicitly, because it changes what gets built:

> This is not a dashboard. It is a demonstration that the system knows *when* it knew things. The scrubber is not a filter control — it is the argument. Every other design decision should make that argument more legible.
