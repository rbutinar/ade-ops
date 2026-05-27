---
status: preview
since: 2026-05-26
related: pbir-create, pbir-clone-template, <client>-pbi-loop, pbir-report
---

# /pbir-add-page — Incremental page addition to existing PBIR report

Add a new page to an existing **PBIR** report folder. Two modes shipped in MVP:

| Mode | Trigger | What happens |
|---|---|---|
| **Spec build** | `--spec page-spec.yaml` | Build the new page from a YAML spec, reusing the same visual primitives as `/pbir-create` |
| **Clone from existing page** | `--clone-from "Source Page Name"` | Copy the source page's `page.json` + `visuals/*` subtree, regenerate page_id and visual_ids, rename to the new `displayName` |

> **Status: `preview`**. Engine validated by synthetic smoke test (18 assertions across 2 modes + insert_at + YAML file + 3 failure modes). **Not yet battle-tested on a real CR add-page event.** Promotion criteria below.

Interactive prompt mode (the third backlog item) is **deferred** to a later iteration. The skill body uses YAML spec or clone-from for now.

## When to use this skill

| Scenario | Use |
|---|---|
| Add a new page to an existing report (CR-driven <client> pattern) | **This skill** (`preview`) |
| Build a brand-new report from scratch | `/pbir-create` (`preview`) |
| Clone an entire report (whole-report granularity) and adapt fields | `/pbir-clone-template` (`preview`) |
| Iterate on an existing page or report | `/<client>-pbi-loop edit {report-ref}` |
| Deploy an existing `.Report` folder | `/pbir-report deploy` |

## Prerequisites

