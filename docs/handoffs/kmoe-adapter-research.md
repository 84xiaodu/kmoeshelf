# Kmoe adapter research handoff

- Baseline commit: `e980ec8`
- Scope owned: research only; this file (`docs/handoffs/kmoe-adapter-research.md`) is the only repository file owned by this agent
- Status: complete

## Decisions and facts

### Evidence baseline

Research was performed on 2026-08-16 (Asia/Shanghai) against:

- `holdjun/kmoe` at commit `211fb7211f2cc3ca91cdfacb8b76fa7077d201e1` (commit date 2026-03-31).
- `chrisis58/kmoe-manga-downloader` at commit `e88b7296ecd1a5ae1fe787793f87e7ea451953a4` (commit date 2026-08-16).
- Read-only live requests to public `mox.moe` login, search, comic-detail, JavaScript and unauthenticated data/download endpoints. No login was attempted, no credential was supplied, and no download was initiated.

Upstream permalinks should use those commit hashes rather than `main`, because the two projects currently describe different generations of the site protocol.

Both upstream repositories are MIT licensed:

- `holdjun/kmoe/LICENSE`: Copyright (c) 2025 holdjun.
- `chrisis58/kmoe-manga-downloader/LICENSE`: Copyright (c) 2025 chris zheng.

If implementation copies or closely translates upstream code rather than independently implementing the observed protocol, add the applicable copyright and MIT license text to the distribution's third-party notices.

### Priority conclusions for the next agent

1. Prefer the current JSON protocol discovered by the newer `chrisis58` code and confirmed live: detail page `data_book("hash")` -> `GET /data_book.php?h=<hash>`.
2. Keep the older `holdjun` script protocol (`/book_data.php?h=...` containing `parent.postMessage("volinfo=...")`) only as an explicitly detected compatibility parser. Do not silently try both and accept whichever returns an empty result.
3. A 200 response with an empty `voldata` is not proof that a comic has no content. A live unauthenticated request returned HTTP 200 with `msgid: 0`, `bookname: ""`, `volcount: 0`, and `voldata: []`. Treat this as authentication/contract failure, never as a baseline.
4. The live login page currently performs `POST /login_act.php`; `/login_do.php` remains in the legacy HTML form action. Detect the actual endpoint from the fetched login page or prefer `/login_act.php` with a deliberate legacy fallback. Do not blindly submit the password to both endpoints.
5. `GET /getdownurl.php?...&json=1` is the stable abstraction for obtaining a short-lived real URL. Avoid constructing `/dl/...` directly because upstream interpretations of its last path fields disagree and the live page shows those fields are line, format and per-batch file counter, not volume page count.
6. The query parameter named `vip` in `getdownurl.php` is used by the live page as the download line selector (`0` or `1`), not simply as a boolean copy of account VIP state. Line 1 is only exposed to eligible users.
7. Volume array indexes are format-specific. Preserve EPUB and MOBI sizes separately. The current in-worktree `RemoteItem.size_bytes` cannot faithfully hold both values before a format is chosen.
8. Mirror and parser failure must be separate. A reachable mirror returning a valid auth error, quota error or valid not-found result must not be reported as `mirror_unavailable`.

## Upstream concrete files and functions

### `holdjun/kmoe` (older HTML/script protocol, strong fixture coverage)

