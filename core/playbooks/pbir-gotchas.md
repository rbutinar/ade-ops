# PBIR silent-failure gotchas

Empirical findings on programmatic Power BI report (PBIR) construction.
These are **silent failures** — Fabric service accepts the input and
renders something that "almost looks right" instead of returning an
error. Each gotcha cost diagnostic time once; this document exists so it
doesn't cost it twice.

Discovered 2026-05-23 during the `databricks-fabric-migration` demo
(`/ddf-operator` session). Cross-distribution: every project that
builds PBIR programmatically will hit the same wall.

## The nine gotchas

### 1. Container-level styling lives under `visualContainerObjects`, not `objects`

**Symptom**: `objects.background` / `objects.title` set on a visual are
silently ignored. The visual renders with default styling as if the
properties were never set.

**Root cause**: PBIR has two separate styling slots:
- `objects.*` — visual-**internal** styling (axis, labels, dataPoint colours, legend)
- `visualContainerObjects.*` — visual-**container** styling (background, title, border)

Setting container properties under `objects.*` is silently dropped.

**Fix**: use `visualContainerObjects.{background, title, border}` for
container-level styling. Keep `objects.*` for what lives inside the visual.

### 2. Background colour rendered as washed-out pastel

**Symptom**: even after fixing gotcha #1, the background colour appears
as a pale/pastel version of the intended hex value.

**Root cause**: Fabric service applies a non-zero default opacity to
background fills when transparency is not set explicitly.

**Fix**: set transparency explicitly to `0D` (which in PBIR's opacity
encoding means fully opaque):

```json
"background": {
  "properties": {
    "color": { "solid": { "color": { "expr": { "Literal": { "Value": "'#1F4E79'" } } } } },
    "transparency": { "expr": { "Literal": { "Value": "0D" } } }
  }
}
```

Legacy hand-authored reports (e.g. `qsXXtitle` style) sometimes render
correctly without the explicit transparency — the legacy renderer may
pick a different default. **Programmatic builds always need the explicit
`0D`**.

### 3. Chart titles auto-generated as `<Measure> by <Category>`

**Symptom**: the chart title shows `Sum of Revenue by Product Category`
(auto-generated from the field projection) instead of the intended title
text. The desired text is in the JSON but invisible.

**Root cause**: same root cause as gotcha #1 — `title.text` set under
`objects.title` is silently ignored. Title is a container-level property.

**Fix**: put `title.properties.text` under `visualContainerObjects`,
same shape as the background fix.

### 4. Custom theme in `StaticResources/SharedResources/BaseThemes/X.json` is uploaded but invisible

**Symptom**: theme JSON file is bundled in the part list and the upload
succeeds. The deployed report uses the theme (visuals don't crash on it,
data colors apply). But `getItemDefinition` does NOT return the theme
file when called with the default format flag.

**Root cause**: not fully diagnosed. Either Fabric stores `StaticResources/`
in a separate logical bucket (different REST endpoint), or a different
`?format=` query parameter is needed to include them, or `getItemDefinition`
silently drops them from the response payload.

**Workaround**: don't rely on `getItemDefinition` to audit theme deployment.
Inspect the rendered report visually (e.g. via the Playwright loop —
see `playwright_pbi_loop.md`). Treat the theme as "deployed if visuals
render with the right colours".

**Open question for the framework**: investigate the `?format=` parameter
on `getItemDefinition` to confirm whether StaticResources can be retrieved
at all via REST.

### 5. Card visual shows "Error fetching data" placeholders

**Symptom**: card visuals render with grey error placeholder boxes that
look like positioning artifacts (misplaced rectangles, missing data).

**Root cause (red herring)**: NOT a layout bug. The placeholder IS the
visual when its semantic-model binding can't resolve — typically because
the DirectLake source table has not been materialised yet (pipeline still
running or never ran).

**Fix**: not a layout fix. Wait for the data pipeline to complete. If
pipeline failed, check pipeline run status — the visual placeholder is
correctly reporting "no data", not a styling bug.

### 6. Hex colour case is irrelevant

**Symptom (red herring during diagnosis)**: `#1f4e79` vs `#1F4E79` —
during gotcha #2 diagnosis, lowercase was suspected as the issue.

**Reality**: both uppercase and lowercase hex parse correctly. Some
hand-authored reports happen to use lowercase, but it's stylistic — not
load-bearing.
Don't waste time normalizing case during diagnosis.

