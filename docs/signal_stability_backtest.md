# Signal-Stability Backtest — Phase 0

**Purpose.** Validation, not prediction. Does not touch any existing mart, model, or test. All data pulled from BigQuery (`bronze` dataset); zero external API cost. Read `docs/threshold_decisions.md` before this — several thresholds referenced here (`reliability_min_competitor_count`, `max_competitor_staleness_days`, `reliability_low_gap_threshold`, `reliability_medium_gap_threshold`, and the §7.8 natural-gap method) are reused for fidelity, not redefined.

**Question.** Does `price_gap_reliability` — the gate the pipeline already uses to decide whether a pricing signal is trustworthy enough to act on — actually predict that the signal is *stable* over time? Three measures (direction, magnitude, action), computed separately, never collapsed into one score.

**Deliverable.** This document. Analysis lives in ad hoc scripts (BigQuery client + pandas), not a dbt model — this is a validation report, not new pipeline logic. Nothing in `models/` changed as part of this work.

**Framing, stated plainly before the results:** `price_gap_reliability` was built to answer a specific, different question — "is there enough competitor evidence to trust this gap at all" (adequate sample size, fresh benchmark, plausible magnitude) — and it answers that question correctly. It was never designed as, and was never claimed to be, a predictor of temporal stability. What this backtest finds is that **sufficiency and stability are different properties, and in this data they point in opposite directions.** That is not evidence the reliability gate is broken. The safety invariant it exists to protect (blocking pricing actions on non-comparable or under-sampled baskets) rests on sufficiency, and sufficiency is intact — confirmed independently in §2 below, where the gate's own logic is shown to reproduce production output exactly.

---

## 1. Data, grain, and why nothing existing was reused

Grain: `store_id × category_name × kroger_collection_date`. 200 store×category pairs (20 stores × 10 categories), across 13 collection dates (`2026-06-10` through `2026-08-26`). Each pair has 11–13 of the 13 dates (1 pair has 11, 19 have 12, 180 have 13 — a handful of rows drop out per date from the existing >5× category-median outlier exclusion, unrelated to this backtest).

Confirmed by reading the models, not assumed:
- `fct_store_category_weekly` / `int_pricing_temporal_features` are genuinely per exact `kroger_collection_date` (documented in-code as "opposite of `mart_pricing_intelligence`, which pins to the latest partition"). `price_gap_pct`, `price_gap_direction`, `price_position`, `gap_direction_stable` all come from here, unmodified.
- `recommended_price_action` lives only in `mart_pricing_intelligence`, which (a) keeps only the single latest `kroger_collection_date`, never historically, and (b) depends on `confidence_score` / `markdown_safety_score` / `margin_pressure_proxy_score` / `premium_support_proxy_score`, all **monthly**-grain composites from `fact_market_signals`'s Kroger-anchored spine (only 3 distinct months exist across the 13 dates). Recomputing it per-date would mean re-implementing ~5 marts' worth of monthly scoring at daily grain — out of scope, and exactly the "weak version" this task was told not to build.
- **Substitution, approved before building — stated plainly:** `directional_pricing_signal` is used instead of `recommended_price_action` for the ACTION measure. **This is a substitution, not the real thing.** `directional_pricing_signal` is a different, already-existing, already-documented field ("SEPARATE from `recommended_price_action` — does NOT change the action cascade"), and it only depends on `gap_direction_stable`, `price_position`, and `price_gap_reliability` — all reproducible per date. The reason for the substitution is a real, standing limitation of the pipeline: nothing retains history for the monthly composite scores (`confidence_score`, `markdown_safety_score`, etc.) that `recommended_price_action` depends on, so a true `recommended_price_action` backtest is not possible without a change to the pipeline itself. A `dbt snapshot` on `mart_pricing_intelligence` would be the natural fix for this — flagged here as a concrete candidate for the data-engineering phase, not attempted in this batch.

