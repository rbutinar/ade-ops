# Deck templates — canonical pattern

> How an ade-ops seat generates PowerPoint decks (PPTX) from a brand
> template + a structured spec, with a **per-seat config that points to
> brand artifacts stored outside the repo** (OneDrive).
>
> Documented 2026-05-28 after the marketing-manager + project-deck
> needs converged on a shared engine. Brand `.pptx` files live outside
> the repo for IP + audit reasons; only the engine, the convention, and
> a neutral skeleton ship with ade-ops.

## Two-part model

A deck is built from two inputs:

1. **Template** — a `.pptx` file with a slide master and named layouts.
   Brand-bound: an <organization> corporate template, a client-branded
   template, an ade-ops community-neutral template. Stored **outside
   the repo** in OneDrive folders the operator owns. The engine never
   modifies the template — only reads its layouts.
2. **Spec** — a YAML file describing the deck (meta + slides list).
   Each slide picks a layout name from the template and provides body
   content (text, bullets, image paths). Authored by the operator (or
   by an agent on their behalf) and lives in the working tree of the
   project the deck is about.

```
Template (.pptx, OneDrive)   +   Spec (YAML, in-repo)   =   PPTX output
   |                                  |                          |
   Brand                              Content                    Deliverable
```

## Template storage — OneDrive, not repo

Brand `.pptx` files are policy-sensitive (<organization> corporate IP,
client-branded versions, etc.) and **do not ship with ade-ops**. They
live in OneDrive folders the operator manages:

```
${OneDrive}/60. ADE - Community/templates/decks/
   community_neutral_2026.pptx       # public/OSS, brand-agnostic
   community_lightning_talk.pptx     # shorter talk format
   ...

${OneDriveCommercial}/60. ADE - <organization>/templates/decks/
   _base/
     accenture_2026.pptx             # <organization> corporate base
     accenture_lightning_2026.pptx   # short pitch variant
   acme/
     acme_branded_2026.pptx          # Acme client deck (corporate-provided)
   <other-client>/
     <client>_branded_2026.pptx
```

`${OneDrive}` and `${OneDriveCommercial}` are standard Windows
environment variables, set automatically by OneDrive sync. Using them
keeps the config portable across operators (each operator's OneDrive
mounts at their own filesystem path).

## Per-seat config — `config/decks.yaml`

Each seat has a personal `config/decks.yaml` (gitignored, analogous to
`credentials.yaml`) that maps **template pack names** to OneDrive
folders. The committed `config/decks.yaml.example` is the template.

```yaml
# config/decks.yaml — per-seat, gitignored
template_paths:
  community: "${OneDrive}/60. ADE - Community/templates/decks"
  accenture: "${OneDriveCommercial}/60. ADE - <organization>/templates/decks/_base"
  accenture-acme: "${OneDriveCommercial}/60. ADE - <organization>/templates/decks/acme"

default_pack: accenture

output_dir: "${OneDrive}/60. ADE - Community/drafts/decks"
```

The engine resolves `${OneDrive}` and `${OneDriveCommercial}` from
`os.environ` at operation time. Unresolved references surface as
precise errors (no silent fallback to `None`).

## Layout discovery — no rename needed

The engine uses the template's **real layouts** as they ship. There is
**no required-layout vocabulary** and **no rename step**: a brand starter
pack with 50+ rich layouts (3-columns, statistics, icons, key-message,
table, section dividers, salutation…) is used as-is — its richness is the
whole point, so collapsing it to a fixed name set would throw it away.

A spec addresses layouts in one of two ways:

- **By index** — `layout: 24` picks the 25th layout in the template.
  Stable, explicit, and the natural fit for rich brand templates.
- **By real name** — `layout: "Content: 3 columns"` (case-insensitive)
  picks the layout with that exact name. Convenient when the template's
  layout names are meaningful.

**Discover** what a template exposes with `deck-catalog` — it lists every
layout (index, name) and its placeholders (idx, name, type). This is the
step that replaces renaming:

```
python -m core.cli deck-catalog "C:/path/to/template.pptx"

  [0] Cover: gradient
        idx=0   CTR_TITLE    Title
        idx=1   SUBTITLE     Subtitle
        idx=13  PICTURE      Picture Placeholder
  [24] Content: 3 columns
        idx=0   TITLE        Title
        idx=2   BODY         heading 1
        idx=3   BODY         body 1
        ...
```

### Addressing placeholders

PowerPoint stores each placeholder with an `idx` (integer) and an optional
`name` (string). The engine supports both:

- **By idx** (rich path) — `text: {0: "…"}`, `bullets: {2: ["…"]}`. The
  idx comes straight from `deck-catalog`. Unambiguous on any template,
  including those whose placeholders are unnamed. **Use this for brand
  templates.**
- **By name** (sugar) — generic named fields (`title`, `subtitle`,
  `body`, `left`, `right`, `quote`, `attribution`, `caption`) route to a
  placeholder matched by name, with an idx-based fallback. Handy for
  simple templates (e.g. the shipped neutral skeleton) whose placeholders
  carry those names. These are **not** tied to any layout — any layout may
  use any field.

`deck-validate <spec>` resolves the spec's template and reports any
`layout` index/name or placeholder `idx` that does not exist, so missing
references surface before the build instead of silently dropping content.

## Spec YAML schema