### 7. PowerShell 5.1 UTF-8 BOM breaks `updateDefinition` silently

**Symptom**: a PBIR `.json` file edited from PowerShell 5.1 via
`Set-Content -Encoding UTF8` or `Out-File -Encoding UTF8` is pushed via
`updateDefinition`. Fabric returns 202 (accepted). The LRO state resolves
**`Failed`** after a 5–10s polling delay with
`errorCode: Report_Import_FailedToImportReport`. Because the failure
arrives after the submission window, it masquerades as a transient
network or schema issue.

**Root cause**: PowerShell 5.1's `-Encoding UTF8` writes a UTF-8 BOM
prefix (`0xEF 0xBB 0xBF`). The Fabric PBIR importer rejects BOM'd JSON
parts.

**Fix — write JSON without BOM in PowerShell**:

```powershell
$enc = New-Object System.Text.UTF8Encoding($false)   # $false = no BOM
[System.IO.File]::WriteAllText($path, $content, $enc)
```

**Diagnostic — check first 3 bytes**:

```powershell
[byte[]]$head = Get-Content $path -Encoding Byte -TotalCount 3
$head -join ' '   # EF BB BF means BOM present
```

**Preferred path for small diffs**: use the Claude Code `Edit` tool
instead of PowerShell file writes. `Edit` does not reintroduce a BOM
(verified: first 3 bytes of an edited file remain the file's original
opening characters, e.g. `7B 0A 20` for an indented JSON `{` newline
space).

Discovered 2026-05-25 (finding F-new-5 from a multi-seat PBI dev exercise).
PowerShell 7+ defaults to UTF-8 without BOM, so this is a 5.1-specific
trap — but 5.1 is the default on most enterprise operator workstations.

### 8. Combo-chart line measures go in `Y2`, NOT a bucket named `LineY`

**Symptom**: a `lineClusteredColumnComboChart` / `lineStackedColumnComboChart`
renders as a **plain column chart** — no line, no error. The legend is
missing the line series and the auto-title omits the line measures.

**Root cause**: for combo charts the column measures belong in
`queryState.Y` and the **line** measures in `queryState.Y2`. Putting the
line measures in a bucket named `LineY` (a plausible-looking guess) makes
Power BI **silently drop that projection**. This masquerades as a
"stale/no-op push" and can cost a full build+verify cycle chasing the
wrong cause.

**Fix**: column measures → `queryState.Y`, line measures → `queryState.Y2`.
**Diagnostic tell**: legend has fewer series than projected, and the
auto-title omits the line measures.

Discovered 2026-05-24 (PBIR visual-feedback loop, finding §B.1).

### 9. A newly-added import table is EMPTY until a dataset refresh

**Symptom**: a table added to a semantic model via `updateDefinition`
deploys fine, but a measure that reads it (e.g. `LOOKUPVALUE`) returns
**BLANK silently** — looks like a broken measure; it's actually missing
data.

**Root cause**: the table definition deploys, but its partition has **no
rows** until a dataset refresh runs.

**Fix**: verify with `EVALUATE ROW("n", COUNTROWS(<table>))` → `null`
means an empty partition. Then run a targeted enhanced refresh:

```
POST .../datasets/{ds}/refreshes
{ "type": "Full", "objects": [ { "table": "<t>" } ], "notifyOption": "NoNotification" }
```

→ `202`, then poll `GET .../refreshes/{id}` to `Completed`. Fast; works on
Fabric capacity with the <organization>-guest identity. (Engine follow-on:
`push --scope power_bi` could detect newly-added import tables vs the
deployed dataset and offer the refresh — tracked in TICK-012.)

Discovered 2026-05-24 (PBIR visual-feedback loop, finding §B.3).

## How to use this document

1. **Before writing programmatic PBIR**: skim section headers. Build
   with the gotchas in mind (container vs internal styling, explicit
   transparency, etc.).
2. **When something renders wrong**: search for the symptom phrasing.
   These nine cover ~all the silent-failure modes observed so far.
3. **When adding a new gotcha**: append a numbered section with the same
   shape (Symptom / Root cause / Fix). Update the "How to use" reference
   count.

## See also

- `playwright_pbi_loop.md` — the visual-feedback loop that catches these
  gotchas in seconds instead of minutes
- `docs/feedback/2026-05-23_pbir-report-build-needs-wrapper-helpers.md`
  — architectural proposal for `core/platforms/powerbi/pbir_engine/` that
  would encapsulate these gotchas behind a wrapper API
