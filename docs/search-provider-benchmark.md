# Search provider benchmark: Serper vs Parallel

## Headline

- **Latency: search got roughly twice as fast.** Median company search 2,979 ms -> 1,316 ms; median search time per lead 5,050 ms -> 2,286 ms (2.2x faster), on 3 provider HTTP requests per lead instead of 6.
- **Evidence depth: about an order of magnitude more text to score from.** Median raw characters returned by the company search 2,089 -> 19,789 (9.5x more) from half as many hits, because Parallel returns objective-selected page excerpts where Serper returns one-line SERP snippets.
- **Provenance: dates arrive with the evidence.** Share of kept company snippets carrying a `publish_date` 15% -> 56%, which is what makes the 5-year recency filter on unit counts meaningful rather than aspirational.
- **Website step: the biggest single win, and it comes from Extract, not Search.** Website evidence was obtained on 71% of runs with the raw HTML parser vs 96% with Parallel Extract -- the HTML parser loses to bot walls, JavaScript-rendered sites and PDFs that Extract reads through.
- **Scoring: Company Fit rose only once Extract was in the loop.** Median Company Fit 18.5 (`serper`) -> 14.5 (`parallel-search`) -> 30.0 (`parallel`). Swapping the search provider alone did not move it; reading the company's own site did. Low-confidence runs fell from 5 to 1.
- **Counter-results, stated plainly.** Serper's per-query fan-out returns more raw property hits, so it clears the strict address filter on slightly more runs (96% vs 79% of runs); Property Fit is the one axis where the migration did not help. And richer evidence cuts both ways on the non-real-estate control: see the Stripe row in the per-lead table, where more retrieved text gives the classifier more leasing-adjacent language to over-read.

## Methodology

Run on 2026-09-01. Every configuration goes through the identical enrichment code path (`enrich_company` -> `score_lead` with an empty `MarketMetrics()`), the identical 14-lead panel, the identical queries, result caps, ranking, address filter and OpenAI classifiers. The only thing that changes is which provider answers, applied by mutating the cached `Settings` singleton (`WEB_SEARCH_PROVIDER`, `WEB_EXTRACT_ENABLED`) before each run. The company step asks for 3 keyword queries in `fast` mode with `max_results=5` and a 5-year `after_date` filter; the property step asks for 2 keyword queries in `basic` mode with `max_results=5` and `location=us`. Parallel takes all queries in a single request; Serper has no multi-query endpoint, so the fallback path issues one `num=5` request per query (3 company requests, 2 property requests) and merges the organic results by URL. Each lead ran 2x per configuration, and the configuration order is rotated per lead so no provider systematically eats the cold-cache cost. Latency figures are medians over per-call rows; scoring figures are medians over per-run rows. Total wall clock: 15.4 min.

Configurations:

- **`serper`** - Serper search + raw HTML website parse (pre-migration stack)
- **`parallel-search`** - Parallel Search + raw HTML website parse (Search API isolated)
- **`parallel`** - Parallel Search + Parallel Extract (current stack)

## 1. Latency

| Config | Company search (median / p90) | Property search (median / p90) | Extract (median / p90) | HTML fallback (median / p90) | Provider HTTP requests per lead | Median search time per lead | Median total enrichment |
|---|---|---|---|---|---|---|---|
| `serper` | 2,979 / 3,651 ms (n=28) | 2,102 / 2,946 ms (n=28) | - | 465 / 870 ms (n=28) | 6.0 | 5,050 ms | 11,240 ms |
| `parallel-search` | 1,199 / 2,052 ms (n=28) | 1,255 / 1,862 ms (n=28) | - | 366 / 729 ms (n=28) | 3.0 | 2,479 ms | 9,657 ms |
| `parallel` | 1,316 / 1,896 ms (n=28) | 1,042 / 1,984 ms (n=28) | 772 / 907 ms (n=28) | 394 / 394 ms (n=1) | 3.0 | 2,286 ms | 10,558 ms |

"Median search time per lead" sums the company and property search calls for one run; "median total enrichment" is the whole `enrich_company` call, which also includes the website step, the Nominatim geocode and the two OpenAI classifier calls, so it is not provider-attributable on its own.

## 2. Evidence quality

### 2a. Company evidence

| Config | Median raw hits per lead | Median raw chars returned | Median kept snippets | Share with unit-count evidence | Share on the company's own domain | Share matching the enrichment domain | Share with publish_date |
|---|---|---|---|---|---|---|---|
| `serper` | 11.0 | 2,089 | 5.0 | 24% | 21% | 19% | 15% |
| `parallel-search` | 5.0 | 17,517 | 5.0 | 27% | 19% | 21% | 63% |
| `parallel` | 5.0 | 19,789 | 5.0 | 31% | 20% | 31% | 56% |

"Raw chars returned" is the cleaned passage text the provider handed back for the three company queries, before ranking and before the densest-400-char window is cut. Snippet shares are computed over every kept company snippet (runs x snippets), not per run. "The company's own domain" is the lead's email domain, which is provider-independent; "the enrichment domain" is whatever domain the website step settled on, so it reads 0% whenever that step failed and is the weaker of the two measures.

### 2b. Property and website evidence

| Config | Median raw property hits | Median address-matched property snippets | Share of runs with any address match | Website step success | Website step outcomes | Median website snippet chars |
|---|---|---|---|---|---|---|
| `serper` | 7.0 | 4.0 | 96% | 71% | html: 20 / html_failed: 8 | 669 |
| `parallel-search` | 5.0 | 3.0 | 82% | 68% | html: 19 / html_failed: 9 | 668 |
| `parallel` | 5.0 | 3.5 | 79% | 96% | extract: 27 / html_failed: 1 | 694 |