| File/function | Verified behavior | Reuse assessment |
|---|---|---|
| `src/kmoe/constants.py`: `MIRROR_DOMAINS`, `URLTemplate`, `DownloadFormat` | Mirrors `kxx.moe`, `kzz.moe`, `koz.moe`; format codes MOBI=1, EPUB=2; endpoint templates. | Format codes remain valid. Mirror list is incomplete for the current requested primary (`mox.moe`) and misses newer `kxo.moe`. |
| `src/kmoe/client.py`: `KmoeClient._request_with_failover` | Preferred/active mirror first; retries `ConnectError`; failover on 404/502/503/504; promotes a successful mirror. | Reuse the ordered-active-mirror idea, not the implementation/error policy. See risks below. |
| `src/kmoe/client.py`: `get_download_url` | `GET /getdownurl.php?b={book_id}&v={vol_id}&mobi={fmt}&vip={line}&json=1`; accepts JSON `code=200,url`, absolute plain text, or relative path; recognizes one quota phrase. | Good starting response-shape inventory. Must map HTTP errors before parsing and recognize more quota/auth variants. |
| `src/kmoe/auth.py`: `login` | Posts fields `email`, `passwd`, `keepalive=on` to legacy `/login_do.php`; then validates by fetching `/` and looking for `my.php`. | Fields and post-login validation are useful. Endpoint and success detection are stale/brittle. |
| `src/kmoe/auth.py`: `check_session`, `_build_user_status` | Restores cookies, validates home, fetches `/my.php`, extracts level/UIN/quota. | General validation flow is useful. Do not reuse machine-derived encryption key or string-only login checks. |
| `src/kmoe/search.py`: `search` | All-language search via `/list.php?s={keyword}[&page=N]`; language browse via `/l/{keyword},all,all,sortpoint,{lang},all,BL,0,0/{page}.htm`, with `chn/jpn/eng/oth`. | Preserve as alternative search route candidates. Current route needs mock/live fixture verification for every language. |
| `src/kmoe/parser.py`: `parse_search_results` | Parses `disp_divinfo(...)`; empty tag argument means active 日語/英文/完結/停更; parses `disp_divpage` and `var page_now`. | Best upstream starting point for search fixture behavior. Replace regex-only JavaScript parsing or at minimum handle escapes and validate structure. |
| `src/kmoe/parser.py`: `parse_comic_detail` | Extracts `bookid`, title/author, status, region/language, score, description assignment and cover. | Useful field inventory. Current live detail offers better selectors noted below. |
| `src/kmoe/parser.py`: `extract_book_data_url`, `parse_volume_data` | Older page points to `/book_data.php?h=...`; response contains `parent.postMessage("volinfo=<comma fields>")`. It reads ID [0], type [3] but discards it, title [5], pages [6], MOBI MB [9], EPUB MB [11]. | Keep only as a legacy compatibility parser. It cannot support required content types because it drops field [3]. Comma splitting also fails if a title ever contains a comma/escape. |
| `src/kmoe/comic.py`: `get_comic_detail` | Fetch detail, parse base metadata, then fetch separate volume endpoint. | Correct high-level two-request shape. It incorrectly collapses all mirror exhaustion (not only all-404) into comic-not-found. |
| `src/kmoe/download.py`: `get_download_urls` | Tries lines 0 and 1, then tries returned URLs in order. | Useful fallback concept; line availability should follow account/response semantics. |
| `tests/fixtures/*`, `tests/test_parser.py`, `tests/test_client.py` | Realistic saved search/detail/book-data pages and mock download URL responses. Parser tests assert 21 results, three content examples, sizes and pagination. | Good sources for sanitized legacy fixtures. Do not copy signed URLs or whole unredacted pages into this repository. |

Permanent source root: `https://github.com/holdjun/kmoe/tree/211fb7211f2cc3ca91cdfacb8b76fa7077d201e1`.

### `chrisis58/kmoe-manga-downloader` (current JSON protocol, richer content/download handling)