- An existing PBIR `.Report` folder under `distributions/{client}/projects/{project}/src/power_bi/` (or any project rooted at `config/project.yaml`)
- The folder must already contain valid `definition/pages/pages.json` (true for any report pulled by the engine or saved by `/pbir-create`)
- For **clone-from** mode: the source page's `displayName` (case-sensitive, exact match)
- For **spec** mode: a YAML file describing the new page (shape below)
- `FabricConnector` credentials when pushing (`az login` against the project's identity)

## Usage

```
/pbir-add-page {ReportRef} --page-name "New Page Name" --env {env} --spec page-spec.yaml
/pbir-add-page {ReportRef} --page-name "New Page Name" --env {env} --clone-from "Source Page Name"
/pbir-add-page {ReportRef} --page-name "New Page Name" --env {env} --clone-from "Source" --insert-at 1
/pbir-add-page {ReportRef} --page-name "New Page Name" --env {env} --spec page-spec.yaml --set-active
/pbir-add-page {ReportRef} --page-name "New Page Name" --env {env} --spec page-spec.yaml --no-push
```

Flags:

- `--spec page-spec.yaml` and `--clone-from "Source"` are **mutually exclusive** — exactly one must be provided.
- `--insert-at N` — 0-based index in `pageOrder`. Default: append at end. Negative indices follow Python list semantics.
- `--set-active` — switch `activePageName` to the new page. Default: preserve current active page.
- `--no-push` — only mutate the local `.Report` folder, skip the Fabric deploy + Playwright verify steps. Useful when batching multiple add-page calls before a single push.

`{ReportRef}` resolves to a `.Report` folder relative to the project root, or a `Report` GUID that maps via the project's overlay.

## Spec manifest format (when `--spec` is provided)

```yaml
page:
  name: "Forecast Detail"            # required; matches --page-name (engine reads name from here too)
  background_color: "#FAFAFA"        # optional
  visuals:
    - type: card
      title: "Total Forecast"
      value: { entity: FactSales, property: Total Forecast, _type: measure }
      position: { x: 10, y: 10, width: 300, height: 80 }
    - type: bar_chart
      title: "Forecast by Channel"
      category: { entity: FactSales, property: sales_channel, _type: column }
      values:
        - { entity: FactSales, property: Total Forecast, _type: measure }
      position: { x: 10, y: 100, width: 600, height: 300 }
```

Supported visual types in MVP: `banner`, `card`, `card_visual`, `bar_chart` (with `horizontal: true|false` for the orientation), `column_chart`, `table`, `textbox`. Same set as `/pbir-create`. Visual types outside this list raise an explicit error.

## Behavior steps

### Step 0 — Resolve project + env + report

Read `config/project.yaml` and overlay to locate the target `.Report` folder under `src/power_bi/{ReportRef}.Report/`. Read `definition/pages/pages.json` to verify the report has a valid pages structure. If the folder is missing or invalid, halt with an explicit error pointing the user at the iterative PBI loop skill (pull first if the report exists only on Fabric).

### Step 1 — Validate input

- Exactly one of `--spec` / `--clone-from` must be set (else: ValueError).
- `--page-name` must not collide with any existing page's `displayName` in this report (else: ValueError with the list of existing names).
- For `--clone-from`: the source `displayName` must resolve to a page folder (else: FileNotFoundError).
- For `--spec`: the YAML must have a top-level `page:` block with a `name:` field.

### Step 2 — Apply add_page

Call `core.platforms.powerbi.pbir_engine.add_page_to_report(...)` with the resolved arguments. The engine writes:

- A new page folder `definition/pages/{new_page_id}/` containing `page.json` + `visuals/{visual_id}/visual.json` for each visual.
- An updated `definition/pages/pages.json` with the new `page_id` appended (or inserted) to `pageOrder`, and `activePageName` set per `--set-active`.

Page IDs and visual IDs are fresh 20-char hex GUIDs to prevent collision with the source page (anti-goal: never reuse GUIDs).

### Step 3 — Push (unless `--no-push`)

Invoke the project's `FabricConnector.push_object` for the report, same as `/pbir-report deploy`. The engine repacks the `.Report` folder as InlineBase64 parts and calls `updateDefinition` on the Fabric Report item.

Pre-push, the skill prints a one-line summary of what's about to happen (target workspace + report displayName + new page count). User confirms before the upload.

### Step 4 — Playwright verify (unless `--no-push --no-verify`)

Open the Power BI service URL with `&pageName={new_page_id}` anchor. Snapshot the new page. If the page renders cleanly, mark success. If not, surface the rendering issue and propose `/<client>-pbi-loop edit` for iteration.

### Step 5 — Log

Append a line to the project's `ops.log`:

```
{ISO_timestamp} | ops | ADD_PAGE | {env} | power_bi: {ReportRef} +'{PageName}' (id={new_page_id[:8]}…) | {ok|fail}
```

## Anti-goals

- **No auto-determination** of the insertion position — caller chooses `--insert-at` explicitly; default is append.
- **No GUID reuse** when cloning — fresh page_id + fresh visual_ids every time (collision = silent rendering corruption).
- **No mutation of the source page** when cloning — read-only on the source.
- **No field rebinding** in this skill — if the cloned page should point at a different model / entity / property, use `/pbir-clone-template` at the report level OR follow with a manual edit via `/<client>-pbi-loop edit`. Mixing concerns blurs the responsibility line.
- **No auto-deploy after add** when `--no-push` is set — explicit control over the push step.
- **No interactive prompt loop** in MVP — use `--spec` or `--clone-from`. Interactive mode is on the backlog.
- **No PBIR-Legacy support** — only modern PBIR `.Report` folders with `definition/pages/{page_id}/` structure.

## Preview tracking — known unknowns

Specific things NOT yet verified empirically in this MVP (calibrate trust accordingly):

1. **Real-CR dogfooding** — engine is synthetic-test green, but no real CR add-page event has been processed yet. The next <client> CR that needs a new page should drive this skill.
2. **Clone fidelity on visualContainerObjects** — synthetic smoke verifies file count + GUID freshness + displayName + background. NOT verified: that the cloned page renders pixel-identical to source on Fabric (theme bindings, slicer state, filter scope). Smoke test absorbs the structural side, not the rendering side.
3. **Large pages (>20 visuals)** — smoke uses 2 visuals. Real <client> pages may have 40+. Performance untested at scale.
4. **PBIR-Legacy** — explicitly out of scope. The skill halts cleanly when given a legacy folder (file structure mismatch).
5. **Concurrent edits** — engine writes assume single-writer to the report folder. If a parallel `/<client>-pbi-loop edit` session is running on the same folder, results undefined.
6. **insert_at edge cases** — negative indices smoke-tested up to `insert_at=1`; very negative or out-of-range insertion not exercised.

## Promotion criteria (`preview` → `stable`)

Following the framework convention (`status:` in root `CLAUDE.md`):

1. **2+ distinct real-CR add-page events** on actual <client> reports, both completing cleanly without manual remediation of the generated page (post-deploy edit cycles via `/<client>-pbi-loop edit` are normal and don't count against the criterion — what counts is: did `add_page_to_report` produce a structurally correct page that Fabric accepted on the first push).
2. **Both modes exercised** — at least one `--spec` and one `--clone-from` real use.
3. **Documented gotchas mitigated** — any silent failure surfaced becomes either a fix in the engine or an explicit `[WARN]` with remediation hint. No silent corruption tolerated for promotion.
4. **One non-author team member** (<seat> or similar) uses the skill successfully without framework-manager coaching.

When all four criteria are met, promote `status: preview` → `status: stable` in a focused commit referenced in `ops.log`, and remove the "Preview tracking" section in favour of a short "Notes" if any caveats remain.

## Related skills

- `/pbir-create` — build a brand-new report from scratch (different granularity)
- `/pbir-clone-template` — clone a whole report and retarget bindings (different granularity)
- `/<client>-pbi-loop edit` — interactive iteration on the new page after `/pbir-add-page` completes
- `/pbir-report deploy` — explicit deploy of a `.Report` folder (used by Step 3 internally)