Website outcomes: `extract` = Parallel Extract produced the evidence; `html` = the raw HTML parser did; `html_failed` = a candidate URL was found but fetching and parsing it returned nothing usable; `no_candidate` = the company search produced no usable non-social URL to read in the first place.

## 3. Scoring outcomes

| Config | Median company fit | Median property fit | Median final score | Confidence High/Medium/Low | Signals from OpenAI classifier | "not source-backed" rejections | Median missing-data entries | Fit labels |
|---|---|---|---|---|---|---|---|---|
| `serper` | 18.5 | 12.0 | 31.5 | 20 / 3 / 5 | 87% (146/168) | 3 | 1.0 | Likely fit: 5 / Strong fit: 9 / Unclear fit: 14 |
| `parallel-search` | 14.5 | 10.0 | 29.0 | 20 / 6 / 2 | 85% (142/168) | 4 | 1.0 | Likely fit: 3 / Strong fit: 10 / Unclear fit: 15 |
| `parallel` | 30.0 | 10.0 | 38.5 | 17 / 10 / 1 | 85% (143/168) | 1 | 1.0 | Likely fit: 4 / Strong fit: 11 / Unclear fit: 13 |

Company Fit is out of 39 and Property Fit out of 16. Market Fit is 0 for every run because `MarketMetrics()` is empty, which is deliberate: it holds the non-provider half of the score constant. `"not source-backed"` counts the signals the OpenAI classifier proposed but that failed literal-substring verification against the retrieved evidence, so they fell back to rules.

## 4. Per-lead results

| Lead | Segment | serper company/property/conf | parallel-search company/property/conf | parallel company/property/conf |
|---|---|---|---|---|
| Greystar - The Eugene, 435 W 31st St, New York NY | large multifamily | 39 / 16 / High | 39 / 16 / High | 39 / 16 / High |
| Greystar - Lamar Union, 1100 S Lamar Blvd, Austin TX | large multifamily | 39 / 13 / High | 39 / 14 / High/Medium | 39 / 16 / High |
| Asset Living - Novel Midtown, 855 Peachtree St NE, Atlanta GA | large multifamily | 34 / 16 / High | 39 / 15 / High | 39 / 16 / High |
| AvalonBay Communities - AVA Nob Hill, 965 Sutter St, San Francisco CA | large multifamily | 24 / 13 / Medium/Low | 34 / 13 / High | 34 / 13 / High |
| Lincoln Property Company - OneEleven, 111 W Wacker Dr, Chicago IL | large multifamily | 32 / 16 / High | 22 / 13 / High | 30 / 13 / High |
| Camden Property Trust - Camden Rainey Street, 91 Rainey St, Austin TX | large multifamily | 13 / 12 / High | 13 / 16 / High | 16 / 14 / High |
| Cortland - Cortland at the Village, 4001 Preston Rd, Plano TX | large multifamily | 32 / 8 / High | 28 / 8 / High | 34 / 8 / High |
| Bozzuto - Union Wharf, 901 S Wolfe St, Baltimore MD | mid multifamily | 34 / 12 / High | 32 / 5 / High | 34 / 5 / High |
| Byram Properties - 500 S Congress Ave, Austin TX | small operator | 10 / 11 / High/Low | 11 / 11 / Medium | 9 / 11 / Medium |
| Small Properties LLC - 1010 East 178th St, Bronx NY | small operator | 10 / 12 / Low | 4 / 9 / Low | 24 / 9 / High/Low |
| Mom & Pop Rentals - 123 Maple Ave, Des Moines IA | small operator | 13 / 9 / Medium/Low | 13 / 9 / Medium | 13 / 9 / Medium |
| JLL - One World Trade Center, 285 Fulton St, New York NY | commercial real estate | 10 / 5 / High/Medium | 13 / 6 / High | 13 / 6 / Medium |
| CBRE - Salesforce Tower, 415 Mission St, San Francisco CA | commercial real estate | 9 / 5 / High | 9 / 6 / High | 10 / 6 / Medium |
| Stripe - 354 Oyster Point Blvd, South San Francisco CA | non-real-estate control | 0 / 4 / High | 14 / 4 / High/Medium | 10 / 4 / Medium |

Values are medians across repeats; confidence lists every level observed for that lead.

## 5. Caveats

- **Small n.** 14 leads x 2 repeats per configuration. Differences of a point or two in median score are noise; the direction and size of the latency and evidence-coverage gaps are the signal.
- **The live web is nondeterministic.** Result sets, page availability and provider latency all move between runs, and the OpenAI classifiers are sampled, so re-running this will not reproduce the numbers exactly.
- **This measures provider quality, not code quality.** The Serper path feeds the same post-processing -- excerpt cleaning, densest-window selection, ranking, dedupe, address filter, classifiers -- as the Parallel path. What differs is what each provider returns: Serper returns short SERP snippets, Parallel returns objective-selected page excerpts.
- **Extract is Parallel-only.** The `parallel` configuration therefore bundles two products, which is why `parallel-search` exists: it isolates the Search API by keeping the old raw-HTML website parser. Serper has no extraction product, so `serper` + Extract is not a configuration that could ship.
- **Serper spends more requests for the same work.** Its per-query endpoint means 5 search requests per lead (3 company + 2 property) against Parallel's 2, plus the website read: 6 provider HTTP requests per lead vs 3. That is a structural property of the API, not an artifact of this harness, and it is a real part of the latency gap.
- **Cost is not measured here.** The two providers price differently per request and Extract bills separately; this benchmark only covers latency, evidence and score quality.