| File/function | Verified behavior | Reuse assessment |
|---|---|---|
| `src/kmdr/core/constants.py`: `BASE_URL`, `_ApiRoute`, `LoginResponse`, `BookFormat` | Default `kxx`; alternatives `kxo`, `koz`, `mox`; login `/login_act.php`; search `/l/{keyword},all,all,sortpoint,all,all,none/{page}.htm`; detail data constant still says `/book_data.php` but implementation uses `/data_book.php`; format 1/2. Login codes: `m100`, `e400`..`e403`. | Current endpoint and login-code inventory is valuable. Do not rely on the unused/stale `BOOK_DATA` constant. |
| `src/kmdr/core/session.py`: `KmdrSessionManager._probing_base_url`, `validate_url` | Prioritizes configured/book URL host; probes `HEAD /login.php` with 2s timeout; follows redirect signal by changing base; selects one base URL for the session. | Priority/probe concept is useful. A HEAD-only startup probe is insufficient for per-request failover and may reject mirrors that disallow HEAD. |
| `src/kmdr/module/authenticator/LoginAuthenticator.py`: `_authenticate` | `POST /login_act.php`, fields `email`, `passwd`, `keepalive=on`, Referer `/login.php`; parses JSON `msgid`; extracts cookies from response/history; validates via `/my.php`. | This is the best current login flow. Password must remain request-local and be cleared after use by our service. |
| `src/kmdr/module/authenticator/utils.py`: `check_status`, `extract_quota` | `/my.php` redirect to `/login.php` means expired credential; extracts nickname, level, VIP and quota. | Redirect/path validation is useful. Never reuse its `UNLIMITED_QUOTA` fallback on parse failure; unknown quota must remain unknown. |
| `src/kmdr/module/cataloger/SearchCataloger.py`: `catalog` | Authenticated GET of the route above; quote keyword; parse results. | Request shape is current but should not require auth if the page is public unless site behavior proves otherwise. |
| `src/kmdr/module/cataloger/utils.py`: `extract_search_results` | Parses `disp_divinfo`, total pages, alphanumeric comic IDs, title/author/status/tags. | Useful current field map. Regex does not support escaped quotes/backslashes robustly. |
| `src/kmdr/module/lister/utils.py`: `extract_book_info_and_volumes` | Normalizes `/m/c/...` to `/c/...`; fetches detail; on content blocked retries with credentials; detail ID is `input[name=bookid]`; title is `font.text_bglight_big`; detects `data_book("hash")`; calls `/data_book.php?h=...`. | Best current detail/volume flow. Add strict response validation and richer detail metadata. |
| `src/kmdr/module/lister/utils.py`: `__extract_volumes`, `__extract_volume_type` | Reads JSON `voldata`; maps `單行本` -> volume, `番外篇` -> extra, `話` -> serial; reads ID/index/name/size. | Type mapping is directly reusable as protocol knowledge. Its page index and single size choice are incomplete for current live JS. |
| `src/kmdr/core/structure.py`: `VolumeType`, `VolInfo`, `CredentialStatus` | Defines required three types and useful credential states (`active`, `invalid`, `quota_exceeded`, etc.). | Semantics are useful. Do not copy multi-account/pool domain model into the first release. |
| `src/kmdr/module/downloader/ReferViaDownloader.py`: `fetch_download_url` | Calls `getdownurl`, expects JSON `code=200,url`; uses header `X-Km-From: kb_http_down` for actual transfer; maps phrase `達到下載額度限制`. | Use as a test hypothesis; validate whether header is mandatory. Map quota separately. |
| `src/kmdr/module/downloader/DirectDownloader.py`: `construct_download_url` | Builds `/dl/{book}/{volume}/1/{format}/{is_vip}/`. | Do not reuse. It conflicts with the live page's `/dl/{book}/{vol}/{line}/{format}/{file_count}/`. |
| `src/kmdr/module/downloader/download_utils.py`: `download_file`, `download_file_multipart`, `_fetch_content_length`, `_download_part` | Uses temporary files and atomic rename; probes Range with `GET bytes=0-0`; validates part sizes; ordinary accounts default to non-multipart; VIP resume is supported by policy. | Reuse concepts/tests, not code wholesale. There are integrity and fallback issues described below. |
| `src/kmdr/core/utils.py`: `async_retry`, `sanitize_headers` | Retries 500/502/503/504/429/408 and network errors; hides Cookie/Authorization headers. | Error list and header redaction are useful. Add jitter/Retry-After and redact signed URLs/query values. |

Permanent source root: `https://github.com/chrisis58/kmoe-manga-downloader/tree/e88b7296ecd1a5ae1fe787793f87e7ea451953a4`.

## Request paths and fields

### Mirrors

Verified lists conflict by generation:

- Older holdjun: `kxx.moe`, `kzz.moe`, `koz.moe`.
- Newer chrisis58: `kxx.moe`, `kxo.moe`, `koz.moe`, `mox.moe`; `kox.moe` deprecated.
- Live `mox.moe` worked on 2026-08-16 and its footer advertised `kxx`, `kzz`, `koz`.

Recommended service rule:

- Make `mox.moe` available and allow it as the user's preferred primary.
- Keep a validated HTTPS-host allowlist/configuration rather than accepting arbitrary URL fragments.
- Probe candidate mirrors with a public endpoint, but do not assume one probe proves every route works.
- Keep comic identity host-independent: canonical remote comic ID plus a relative detail path such as `/c/50076.htm`.

### Login and session validation

Current live page evidence:

- `GET /login.php`.
- JavaScript creates `FormData` with `email` and `passwd`, then posts to `/login_act.php`.
- Legacy `<form action="/login_do.php" method="post">` still exists.
- Newer upstream additionally sends `keepalive=on` and Referer `/login.php`; this is compatible protocol evidence, not yet live-verified as required.
- `/login_act.php` response is JSON. Current page considers `msgid == "m100"` success.

Known login codes from newer upstream:

| msgid | Meaning | Adapter error |
|---|---|---|
| `m100` | success | none; still validate `/my.php` |
| `e400` | account/password incorrect | invalid credentials, non-retryable |
| `e401` | illegal access/use normal browser | request rejected/challenge, not automatically invalid password |
| `e402` | account deleted | account disabled, non-retryable |
| `e403` | validation expired/refresh page | refresh login page/challenge once, then auth failure |
| missing/unknown/non-JSON | response contract unknown | `site_changed` or structured auth protocol error |

After login, validate with `GET /my.php` using returned cookies. Treat final redirect/path `/login.php`, 401/403, or absence of account-page sentinels as expired/invalid session. Do not decide success from cookie presence alone.

Cookie persistence contract:

- Persist only the minimal cookie jar needed for Kmoe requests, encrypted with the application's configured secret.
- Never persist password, login response body, signed URL or request log with credentials.
- Cookie names, domain scoping and cross-mirror portability remain unverified; store enough cookie metadata (name/value/domain/path/expiry if HTTPX exposes it) to avoid accidental over-broad cookie sending.

### Search

Observed route families:

1. Current/newer: `GET /l/{quoted_keyword},all,all,sortpoint,all,all,none/{page}.htm`.
2. Older simple: `GET /list.php?s={quoted_keyword}&page={page}` (`page` omitted for page 1).
3. Older language filter: `GET /l/{quoted_keyword},all,all,sortpoint,{chn|jpn|eng|oth},all,BL,0,0/{page}.htm`.

Response is HTML with JavaScript calls:

```text
disp_divinfo(div_id, detail_url, cover_url, border,
             tag_jp, tag_en, tag_end, tag_break,
             score, title, author, latest, update_date)
disp_divpage(div_id, search_text, total_pages, ...)
var page_now = "01"
```

The four tag arguments use inverted semantics: an empty string means the corresponding tag is active. Comic ID is the alphanumeric segment in `/c/<id>.htm` (not necessarily numeric). Normalize the returned absolute URL to a trusted relative path after validating host/path.

Parser validity must be separate from result count. A valid empty result should still contain recognized page/list structure. HTML lacking all expected sentinels is `site_changed`, not an empty result.

### Comic detail

Current live detail route: `GET /c/{comic_id}.htm`. Mobile `/m/c/{id}.htm` should be normalized to the desktop path.

Current live metadata evidence:

- Stable book ID: `input[name="bookid"]` value and JS `var bookid`.
- Title: `font.text_bglight_big` (also available in `<title>`).
- Cover: `img.img_book[src]` or `meta[name="og:image"]`.
- Authors: visible links beneath `td.author` after the `作者：` label.
- Status/region/language: text within `td.author` containing `狀態：`, `地區：`, `語言：`.
- Score: `table.book_score` large font.
- Description: JS assignment to `div_desc_content.innerHTML`; the static div contains a placeholder and must not be trusted as the real description.
- Volume capability: module call `data_book("<opaque hash>")`.

The hash is opaque and short-lived/stability-unknown; do not persist it as comic identity.

Current volume request: authenticated `GET /data_book.php?h={hash}`, JSON response.

Legacy compatibility request: `GET /book_data.php?h={hash}`, script response with `parent.postMessage("volinfo=...")`. Only use this when the detail page itself explicitly exposes the legacy URL/call.

### `voldata` parsing contract

The live page JavaScript is the strongest available index map:

| Index | Meaning | Evidence/normalization |
|---:|---|---|
| 0 | remote volume/item ID | stable string; never coerce to integer |
| 1 | recency/download marker | `0` none, `1` recently updated, `2` downloaded/pushed within 90 days; informational only |
| 2 | last/completed marker | `"1"` displays `[完結]`; do not confuse with whole comic status |
| 3 | content type label | `單行本` -> `volume`; `番外篇` -> `extra`; `話` -> `serial`; unknown value must raise `site_changed` |
| 4 | sequence/index | integer-like; for serial groups it is the starting chapter index |
| 5 | item name | required non-empty string |
| 6 | source/archive page count | live page uses for ZIP tab |
| 7 | ebook page count | live page uses for MOBI/EPUB/push tabs; preferred `page_count` for our EPUB/MOBI product |
| 8 | source ZIP size MB | not needed in first release |
| 9 | MOBI size MB | preserve separately |
| 10 | push-compressed size MB | not needed in first release |
| 11 | EPUB size MB | preserve separately |
| 12 | source/management metadata | meaning not fully verified |
| 13 | display date/status text | informational; meaning not fully verified |
| 14 | MOBI build timestamp | optional metadata |
| 15 | EPUB build timestamp | optional metadata |
| 16 | push build timestamp | not needed |

Both upstream parsers use `[6]` as page count. The current live page uses `[7]` for MOBI/EPUB page display and `[6]` only for source ZIP. The old fixture often has equal values in both fields, hiding this bug.

Minimum accepted successful JSON should be an object with a recognizable success/account context and internally consistent fields. Suggested checks:

- `voldata` is a list and `volcount` is integer-like.
- `volcount == len(voldata)` unless a documented server reason proves otherwise.
- For non-empty `voldata`, every item has at least indexes 0..11, known type, non-empty ID/name and numeric page/size fields.
- `bookname`/`bookkey`/`hash` relationship matches the detail request when present.
- A zero-volume response is accepted only if authenticated context and successful response markers are independently established. The unauthenticated 200 response observed live had blank identity fields and `msgid: 0`; reject that shape.
- A parsing failure must leave subscription baseline untouched.

Suggested normalized item identity: `(comic_remote_id, content_type, remote_item_id)`. This is safe even if the site later reuses numeric IDs across type groups.

The current worktree schema has one `size_bytes`; change or supplement it with separate nullable `size_mobi_bytes` and `size_epub_bytes`, or an immutable format-size mapping. Do not choose one upstream index globally.

### Download URL

Preferred request:

```text
GET /getdownurl.php?b={book_id}&v={item_id}&mobi={format_code}&vip={line}&json=1
```

- `format_code`: MOBI=1, EPUB=2.
- `line`: normally 0; line 1 is an alternate/VIP line when available.
- Expected success: JSON object with `code == 200` and non-empty `url`.
- Treat returned URL as short-lived secret data: never persist beyond task need and never log its query string.
- Validate scheme (`https`, with an explicit compatibility decision for `http` if the site ever emits it), host and non-empty path before downloading. Redirect destinations require the same validation policy.
- Newer upstream sends `X-Km-From: kb_http_down` on actual file requests. Whether it is mandatory is not verified; cover it in the fake-service contract and one opt-in live smoke test later.

Live unauthenticated error evidence for `getdownurl.php`:

- HTTP 403.
- HTML/plain response saying illegal access or login state failure, rather than JSON.

Therefore, HTTP status must be mapped before JSON parsing. Do not report this case as site-change or generic network failure.

Known quota message variants across source/live JavaScript:

- Contains `額度不足`.
- Contains `達到下載額度限制`.
- Live UI code `e403` means Kmoe site quota insufficient.

Direct `/dl/` construction should not be part of the adapter contract. The live page constructs `/dl/{book}/{item}/{line}/{format}/{file_count}/`, where `file_count` is the sequential batch-download counter. Holdjun's `build_download_url` passes page count in that position, while chrisis58's direct downloader uses a different five-segment interpretation. Resolve through `getdownurl.php` instead.

## Parsing contract exposed to the application

Recommended stable adapter operations:

```text
login(email, password) -> SessionSnapshot + AccountStatus
validate_session(session) -> AccountStatus
search(query, language, page) -> SearchPage[ComicSummary]
get_comic_details(comic_id) -> ComicDetails + tuple[RemoteItem]
get_download_info(item, format, preferred_line=0) -> ephemeral DownloadInfo
```

Required normalization rules:

- IDs are opaque non-empty strings; allow ASCII alphanumeric IDs observed in search URLs.
- Public API returns trusted relative `detail_path`, not arbitrary upstream absolute URLs.
- Content types are exactly `volume`, `extra`, `serial`.
- Format is exactly `mobi` or `epub`; translate to 1/2 only inside adapter.
- Sizes from decimal MB are approximate display/catalog data. Convert deliberately (site appears to label `M`; whether decimal MB or MiB is unverified). File transfer truth comes from HTTP byte lengths.
- Description HTML must be decoded/sanitized into text; never return executable script or raw untrusted markup to the Web UI.
- Cover URLs are external untrusted URLs and may be signed. Do not log them; consider proxying or enforcing an image-host allowlist later.
- Pagination is 1-based. Preserve `current_page`, `total_pages`, and optionally `has_next`; reject requested page < 1.
- Unknown required fields/type codes produce `site_changed`; optional missing metadata remains `None`.

## Error semantics

Recommended adapter taxonomy and retry behavior:

| Condition | Structured error | Retry/failover |
|---|---|---|
| Bad email/password (`e400`) | `invalid_credentials` (new auth-specific subtype) | no retry, no mirror fan-out with password |
| Deleted account (`e402`) | `account_disabled` | no retry |
| Existing session redirects to login, 401/403 from protected route, unauth data sentinel | `auth_expired` | pause remote tasks; require login; do not try all mirrors unless cookie portability is proven |
| Login challenge rejected (`e401`/`e403`) | `auth_challenge` or auth protocol failure | refetch login page once; no generic network retry |
| Quota phrase/code | `quota_exhausted` | no automatic task retry; retain until quota refresh/manual action |
| Valid comic 404 on every reachable mirror | `not_found` | fail over 404, then aggregate all-404 as not-found |
| One mirror connect/DNS/timeout or 502/503/504 | `network_error` internally, `mirror_unavailable` only after candidates exhausted | retry idempotent GET with bounded exponential backoff + jitter; fail over |
| HTTP 429 | `rate_limited` | honor `Retry-After`; do not immediately hammer all mirrors if they share backend |
| Other 4xx | request/content/access error | normally no retry; preserve status and safe diagnostic |
| HTML/JSON lacks required sentinels, unknown type, impossible field lengths | `site_changed` | no destructive baseline update; alert administrator |
| Content/geo blocked phrase | `content_blocked` | distinguish from expired session; optional proxy guidance, no blind retry |
| Signed URL invalid/expired before transfer | `download_url_expired` | reacquire URL once/few bounded times, not whole login |
| Range ignored/malformed | `range_not_supported` | discard/avoid unsafe partial append and restart full transfer |

Current `src/kmoe_subscriptions/kmoe/errors.py` has `AuthenticationExpired`, `QuotaExhausted`, `SiteChanged`, `NetworkError`, `MirrorExhausted`. It will eventually need at least invalid-credentials/not-found/rate-limit distinctions, even if API initially folds them into broader public codes.

Current `src/kmoe_subscriptions/kmoe/client.py` correctly serializes rate-limit timestamps with a lock and maps 401/403 before response parsing. Follow-up risks:

- Defaults currently omit `mox.moe` and `kxo.moe`.
- Generic failover can replay POST login across mirrors after ambiguous network failure; make request retry policy method/operation-aware.
- All candidate 404s currently become `MirrorExhausted`, not not-found.
- All 403s become auth-expired; detail content blocking/geo restriction may need a different mapping based on route/body.
- A non-failover `RequestError` currently aborts without trying other mirrors.
- Mirror input cleaning should validate an HTTPS hostname rather than merely strip a prefix.

## Safe reuse and parts to avoid

### Safe to reuse as protocol knowledge or independently reimplement

- Endpoint shapes, format codes, login `msgid` meanings and content type labels.
- Ordered preferred/active mirror and promotion after a successful response.
- Separate detail-page fetch from volume-data fetch.
- Search result field mapping and inverted tag semantics.
- Post-login `/my.php` validation and redirect-to-login detection.
- `getdownurl.php` rather than direct `/dl/` construction.
- `.part`/temporary files followed by validation and atomic rename.
- Range probe using `GET Range: bytes=0-0` when HEAD is unreliable, with strict 206/Content-Range checks.
- Sensitive header redaction and format-specific size accounting.

### Do not directly reuse without redesign