Two backtest-only columns were computed fresh (not read from any mart, since the mart versions don't exist at this grain):
- `price_gap_reliability_backtest` — reproduces `mart_pricing_intelligence`'s exact CASE expression, at the per-date grain, from `fct_store_category_weekly`'s own per-date median prices, competitor count, and staleness days. Same vars: `reliability_min_competitor_count=10`, `max_competitor_staleness_days=14`, `reliability_low_gap_threshold=50.0`, `reliability_medium_gap_threshold=25.0`.
- `directional_pricing_signal_backtest` — same substitution logic, at the per-date grain.

## 2. Proof the reproductions match production (required before trusting any downstream number)

Compared both backtest columns against the real `price_gap_reliability` / `directional_pricing_signal` in `mart_pricing_intelligence`, on `2026-08-26` (the one date where the production columns actually exist).

| | n rows compared | Match | Mismatch |
|---|---|---|---|
| `price_gap_reliability_backtest` vs prod | 591 | **591 (100%)** | 0 |
| `directional_pricing_signal_backtest` vs prod | 591 | **591 (100%)** | 0 |

9 of the 600 production rows (3 distinct store×category pairs, each present 3× under a separate grain dimension not relevant here) were excluded from the comparison — independently confirmed as `kroger_collection_date IS NULL` in production, i.e. the cascade's own documented "no fresh Kroger price this period" stale-fallback case (rule 0 of the action cascade). There is no fresh per-date row to compare those against, and that's consistent with what the mart itself says it's doing, not a gap in the reproduction.

**Conclusion: the backtest reproductions are byte-for-byte faithful to production logic wherever production logic exists to check against.** Every result below is measuring what the real pipeline actually does.

## 3. The 618 zero-change transitions — investigated, not assumed

Across all 2,379 T→T+1 sequence-based transitions (all 13 dates, chronological), 618 (26.0%) show `price_gap_pct` byte-identical between T and T+1. Before using this in a band derivation, checked what's driving it:

| | Among the 618 zero transitions |
|---|---|
| `kroger_median_price` unchanged | 618 / 618 (100%) |
| `competitor_median_price` unchanged | 618 / 618 (100%) |
| `competitor_asof_date` unchanged (same underlying SerpAPI pull reused) | 127 / 618 (20.6%) |

The 127 with an unchanged `competitor_asof_date` are **exactly** the `2026-07-15 → 2026-07-16` transitions (127 of the 200 pairs) — the off-cadence day. On that single day, SerpAPI's cache correctly did not re-pull (only 24 hours passed, well inside its 6-day window), so the competitor price genuinely is the same underlying observation carried forward, and Kroger also didn't reprice in 24 hours. **These are the same observation counted twice, exactly the risk flagged before building** — but they are structurally confined to `07-16`.

**Verified this does not reach the primary (calendar) time basis:** re-deriving the zero-change count directly on the calendar-only transition set (2,179 transitions, `07-16` excluded, T→T+1 pairs re-linked so `07-15` pairs directly with `07-22`) gives 496 zero-change transitions, and **0 of these 496 have an unchanged `competitor_asof_date`** — every calendar comparison uses a freshly-pulled competitor snapshot. All 496 have a *different* `competitor_asof_date` at T vs T+1, yet still land on an identical median price — a genuine, independent week-over-week observation of no price movement, not a duplicate. This is plausible for slow-moving CPG categories and is not evidence of a join artifact.

**Action taken:** the magnitude band (below) is derived from the calendar-only set, which is unaffected by this. Sequence-basis results in §5 retain the `07-16`-anchored transitions, but they are flagged explicitly wherever they appear, per the design.

## 4. Magnitude band — re-derived on the clean calendar-only set (locked before use)

Natural-gap method, same approach as `ppi_deadband_pct` (§7.8). Distribution of `ABS(price_gap_pct at T+1 − price_gap_pct at T)`, calendar-only transitions (n=2,179, zero contaminated by stale `competitor_asof_date`, confirmed above):

| Value (pp) | Count |
|---|---|
| 0.00 | 496 |
| 0.02 | 1 |
| **— empty interval, nothing observed —** | **—** |
| 0.14 | 16 |
| 0.26 | 11 |
| 0.28 | 24 |
| ... | continues smoothly upward |

The gap between `0.02` and `0.14` is a genuine empty interval on the full-resolution (2-decimal) data — not just a density dip, a literal zero observations in between. This confirms the preview number from STEP 1 survives the calendar-only cut unchanged.

**Band locked at 0.08 percentage points** — the midpoint of `(0.02, 0.14)`. Any value in that open interval classifies the sample identically, so this is not a fragile pick.

## 5. Results

**Time basis.** Calendar = only the 12 dates spaced exactly 7 (or 14, for T+2/T+3) days apart, `07-16` excluded entirely — **primary**. Sequence = all 13 dates in chronological order, T+1 = literally the next collection — **secondary**. Sequence T+1/T+2/T+3 each include exactly 200 transitions anchored on `07-16` (either as the earlier or later date) with non-standard gaps (1, 6, 8, 13, 15, or 20 days instead of 7/14/21) — flagged, not silently pooled with the rest.

**Data completeness.** 1.6–1.9% of possible pair-transitions at each horizon are excluded for missing rows (a pair not collected on one of the two dates — outlier exclusion, unrelated to this analysis). Zero rows were excluded for `Unknown` direction — no missing prices anywhere in this 13-date window. Excluded rows are NULL in the result, not counted as unstable.

**Null baseline.** Within-pair permutation: for each store×category pair, its own observed label sequence (direction / gap value / action label) is randomly shuffled among its own non-null dates, 500 times, and the same T-vs-T+n metric is recomputed on the shuffled data. This preserves each pair's own marginal tendency (e.g., a category that's structurally almost-always-`Overpriced`) and isolates whether there's a real temporal signal beyond that. Reported as the null mean and its 5th–95th percentile band. **Lift = observed − null mean.** A lift within (or below) the null's own 5–95% band means the observed rate is not distinguishable from chance.