```yaml
meta:
  title: "ade-ops — Project deck"
  author: "Roberto Butinar"
  date: "2026-05-30"
  pack: accenture-acme              # references template_paths key in decks.yaml
  template: acme_branded_2026.pptx  # filename within the pack folder
  # template: default               # OR: first .pptx in the pack alphabetically
  # keep_template_slides: false     # default false → drop the template's example slides

slides:
  # --- Named-field path (sugar) — for templates with named placeholders ---
  - layout: Title                   # by real name (case-insensitive)
    title: "ade-ops — Acme"
    subtitle: "Roadmap & demo readiness"

  - layout: TitleAndContent
    title: "Q2 recap"
    body:                           # list → bullets; string → one paragraph
      - "Wave 1 — go-public switch executed"
      - "Wave 2 — public-distribution scenarios live"

  # --- Idx path (rich) — for brand starter packs; idx from deck-catalog ---
  - layout: 24                      # by index
    text:                           # placeholder idx → single string
      0: "Automation across platforms"
      2: "Power BI"
      3: "Databricks"
    bullets:                        # placeholder idx → bullets
      4: ["TMDL models", "PBIR deploy", "Live edit via MCP"]
    force_font:                     # override run font (brand font on key text)
      - {idx: 0, name: "Graphik Semibold"}

  # --- Images: three forms ---
  - layout: 12                      # "title only" layout → free diagram
    text: {0: "How a deployment works"}
    image:                          # explicit position in inches (no placeholder)
      path: "assets/architecture.png"   # relative to the spec file dir
      left: 0.6
      top: 1.5
      width: 12.13
      # height: 6.0                 # optional; omit to keep aspect ratio

  - layout: ImageRight
    title: "Architecture flywheel"
    body: ["core/ — engine", "distributions/ — overlays"]
    image: "assets/flywheel.png"    # string → routed to a named image placeholder
    # image: {idx: 13, path: "assets/flywheel.png"}  # OR into placeholder idx 13
```

### Field rules

- `meta.pack` — required, must match a key in `decks.yaml.template_paths`
  (or omit and rely on `default_pack`).
- `meta.template` — a filename in the pack folder, or `default`.
- `meta.keep_template_slides` — optional; `true` appends the spec's slides
  onto the template's existing slides instead of dropping them (default
  `false`).
- `slides[*].layout` — required; an **int** index or a **layout name**
  (case-insensitive). Run `deck-catalog` to see both.
- `text: {<idx>: <str>}` / `bullets: {<idx>: <list|str>}` — populate
  placeholders by idx.
- Named fields (`title`, `subtitle`, `body`, `left`, `right`, `quote`,
  `attribution`, `caption`) — populate by placeholder name (idx fallback);
  `body`-kind fields accept a list (bullets) or string.
- `image` — a path string (→ named image placeholder), or a mapping with
  `path` + either `idx` (a placeholder) or `left`+`top`+`width` (explicit
  inches). Paths resolve relative to the spec file dir.
- `force_font: [{idx, name}]` — set the run font of a placeholder (the
  layout's font is not applied to text the engine writes).

## CLI surface

```
python -m core.cli deck-list                       # list packs + templates
python -m core.cli deck-catalog <template.pptx>    # discover layouts + placeholder idx
python -m core.cli deck-validate <spec.yaml>       # check spec refs resolve vs its template
python -m core.cli deck-build <spec.yaml>          # build PPTX
python -m core.cli deck-build <spec.yaml> --out X  # custom output path
python -m core.cli deck-build <spec.yaml> --render # + render to PNG (PowerPoint COM)
```

Default output goes to `decks.yaml.output_dir`, file named after
`<spec basename>_<YYYYMMDD>.pptx`. The `--render` step uses the
PowerPoint-COM renderer (`tools/deck-render/`) for true Office fidelity —
the visual-verify half of the build → render → inspect → fix loop.

## What the engine does NOT do

- **Does not modify the template** — read-only (apart from dropping the
  template's own example slides; masters/layouts/theme are untouched). To
  change brand, change the source `.pptx` in OneDrive.
- **Does not enforce brand rules** — colors, fonts, master shapes are the
  template's responsibility. The engine populates placeholders only
  (use `force_font` only where a brand font must override).
- **Does not auto-resize images** — placeholder/explicit-box images are
  inserted at the given box; aspect ratio is fit-to-fill.
- **Does not generate charts from data** — chart placeholders are
  out of scope for V1. Use prebuilt chart images in `image` slides.
- **Does not upload anywhere** — output is local. Sharing/upload is
  manual or via a separate skill (future `deck-publish-sharepoint`
  candidate).

## Anti-patterns

- **Committing brand `.pptx` to the repo** — corporate / client templates
  are IP-sensitive. They live in OneDrive, not in git. The engine
  resolves them via `decks.yaml` per-seat.
- **Hardcoding OneDrive paths** — use `${OneDrive}` /
  `${OneDriveCommercial}` so the config is portable across operators.
- **Building decks against the wrong pack** — if you target an
  <organization>-internal audience, do not use `community`. The pack name
  encodes the audience.
- **Renaming a template's layouts/placeholders to fit the engine** — not
  needed and counter-productive. Address the template's real layouts by
  index/name and placeholders by idx (`deck-catalog`). A spec is naturally
  template-specific; that is fine — the template is the brand, the spec is
  the content.
- **Guessing placeholder idx** — run `deck-catalog` and copy the indices.
  `deck-validate <spec>` catches references that do not resolve.

## Related

- [`credentials.md`](./credentials.md) — the per-seat gitignored config
  pattern (`decks.yaml` follows the same model as `credentials.yaml`)
- [`seat.md`](./seat.md) — per-seat scoping convention
