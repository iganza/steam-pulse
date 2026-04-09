# Metadata Context Wiring (Three-Phase Pipeline)

> **Must land in the `feature/three-phases-analysis` branch before merge.**
> The three-phase analyzer (`scripts/prompts/three-phase-analysis.md`) plumbs
> `metadata: GameMetadataContext | None` all the way through `analyze_game`,
> `build_synthesis_request`, and the synthesis user-message builder — but
> both call sites pass `metadata=None`. As shipped, the entire
> `store_page_alignment` section and the Price / Platforms / Genres / Tags /
> Metacritic context block of the synthesis prompt are dead code for every
> analyzed game. This spec wires the already-built `GameMetadataContext`
> into both the realtime and batch synthesis paths.

---

## Background

`library_layer/models/metadata.py` already defines:

- `GameMetadataContext` — a pydantic bundle of store-page fields
  (`short_desc`, `about_the_game`, `price_usd`, `is_free`, `tags`, `genres`,
  `platforms`, `deck_status`, `achievements_total`, `metacritic_score`).
- `build_metadata_context(game, tags, genres) -> GameMetadataContext` —
  pure function, no I/O, strips HTML from `about_the_game` and truncates
  to 1500 chars.

`TagRepository` already exposes `find_tags_for_game(appid)` and
`find_genres_for_game(appid)` for the per-game row sets.

`library_layer/analyzer.py::_build_synthesis_user_message` already has the
entire conditional rendering path for metadata:

- Lines ~170-188: the "Price / Platforms / Steam Deck / Genres / Tags /
  Achievements / Metacritic" context block — gated on `metadata is not None`.
- Lines ~190-211: the `<store_description>` block + the
  `store_page_alignment` section of `<section_definitions>` + the two extra
  `<self_check>` items — gated on `metadata is not None and
  metadata.about_the_game is not None`.

`GameReport.store_page_alignment: StorePageAlignment | None = None` exists
in `analyzer_models.py` and is ready to receive the LLM output.

**Nothing needs to change in the prompt, the models, or the repository
layer.** The only missing piece is the handlers never constructing and
passing `GameMetadataContext`. That is the entire scope of this spec.

---

## Goal

Every three-phase synthesis call — realtime and batch — receives a
fully-populated `GameMetadataContext` built from the `Game` row plus the
game's tag and genre rows. Every fresh `GameReport` persisted after this
lands carries a non-null `store_page_alignment` (when the game has a
non-empty `about_the_game`), and the synthesis prompt's genre_context /
dev_priorities reason with price, platforms, genres, and tags in-context.

---

## Files to Modify

### 1. `src/lambda-functions/lambda_functions/analysis/handler.py`

- Add a module-level `_tag_repo: TagRepository = TagRepository(get_conn)`
  next to the existing repo singletons.
- In `handler()`, after the `game = _game_repo.find_by_appid(req.appid)`
  check, build the metadata context:
  ```python
  tags = _tag_repo.find_tags_for_game(req.appid)
  genres = _tag_repo.find_genres_for_game(req.appid)
  metadata = build_metadata_context(game, tags, genres)
  ```
- Pass `metadata=metadata` (not `None`) into the `analyze_game(...)` call.
- Add the `TagRepository` and `build_metadata_context` imports at the top
  of the file (NOT inside the handler — per the project's top-of-file
  import rule).

### 2. `src/lambda-functions/lambda_functions/batch_analysis/prepare_phase.py`

- Add a module-level `_tag_repo: TagRepository = TagRepository(get_conn)`.
- In `_prepare_synthesis`, after the `game = _game_repo.find_by_appid(appid)`
  guard, build `metadata` the same way as the realtime handler and pass
  it into `build_synthesis_request(..., metadata=metadata, ...)`.
- Add the imports at the top of the file.

**Do not** wire metadata into `_prepare_chunk` or `_prepare_merge` —
chunk extraction and merge do not receive metadata in the current prompt
design, and this spec explicitly does not expand that.

### 3. (Optional hardening) `src/library-layer/library_layer/analyzer.py`

The existing `_build_synthesis_user_message` has `metadata: ... = None`
default params. That default is the reason this bug existed silently —
a caller that forgets to pass metadata gets a degraded prompt with no
runtime error. Tighten it in a follow-up: make `metadata` and `temporal`
required keyword arguments (`metadata: GameMetadataContext | None`, no
default). Callers that genuinely have nothing pass `metadata=None`
explicitly. This matches the project's "no defaults in helpers" rule
called out in `three-phase-analysis.md`.

This hardening is **not required** for the fix to work, but if we don't
do it the next regression of this exact shape will also be silent.

---

## Tests (required)

### 1. `tests/handlers/test_analysis_handler.py` (or equivalent)

Add or extend a test that drives the realtime handler with a mocked
`ConverseBackend` and asserts the `GameMetadataContext` passed into
`analyze_game` is non-None and has the expected `genres`, `tags`,
`price_usd`, `about_the_game` fields populated from the test Game row.
If the handler doesn't have an existing test file, the assertion can live
as a spy/monkeypatch on `analyze_game` inside a minimal handler-invocation
test.

### 2. `tests/handlers/test_prepare_phase.py`

Extend the existing synthesis-prepare test to assert
`build_synthesis_request` is called with a non-None `metadata`. The test
already stubs `_game_repo` and `_merge_repo`; stub `_tag_repo` the same
way.

### 3. `tests/services/test_analyzer_three_phase.py`

Add a focused test that calls `_build_synthesis_user_message` with a
populated `GameMetadataContext` (including a non-empty `about_the_game`)
and asserts the rendered prompt contains:
- `"<store_description>"`
- `"store_page_alignment"`
- the price string, the first genre, the first tag

and a matching negative test that asserts those strings are **absent**
when `metadata=None`. This is the regression harness for the silent
failure mode.

### 4. End-to-end sanity

`poetry run pytest tests/services/test_analyzer_three_phase.py tests/handlers/test_prepare_phase.py tests/handlers/test_collect_phase.py tests/handlers/test_analysis_handler.py -q`
must be green. `poetry run ruff check .` must be clean.

---

## Out of Scope

- Frontend rendering of `store_page_alignment`. The API surface already
  returns the full `GameReport` JSON; whatever the frontend currently
  does with the field (including "ignore it") is unchanged.
- New matview columns / benchmarks derived from `store_page_alignment`.
- Back-filling `store_page_alignment` on existing reports. The next
  scheduled re-analyze (stale refresh) will pick it up naturally. If
  operator-triggered backfill is desired it can be its own ticket.
- Expanding metadata into the chunk or merge prompts. Only synthesis
  receives metadata, matching the current prompt design.

---

## Acceptance Criteria

1. Both realtime (`analysis/handler.py`) and batch synthesis
   (`batch_analysis/prepare_phase.py::_prepare_synthesis`) construct a
   `GameMetadataContext` via `build_metadata_context(game, tags, genres)`
   and pass it into the analyzer / request builder. `metadata=None`
   appears in **zero** production call sites after this lands (grep must
   return nothing for `metadata=None` under `src/lambda-functions/`).
2. The regression test in `test_analyzer_three_phase.py` asserts
   `<store_description>` and `store_page_alignment` are rendered when
   metadata is populated.
3. A spot-check re-analysis of one real game (e.g. appid 440, via the
   admin reanalyze path once deployed by the user — NOT by Claude)
   produces a `GameReport` row whose `report_json.store_page_alignment`
   is non-null and whose `audience_match` is one of the three literal
   values.
4. All existing three-phase tests still pass; ruff clean.