**Sample-size floor.** Cells below N=20 aren't produced by this dataset — smallest reported cell is N=297 (calendar, Medium, T+3). Every number below carries its own N.

### 5a. DIRECTION persistence (`price_gap_direction`, sign match)

**Calendar (primary):**
| Stratum | Horizon | N | Observed | Null mean | Null 5–95pct | Lift |
|---|---|---|---|---|---|---|
| High | T+1 | 1191 | 71.5% | 71.5% | [69.9%, 73.2%] | **−0.1pp** |
| High | T+2 | 1076 | 74.8% | 71.1% | [69.3%, 73.1%] | +3.7pp |
| High | T+3 | 976 | 68.2% | 71.4% | [69.5%, 73.1%] | **−3.2pp** |
| Medium | T+1 | 378 | 95.0% | 92.2% | [90.5%, 93.9%] | +2.8pp |
| Medium | T+2 | 358 | 94.1% | 91.7% | [89.9%, 93.6%] | +2.4pp |
| Medium | T+3 | 297 | 96.0% | 93.8% | [91.9%, 95.6%] | +2.1pp |
| Low | T+1 | 592 | 93.6% | 86.0% | [84.3%, 87.8%] | **+7.5pp** |
| Low | T+2 | 529 | 93.6% | 86.4% | [84.7%, 88.1%] | **+7.2pp** |
| Low | T+3 | 492 | 83.9% | 85.3% | [83.3%, 87.4%] | −1.4pp |
| ALL | T+1 | 2161 | 81.6% | 79.1% | [78.1%, 80.2%] | +2.5pp |
| ALL | T+2 | 1963 | 83.4% | 79.0% | [77.9%, 80.1%] | +4.4pp |
| ALL | T+3 | 1765 | 77.3% | 79.1% | [78.0%, 80.1%] | −1.8pp |

**Sequence (secondary)** — closely matches calendar throughout (largest single-cell difference is 3.3pp); full table in the appendix script output. Confirms the two time bases **agree**.

### 5b. MAGNITUDE persistence (`|price_gap_pct|` within 0.08pp of its T value)

