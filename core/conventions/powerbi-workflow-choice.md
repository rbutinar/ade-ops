# Power BI workflow — two paths, when to use which

> ade-ops ships two complementary paths for Power BI authoring: an
> **engine path** (Python libraries we own, no Desktop, no MCP) and an
> **MCP path** (Microsoft Power BI Modeling MCP via `powerbi`, requires
> Desktop open). Both ship in the public preview. The engine path is
> the default; the MCP path is opt-in for specific scenarios. This
> document is the decision tree.

## The two paths at a glance

| Aspect | Engine path | MCP path (`powerbi`) |
|---|---|---|
| Authoring artefacts | TMDL semantic models + PBIR reports, generated from Python | TOM operations against a live model in Desktop |
| External dependency | None (Python `core/parsers/` + `core/platforms/powerbi/`) | Power BI Desktop running + `.pbip` file open + `powerbi` MCP server registered |
| Setup cost | Zero — comes with ade-ops install | Install VSIX of `analysis-services.powerbi-modeling-mcp` (see `.mcp.example.json` `_setup_powerbi_prereq`) + binding to local Desktop process |
| Reproducible | Yes — output is deterministic from spec YAML | No — depends on Desktop UI state + cookies / session |
| Visual feedback loop | No (deploy → check via REST or screenshot) | Yes (changes appear live in Desktop preview) |
| Where the canonical source lives | `src/power_bi/<Model>.SemanticModel/` (TMDL) + `src/power_bi/<Report>.Report/` (PBIR) in repo | Same paths, but Desktop is editing them concurrently |
| Skills using it | `/powerbi-directlake-create`, `/powerbi-model-create`, `/powerbi-publish`, `/pbir-create`, `/pbir-clone-template`, `/pbir-add-page`, `/pbir-report` | `/powerbi-model-edit` |

## Decision tree

```
What do you want to do with Power BI?

├── Generate a new semantic model from scratch
│   └── ENGINE PATH — /powerbi-directlake-create or /powerbi-model-create
│                     (writes TMDL skeleton; no Desktop required)
│
├── Create or extend a PBIR report
│   ├── New report from spec
│   │   └── ENGINE PATH — /pbir-create
│   ├── Clone a known-good report and retarget bindings
│   │   └── ENGINE PATH — /pbir-clone-template
│   ├── Incremental page addition to existing report
│   │   └── ENGINE PATH — /pbir-add-page
│   └── Deploy a built PBIR to Fabric
│       └── ENGINE PATH — /pbir-report or /powerbi-publish
│
├── Edit an EXISTING semantic model with visual feedback loop
│   ├── Add / modify measures, columns, relationships interactively
│   │   └── MCP PATH — /powerbi-model-edit (requires Desktop open)
│   ├── Tune calculation groups, perspectives, translations
│   │   └── MCP PATH — TOM is the natural API for these
│   └── Debug a deployed model that has errors
│       └── MCP PATH — open in Desktop, inspect via TOM, fix in TMDL
│
└── Just publish a TMDL model to Fabric
    └── ENGINE PATH — /powerbi-publish (REST API, no Desktop)
```

## Why the engine path is the default

1. **Zero setup**: works out of the box on any machine where ade-ops is
   installed. No VSIX install, no Desktop, no MCP server registration.
2. **Reproducible**: the same input spec produces the same TMDL / PBIR
   output every time. Critical for CI / pipeline-driven environments.
3. **Headless-friendly**: runs on CI, in containers, on any OS, in
   automated pipelines. The MCP path requires a Windows desktop session.
4. **Audit-friendly**: every authoring step is a git-visible change to
   the TMDL / PBIR files. Desktop edits via MCP are also git-tracked
   (the files are the same), but the *intent* is more readable in the
   engine-path skill body output.
5. **Decoupling**: the engine path produces files; what consumes them
   (Desktop, Fabric, Tabular Editor, external tools) is independent.

## Why the MCP path exists despite the above

Some operations genuinely benefit from a **live model + visual feedback
loop**:

- Iterative DAX measure refinement where you want to see the resulting
  visual change immediately
- Calculation group authoring with translation/perspective interactions
- Visual debugging of a model that's already deployed and behaves
  unexpectedly
- TOM-specific operations the engine path does not (yet) cover
  (e.g. detailed role security, complex KPI definitions)

For these cases, opening Desktop on the `.pbip` and using
`/powerbi-model-edit` (which talks to `powerbi` MCP) is faster and more
ergonomic than round-tripping through TMDL files.

## Combining both paths (the common production pattern)

A typical end-to-end workflow uses both:

1. **Build phase** (engine path): scaffold the semantic model via
   `/powerbi-directlake-create`, build the report via `/pbir-create`.
2. **Refinement phase** (MCP path, optional): open the `.pbip` in
   Desktop, tweak measures and visuals with `/powerbi-model-edit` until
   the model behaves as wanted.
3. **Deploy phase** (engine path): `/powerbi-publish` to push the
   refined TMDL to Fabric. `/pbir-report` to push the PBIR to the same
   workspace.
4. **Iterate phase** (mixed): subsequent changes can come from either
   path. The TMDL files are the single source of truth — Desktop edits
   write back to them, engine edits read and rewrite them.

The git history captures every change regardless of which path made it.

## Setup for the MCP path

If you want to enable the MCP path on a new seat:

1. Install Node.js LTS (`winget install OpenJS.NodeJS.LTS`) — required
   by the `@playwright/mcp` server used in adjacent workflows; not
   strictly required for `powerbi` alone but expected by the bundle.
2. Install the VSIX: download
   `analysis-services.powerbi-modeling-mcp` from VS Code Marketplace,
   rename `.vsix` → `.zip`, extract to
   `C:/MCPServers/PowerBIModelingMCP_x64/`. The binary lands at
   `C:/MCPServers/PowerBIModelingMCP_x64/extension/server/powerbi-modeling-mcp.exe`.
3. Configure `.mcp.json` (copy from `.mcp.example.json` template,
   replace `<your-user>` placeholders). The `powerbi` block is already
   shaped for you.
4. Open Power BI Desktop, open the `.pbip` you want to edit, ensure
   the local model server is running (Desktop shows it in the status
   bar).
5. Restart Claude Code so the new `.mcp.json` is picked up. `claude
   mcp list` should now show `powerbi` in addition to `databricks` and
   `playwright`.
6. First invocation of `/powerbi-model-edit` confirms the binding.

## Anti-patterns

- **Using MCP path for new model generation**: don't open Desktop just
  to scaffold a fresh model. The engine path is faster, cleaner, and
  doesn't require a `.pbip` file to exist yet.
- **Using engine path for "just need to tweak one measure" exploration**:
  if you don't know yet what the measure should be, iterating in
  Desktop is faster than round-tripping TMDL. Once you've converged,
  commit the TMDL diff via git — the engine path takes over from there.
- **Skipping the engine path for production deployment**: even if the
  authoring happened in Desktop, the deployment step should go through
  `/powerbi-publish` (engine path). Manual "Save as → upload via UI"
  bypasses audit and breaks the multi-environment promotion pattern.
- **Running both paths concurrently on the same `.pbip`**: Desktop and
  engine-side edits to the same TMDL file race. Either close Desktop
  before invoking engine skills, or limit Desktop to non-overlapping
  parts of the model.

## Related

- [`.mcp.example.json`](../../.mcp.example.json) — `powerbi` server registration template + setup prereqs
- `core/parsers/tmdl_directlake_builder.py` — TMDL Direct Lake builder
- `core/platforms/powerbi/pbir_engine/` — PBIR engine (builder, clone, add_page, visuals, layout, fields)
- [`seat-triad.md`](./seat-triad.md) — which seat layers a Power BI workflow touches (the `.pbip` files live under the per-distribution `src/power_bi/`, tracked by git; the MCP server session state is ephemeral, not tracked)