- `holdjun.auth._get_machine_key`: derives encryption from hostname + OS username, which is predictable and breaks container migration. Use configured application secret and authenticated encryption with rotation/version metadata.
- `holdjun.login`: ignores login POST body and infers success from home-page substrings.
- `holdjun._request_with_failover`: returns many 4xx/5xx statuses as success, treats all exhausted 404/502/etc. alike, has no jitter/Retry-After, and loses root-cause details.
- `holdjun.get_comic_detail`: converts every `MirrorExhaustedError` into comic-not-found.
- `holdjun.parse_volume_data`: discards content type and comma-splits a JavaScript payload without escape handling.
- `holdjun.build_download_url`: uses volume page count as `/dl/` `file_count`, contradicted by live JavaScript.
- `holdjun.download_file`: writes straight to final path, so interruption can leave a corrupt file that appears final.
- `chrisis58.extract_quota`: defaults missing quota patterns to an enormous `UNLIMITED_QUOTA`; a site change could authorize downloads incorrectly.
- `chrisis58.__extract_volumes`: accepts absent/empty `voldata` without authentication/success validation, reads `[6]` as ebook pages, and only retains EPUB-sized `[11]` for all formats.
- `chrisis58.DirectDownloader`: direct URL structure conflicts with live site.
- `chrisis58.download_file` resumable append: when sending a Range request it does not strictly require status 206 or validate `Content-Range` before appending. A server returning full 200 could corrupt the partial file.
- `chrisis58.download_file_multipart` fallback: fallback call shown does not pass cookies/quota callback, and part failures can be represented as status without always raising immediately. Reimplement around explicit task/file invariants.
- Any CLI console, callback execution, credential pool, local-library JSON or multi-account logic; those conflict with this service's domain and security boundaries.

## Suggested test fixtures

Store only minimized, sanitized fixtures. Replace emails, nicknames, cookie values, opaque hashes, signed image/download URLs and unrelated full-page content. Each fixture should include a short provenance comment (upstream commit or sanitized live structure) without a real credential.

### Authentication

- `login_page_current.html`: contains both legacy form action and JS `/login_act.php`; tests endpoint detection preference.
- `login_success.json`: `msgid=m100` and a minimal message.
- `login_invalid_credentials.json`: `e400`.
- `login_account_disabled.json`: `e402`.
- `login_challenge_expired.json`: `e403`.
- `login_malformed.html` or non-JSON body.
- `profile_normal.html`, `profile_vip.html`: minimal selectors/quota reset/total/used fields.
- `profile_redirect_to_login` fake response: response history + final `/login.php`.

### Search

- `search_results_current.html`: numeric and alphanumeric comic IDs, all inverted tag combinations, pagination/current page.
- `search_escaped_values.html`: HTML tags in title, HTML entities, escaped quote/backslash and non-ASCII author.
- `search_empty_valid.html`: recognized list/page structure with zero results.
- `search_site_changed.html`: HTTP 200 login/challenge/unrelated HTML that must raise `site_changed`, not return empty.
- Route-level mock cases for all language codes and page > 1.

### Detail and volumes

- `comic_detail_current.html`: title, multiple authors, cover placeholder, status/region/language, description JS and `data_book(hash)`.
- `comic_detail_mobile.html`: ensures `/m/` normalization.
- `comic_detail_blocked.html`: exact blocked-content sentinel, sanitized.
- `volume_data_all_types.json`: at least one `單行本`, `番外篇`, `話`; deliberately make [6] and [7] different and MOBI [9] and EPUB [11] different so index bugs fail.
- `volume_data_unknown_type.json`: must raise `site_changed`.
- `volume_data_unauthenticated_empty.json`: sanitized live shape with blank identity, `msgid=0`, `volcount=0`, `voldata=[]`; must raise auth/contract error.
- `volume_data_valid_empty.json`: only after a successful authenticated shape is captured and verified; must be distinguishable from unauthenticated empty.
- `volume_data_count_mismatch.json`, `volume_data_short_row.json`, `volume_data_bad_numeric.json`.
- `legacy_book_data.html`: minimized `parent.postMessage(volinfo=...)` records for all three types and a title edge case.

### Download URL and transport