**Calendar (primary):**
| Stratum | Horizon | N | Observed | Null mean | Null 5–95pct | Lift |
|---|---|---|---|---|---|---|
| High | T+1 | 1191 | 19.6% | 12.4% | [11.2%, 13.8%] | +7.1pp |
| High | T+2 | 1076 | 19.2% | 12.6% | [11.1%, 14.0%] | +6.7pp |
| High | T+3 | 976 | 17.3% | 12.6% | [11.1%, 14.3%] | +4.7pp |
| Medium | T+1 | 378 | 21.7% | 16.0% | [13.5%, 18.5%] | +5.7pp |
| Medium | T+2 | 358 | 24.6% | 15.2% | [12.6%, 17.9%] | +9.4pp |
| Medium | T+3 | 297 | 20.2% | 16.1% | [12.8%, 19.2%] | +4.1pp |
| Low | T+1 | 592 | 30.4% | 13.0% | [11.0%, 15.0%] | **+17.4pp** |
| Low | T+2 | 529 | 12.5% | 12.8% | [10.8%, 14.9%] | **−0.3pp** |
| Low | T+3 | 492 | 8.9% | 12.7% | [10.8%, 14.8%] | **−3.7pp** |
| ALL | T+1 | 2161 | 22.9% | 13.2% | [12.3%, 14.2%] | +9.7pp |
| ALL | T+2 | 1963 | 18.4% | 13.1% | [12.0%, 14.2%] | +5.3pp |
| ALL | T+3 | 1765 | 15.5% | 13.2% | [12.1%, 14.4%] | +2.2pp |

Sequence basis: same shape, agrees with calendar (largest difference 4.2pp).

### 5c. ACTION persistence (`directional_pricing_signal` — proxy, see §1)

**Calendar (primary):**
| Stratum | Horizon | N | Observed | Null mean | Null 5–95pct | Lift |
|---|---|---|---|---|---|---|
| High | T+1 | 1191 | 55.8% | 44.2% | [42.1%, 46.3%] | +11.6pp |
| High | T+2 | 1076 | 38.6% | 44.2% | [42.0%, 46.4%] | **−5.6pp** |
| High | T+3 | 976 | 45.6% | 44.7% | [42.5%, 46.9%] | +0.9pp |
| Medium | T+1 | 378 | 69.6% | 56.3% | [53.2%, 59.5%] | **+13.2pp** |
| Medium | T+2 | 358 | 67.9% | 55.6% | [52.2%, 59.2%] | **+12.3pp** |
| Medium | T+3 | 297 | 68.4% | 55.8% | [51.9%, 59.9%] | **+12.5pp** |
| Low | T+1 | 592 | 76.2% | 69.2% | [67.6%, 70.8%] | +7.0pp |
| Low | T+2 | 529 | 73.2% | 69.7% | [67.9%, 71.5%] | +3.5pp |
| Low | T+3 | 492 | 74.2% | 68.3% | [66.3%, 70.1%] | +5.9pp |
| ALL | T+1 | 2161 | 63.8% | 53.2% | [51.9%, 54.4%] | +10.6pp |
| ALL | T+2 | 1963 | 53.2% | 53.1% | [51.9%, 54.4%] | **+0.1pp** |
| ALL | T+3 | 1765 | 57.4% | 53.1% | [51.8%, 54.5%] | +4.3pp |

Sequence basis agrees (largest difference 2.7pp).

## 6. Headline finding: the reliability-predicts-stability claim does NOT hold

The claim worth proving was "High-reliability signals are more stable than Low-reliability ones." **They are not — and the relationship is frequently inverted.**

- **Direction:** High reliability's lift over its own chance baseline ranges from −3.2pp to +3.7pp across the three horizons — statistically indistinguishable from noise throughout, and *negative* at 2 of 3 horizons (T+1: −0.1pp, T+3: −3.2pp). Low reliability shows the largest real lift (+7.5pp, +7.2pp at T+1/T+2). Medium is consistently the most stable in absolute terms (94–96%) but that's mostly base rate (null is already 92–94%).
- **Magnitude:** Low reliability shows the single largest lift anywhere in the table (+17.4pp at T+1) — then collapses to *negative* lift at T+2/T+3. High reliability is the most consistent (+4.7 to +7.1pp across all three horizons) but never the largest.
- **Action:** High reliability actually has a *negative* lift at T+2 (−5.6pp) — meaning High-reliability action labels flip **more** than chance would predict at that horizon. Medium reliability shows the strongest, most consistent lift of any stratum (+12 to +13pp at every horizon).

**Why, structurally:** `price_gap_reliability`'s `High` bucket requires `|price_gap_pct| ≤ 25%`; `Low` catches both genuine data-quality problems (thin competitor sample, stale benchmark) *and* every gap over 50%, regardless of data quality. Checked directly:

| Reliability (backtest) | avg `|gap|` | min | max | n |
|---|---|---|---|---|
| High | 10.2% | 0.17% | 24.87% | 1,439 |
| Medium | 36.9% | 26.09% | 49.95% | 425 |
| Low | 114.6% | 0.73% | 189.49% | 715 |

`High` reliability structurally selects for gaps near zero — and a gap near zero is mechanically far more likely to cross the `Overpriced`/`Underpriced` sign boundary from ordinary week-to-week noise than a gap sitting at 114% average magnitude ever is. `Low` reliability is dominated by extreme, far-from-zero gaps (574 of 715 Low rows are Low purely because the competitor sample was thin — `competitor_product_count < 10` — not because the gap itself was implausible; the remaining 141 are Low specifically because `|gap| > 50%`).

**This was a hypothesis at this point, supported only by a correlation (avg gap 10.2% vs 114.6%) — not yet a demonstration.** It was tested directly by holding magnitude constant and comparing reliability tiers within the same magnitude band. **The test refutes it — see §7.** Something other than (or in addition to) the magnitude confound is driving High reliability's weak direction/magnitude persistence; this analysis does not identify what.

On the ACTION measure's Medium stratum: it shows a real, consistent lift no other stratum matches. **Reported as observed and unexplained — not investigated further.** A single stratum showing a lift while both its neighbours don't is, on priors, more likely to be an artifact of this dataset than a discovery, and chasing it risks exactly the kind of after-the-fact reframing this batch is trying to avoid.

**This is the actual finding of this batch.** Not "signals are stable" — they mostly aren't, once compared to chance. Not "reliability predicts stability" — it largely doesn't, and often predicts the opposite, for a reason this analysis could only partially pin down (see §7). And not "the reliability gate is broken" — it does what it was built to do (§2); it was never built to do this.

## 7. Testing the root-cause hypothesis directly (matched magnitude) — CHECK 1

§6's explanation ("High reliability structurally selects for near-zero gaps, which mechanically sign-flip") was asserted from a correlation, not demonstrated. Tested directly: stratify by `|price_gap_pct|` magnitude band *within* each reliability tier, then re-run direction persistence per (magnitude band × reliability tier) cell against the same within-pair permutation null. If the magnitude confound is the real explanation, reliability tiers should show *similar* persistence once magnitude is matched. If High still underperforms at matched magnitude, the stated root cause is wrong.

**Magnitude bands, natural-gap method (not round numbers).** Raw consecutive-gap search on the sorted `|price_gap_pct|` distribution (165 distinct values, 2,579 rows) didn't show a clean break — the distribution is dense and continuous near zero, and gaps only widen in the tail because observations get sparse there, not because of a real cluster boundary. Used 1D natural-breaks clustering instead (k-means on the 1D distribution, equivalent to Jenks natural breaks — minimizes within-band variance): at k=3, bands are `[0.17, 32.69]`, `[33.84, 103.20]`, `[107.83, 189.49]`, each boundary itself an empty interval in the data. Cut points set at the interval midpoints: **33.265%** and **105.515%**.

- Small: `|gap| ≤ 33.3%`
- Moderate: `33.3% < |gap| ≤ 105.5%`
- Large: `|gap| > 105.5%`

**Structural note:** `High` reliability requires `|gap| ≤ 25%`, which is entirely inside the Small band — so `High` can *only* ever appear in Small, by construction. There is no Moderate/Large cell for `High` to compare against; the Small-band comparison is the only place a genuine 3-tier matched comparison is possible, and it's the one that matters (it's exactly where §6's hypothesis makes its prediction).

**Direction persistence, matched to Small magnitude (`|gap| ≤ 33.3%`), calendar basis:**