- JSON success with an obviously fake HTTPS URL.
- JSON error for each quota phrase.
- HTTP 403 HTML auth error.
- JSON missing `url`, unknown `code`, invalid URL scheme/host, relative URL if intentionally supported.
- Signed-URL expiry followed by successful reacquisition.
- Range probe 206 with `Content-Range: bytes 0-0/total`; 200 ignoring Range; malformed range; 416; unknown total.
- Resume response starting at wrong byte must discard/restart, never append.
- Content-Length mismatch, zero-length file, wrong extension/content type, cancellation and restart recovery.

### Mirror fake service

- Preferred connect failure then alternate success and promotion.
- 502/503/504 failover; retry count and backoff deterministically injected.
- 429 honors Retry-After without mirror stampede.
- all-404 detail -> not-found; mixed 404+network -> diagnostic/network outcome, not false not-found.
- 401/403 protected route -> auth-expired without trying every mirror.
- login POST ambiguous timeout -> no credential fan-out.
- active mirror changes while cookie is valid/invalid, documenting the chosen portability policy.

## Changes

- Added `docs/handoffs/kmoe-adapter-research.md` as durable research memory.
- No application code, migration, test or other handoff file was modified.

## Verification

Commands/evidence used:

```text
git -C /tmp/kmoe-upstream-holdjun rev-parse HEAD
# 211fb7211f2cc3ca91cdfacb8b76fa7077d201e1

git -C /tmp/kmoe-upstream-chrisis58 rev-parse HEAD
# e88b7296ecd1a5ae1fe787793f87e7ea451953a4

rg/nl/sed over the exact upstream files named above

read-only GET https://mox.moe/login.php
read-only GET a public mox.moe search page
read-only GET https://mox.moe/c/50076.htm
read-only GET the public /zzfunc.js referenced by that page
read-only unauthenticated GET /data_book.php?h=<page hash>
read-only unauthenticated GET /getdownurl.php with an invalid volume ID
```

Observed live results relevant to tests:

- Login page contains JS `/login_act.php` plus legacy form `/login_do.php`.
- Detail page contains `data_book(hash)` and live JS calls `/data_book.php?h=...`.
- Unauthenticated data endpoint returns a 200 empty sentinel, not a login redirect.
- Unauthenticated download-URL endpoint returns HTTP 403 with a non-JSON login-state message.
- Search page contains `disp_divinfo`, `disp_divpage` and `var page_now`.
- Live volume rendering uses ebook pages [7], MOBI size [9], EPUB size [11].

No tests were run against a real authenticated account, and no live response containing private data was saved in the repository.

## Unresolved

These are not facts and must not be silently assumed:

1. Exact successful `/data_book.php` `msgid`, `hash`, `bookkey`, `bookname` invariants; an authenticated sanitized fixture is still needed.
2. Whether truly empty comics exist and how a valid authenticated empty response differs from the observed unauthenticated sentinel.
3. Cookie names, expiry, SameSite/domain attributes and whether one session is portable across `mox`, `kxx`, `kxo`, `kzz`, `koz`.
4. Whether `keepalive=on` is required/accepted by current `/login_act.php`; live JavaScript did not send it, newer CLI does.
5. Whether current server still supports `/login_do.php` programmatically and what its success/failure body contract is.
6. Current language-filter route semantics for `chn/jpn/eng/oth` on every mirror.
7. Whether `disp_divinfo` arguments can contain JavaScript escapes/commas beyond current regex assumptions.
8. Whether remote item IDs can collide across types; use composite identity until proven impossible.
9. Whether catalog size `M` is decimal MB or MiB; never use it as final byte-integrity truth.
10. Meaning/stability of `voldata` indexes 12 and 13 beyond current display usage.
11. Complete current `getdownurl.php` error code catalog and signed URL lifetime.
12. Whether `X-Km-From: kb_http_down` is mandatory and which redirect/CDN hosts are legitimate.
13. Actual Range behavior by account tier, line and CDN; upstream reports ordinary accounts may not support multipart/resume.
14. Whether a 403 detail response means expired auth, geo/content block, or both; route/body-aware classification is required.
15. Mirror rate limits and whether mirrors share a backend/rate-limit bucket.

## Next action

Reconcile the in-progress adapter with the priority conclusions above before adding parsers: add current `mox.moe` support, make login POST retry policy non-replaying, define format-specific item sizes, and write the unauthenticated-empty `data_book` fixture/test first. Then implement current JSON parsing with strict sentinels, followed by the explicitly detected legacy parser.