| Reliability | Horizon | N | Observed | Null mean | Null 5–95pct | Lift |
|---|---|---|---|---|---|---|
| High | T+1 | 1191 | 71.5% | 71.5% | [70.0%, 73.2%] | **−0.1pp** |
| High | T+2 | 1076 | 74.8% | 71.2% | [69.3%, 72.8%] | +3.6pp |
| High | T+3 | 976 | 68.2% | 71.4% | [69.5%, 73.1%] | **−3.1pp** |
| Medium | T+1 | 114 | 100.0% | 86.7% | [82.5%, 90.4%] | **+13.3pp** |
| Medium | T+2 | 111 | 99.1% | 86.6% | [82.9%, 90.9%] | **+12.5pp** |
| Medium | T+3 | 74 | 87.8% | 80.5% | [74.3%, 86.5%] | +7.3pp |
| Low | T+1 | 50 | 82.0% | 48.7% | [38.0%, 60.0%] | **+33.3pp** |
| Low | T+2 | 47 | 59.6% | 48.5% | [36.2%, 59.6%] | +11.1pp |
| Low | T+3 | 50 | 78.0% | 48.0% | [38.0%, 58.0%] | **+30.0pp** |

(sequence basis: same pattern, largest divergence from calendar is 2.2pp — full table in the script output)

**Sample-size caveat, stated before the verdict:** the `Low`-Small cell (n=50) is an order of magnitude thinner than the `High`-Small cell (n=1,191) — this is not a like-for-like comparison in precision, and the `Low` numbers carry visibly wider null bands as a result (e.g. [38.0%, 60.0%] vs `High`'s [70.0%, 73.2%]). **The refutation below rests primarily on `High` showing ~0 lift at n=1,191 — that result is well-powered on its own and does not depend on the thinner `Low` cell to hold.** The `Low`/`Medium` numbers corroborate the same direction of finding but are held to a lower evidentiary standard given their N.

**Verdict: the hypothesis is REFUTED.** At matched Small-band magnitude, `High` shows essentially zero lift over chance at every horizon (−3.1pp to +3.6pp, n=976–1,191) — a well-powered null result on its own, since if the magnitude-confound explanation were correct, a large, well-sampled cell like this should show something closer to the unstratified `Low`/`Medium` lift once magnitude is matched, and it doesn't. `Low` — at the *same* magnitude range, albeit on a much thinner sample (n=47–50) — shows the largest lift anywhere in this analysis (+33.3pp, +30.0pp), reinforcing rather than driving the conclusion. This directly contradicts the magnitude-confound prediction: if gap proximity to zero were the (sole) explanation, `Low`-reliability rows in the Small band should behave like `High`-reliability rows in the Small band, since they occupy the same magnitude range. They don't. The `Low`-Small cell is composed entirely of rows that are `Low` via thin competitor sample or staleness, not gap magnitude (by construction, since gap ≤ 33.3% rules out the `|gap| > 50%` leg) — the same small gaps as `High`, carrying worse data-sufficiency, yet showing *stronger*, not weaker, real persistence.

**This means §6's stated mechanism is not the (sole) explanation for High reliability's weak persistence.** Something else is driving it. This analysis does not identify what — no alternative mechanism is asserted here, per the standing rule against reframing a falsified hypothesis into a new unverified one.

## 8. Confirming the calendar basis is genuinely clean — CHECK 2

§3 claimed zero stale-`asof` contamination across all 2,179 calendar transitions. Confirmed more rigorously, and at every horizon (not just T+1):

**`competitor_staleness_days` distribution, all 2,379 calendar-basis rows:**

| staleness_days | Count |
|---|---|
| 0 | 2,179 (91.6%) |
| 1 | 200 (8.4%) |

Max observed staleness on the calendar basis is 1 day — nowhere close to the `max_competitor_staleness_days=14` reliability threshold. (The 200 rows at staleness=1 are not the `07-16` artifact — `07-16` isn't part of the calendar basis at all; these are ordinary rows where that week's SerpAPI pull happened to land one day before the Kroger collection.)

**Same-`competitor_asof_date` reuse across T→T+n, calendar basis, all three horizons:**

| Horizon | Valid pairs | Pairs sharing the SAME `competitor_asof_date` |
|---|---|---|
| T+1 | 2,161 | **0 (0.00%)** |
| T+2 | 1,963 | **0 (0.00%)** |
| T+3 | 1,765 | **0 (0.00%)** |

Zero calendar-basis comparisons at any horizon reuse the same underlying Walmart observation. §3's claim holds, and holds more strongly than originally stated — the absence of the `07-16` artifact specifically was verified before, but this confirms there is no carry-forward contamination anywhere in the calendar basis, at any horizon, not only in the case that was already suspected. No exclusion or recomputation was needed; §5's reported rates are already computed on fully independent observations at every transition.

## 9. Where the three measures disagree (not averaged away)

Cross-tab of (direction_stable, magnitude_stable, action_stable) jointly, calendar basis, rows where all three are computable:

| direction | magnitude | action | T+1 (n=2161) | T+2 (n=1963) | T+3 (n=1765) |
|---|---|---|---|---|---|
| stable | stable | stable | 392 | 309 | 190 |
| stable | stable | unstable | 103 | 52 | 83 |
| stable | unstable | stable | 737 | 688 | 647 |
| stable | unstable | unstable | 532 | 588 | 444 |
| unstable | unstable | stable | 250 | 48 | 176 |
| unstable | unstable | unstable | 147 | 278 | 225 |

Only 6 of the 8 possible combinations occur, at every horizon: **whenever direction is unstable, magnitude is always unstable too** (no row shows direction flipping while magnitude stays within the 0.08pp band). That's expected — flipping sign while landing on a byte-identical absolute gap value would require an exact mirror-image price move, essentially never happening at 2-decimal resolution.

The largest single cell at every horizon is **direction stable, magnitude unstable, action stable** (737/1963/1765 → up to 41% of all fully-measured rows at T+1) — the sign of the gap holds, but its size moves by more than 0.08pp, while the coarser reliability-gated action label still matches. This says the pipeline's action label is considerably more forgiving of magnitude drift than a literal 0.08pp band is — expected, since `directional_pricing_signal` only checks direction + reliability, not magnitude at all.

## 10. Limitations

- ACTION measure is `directional_pricing_signal`, not `recommended_price_action` — a substitution, not the real thing (see §1 for why). Flagged as a candidate for a `dbt snapshot` on `mart_pricing_intelligence` in the data-engineering phase, which would make a true monthly-composite backtest possible.
- 13 dates, 3 months. The `Medium` stratum's consistent action-persistence lift (§6) is reported as observed and unexplained — not investigated further in this batch, per the standing rule that a single stratum diverging from both neighbours is more likely an artifact than a discovery.
- §7 refutes the stated magnitude-confound explanation for High reliability's weak direction/magnitude persistence but does not identify a replacement mechanism. That remains open.
- The 0.08pp magnitude band (§4) and the Small/Moderate/Large magnitude bands (§7) are both derived from and validated against this dataset's own distribution; neither is a claim about what magnitude change is economically meaningful to a pricing decision — that's a separate, unaddressed question.
- Permutation null uses 500 draws per cell — stable to the reported precision (checked null 5–95% bands are narrow relative to observed lifts in all but the smallest cells). The smallest cells in §7 (`Low`-Small, n=47–50) have wider null bands than the rest of the analysis; reported, not treated as more certain than the N warrants.

## 11. Reproduction

Scripts (not committed — scratch analysis, results are what's committed here): pull `fct_store_category_weekly` + `int_pricing_temporal_features` from `bronze`, reproduce `price_gap_reliability_backtest` / `directional_pricing_signal_backtest` with the vars above, build calendar/sequence panels, compute T-vs-T+n transitions per horizon/stratum, run 500 within-pair permutations for the null. Seed fixed (`20260830`) for exact reproducibility of the null estimates if re-run against the same `bronze` snapshot. §7's magnitude bands additionally use `sklearn.cluster.KMeans` (1D, k=3, `n_init=20`, `random_state=42`) on the full `|price_gap_pct|` population from `fct_store_category_weekly`.
