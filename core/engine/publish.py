"""Engine for ``/ops-publish`` — copy lab → public target with sanitization.

Loads ``core/conventions/_private_sanitization_values.yaml`` (lab-only,
gitignored), parses BLOCK / REPLACE / ALLOW rules, walks the source tree
applying:

1. **Path filter** — exclude lab-only paths (ops.log, feedback/, backlog/,
   marketing-manager/**, client-specific distributions, demo-claude,
   state/, credentials.yaml, .mcp.json, agent memory directories, the
   private sanitization values file itself, etc).
2. **Skill maturity gate** — prune ``.claude/commands/<name>.md`` (legacy) and
   ``.claude/skills/<name>/`` (canonical Agent-Skills folder) by each skill's
   frontmatter ``status:`` (experimental/deprecated never ship; preview ships
   only when opted-in via the distribution's ``skills.include``; stable or
   status-less grandfathered) + a core subtree allowlist. See ``_skill_ships``
   and ``_core_path_ships``.
3. **REPLACE rules** — substitute matching patterns in flight (text files).
4. **BLOCK rules** — refuse to publish if a BLOCK pattern matches the
   post-REPLACE text. Returns the violation list to the CLI.
5. **ALLOW rules** — verify positive assertions on the materialised target
   (e.g. ``Roberto Butinar`` must appear in ``LICENSE``).

The public sibling ``core/conventions/sanitization-patterns.md`` is
structural-only documentation (no literal pattern values) and ships
verbatim as part of the public publish.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Literal

import yaml

from .config import ProjectConfig, load_project

# ---------------------------------------------------------------------------
# Path filter: lab-only paths that never ship in a public publish.
# ---------------------------------------------------------------------------

# Glob patterns relative to the lab root. Any source path matching one of
# these is silently dropped from the publish target.
_LAB_ONLY_PATH_GLOBS: tuple[str, ...] = (
    # Framework-level narrative / state
    "docs/ops.log",
    "docs/feedback/**",
    "docs/backlog/**",
    "docs/pm/**",              # lab internal project-management substrate (dogfooding), lab-only
    "docs/notes/**",
    "docs/handoffs/**",
    "docs/design.md",          # internal architecture doc, lab-only V1
    "docs/toolkit_design.md",  # internal design patterns, lab-only V1
    "docs/migrations/**",
    # Knowledge-base content — experimental (TICK-038), distilled from lab and
    # client experience and carrying client slugs. Held from public until curated +
    # sanitized. The core/knowledge engine is likewise held (not in
    # _PUBLIC_CORE_SUBTREES), so the whole KB feature stays lab-only as a unit.
    "docs/knowledge/**",
    # Lab dev tooling (clean-room tester, provisioning scripts) — never part of
    # the published distribution. Caught a near-leak in clean-room run #1
    # (maintainer path + client slug in a tooling README). Finding #5.
    "tools/**",
    # Lab test suite — exercises engine internals including held modules (fleet,
    # PM) and uses real client slugs as fixtures. The public distribution ships
    # the framework + reference projects, not the lab's internal test suite.
    # (TICK-002 publish dry-run 2026-06-13 surfaced client slugs in fixtures.)
    "tests/**",
    # Internal operational reference (gotchas, Edge profile patterns, MCP scope
    # priority) — contain lab-policy-specific workarounds that should not be
    # presented as primary guidance in the public distribution. F2 will
    # selectively re-include cleaned-up subsets.
    "core/docs/**",
    # Git submodule references (lab pulls in client-specific submodules)
    "**/.gitmodules",
    # Personal Claude Code settings (paths, env, MCP scope per user)
    ".claude/settings.local.json",
    ".claude/settings.json",
    # Agent memory (per-skill, contains user-specific state)
    ".claude/agents/*/CONTEXT.md",
    ".claude/agents/*/IDENTITY.md",
    # Per-seat user state (e.g. ops-local-manager/users/<handle>.md). publish
    # walks the working tree, not git — these are gitignored but present on
    # disk, so they must be filtered here. *.template.md + .gitkeep survive.
    ".claude/agents/*/users/*.md",
    ".claude/agents/*/sessions/**",
    ".claude/agents/*/handoffs/**",
    ".claude/agents/*/local/**",
    ".claude/agents/*/drafts/**",
    ".claude/agents/*/sources/**",
    ".claude/agents/_threads/**",
    # Marketing-manager: entirely lab-only (drafts, sources, editorial plan)
    ".claude/agents/marketing-manager/**",
    # Ops-manager: framework maintainer agent memory (CONTEXT.md history,
    # IDENTITY.md learned behaviors, port-back queue + sessions). All
    # lab-only — never expose maintainer-internal operational state.
    ".claude/agents/ops-manager/**",
    # Archived working folders
    "**/_archived/**",
    # Lab distributions (client-specific, demo-claude, _lab, etc) — only the
    # published distribution survives, all others are filtered at the walk
    # boundary. (Handled in walk_publishable() rather than glob — needs the slug.)
    # Credentials + MCP config
    # NOTE: .mcp.example.json IS published — it is the setup template for
    # fresh clones. MCP server keys carry canonical, descriptive names in the
    # published copy (the REPLACE pass normalises any local lab aliases to
    # these). Finding #4 from ade-ops-2 dogfooding.
    "**/credentials.yaml",
    "**/.mcp.json",
    # Sanitization literal values (lab-only sibling of the structural .md)
    "core/conventions/_private_sanitization_values.yaml",
    # State (pulled from remote, not source of truth)
    "**/state/**",
    # Build artefacts / VCS
    "**/__pycache__/**",
    "**/*.pyc",
    ".git/**",
    # Harness git worktrees live under .claude/worktrees/ — each is a full nested
    # checkout of the repo, NOT source. Exclude so a publish/seed run from the
    # repo root never descends into one (it would double-walk the tree and drag
    # in lab-only content that the anchored globs miss at the nested depth).
    # Surfaced by the TICK-036 enterprise-baseline dry-run.
    ".claude/worktrees/**",
    ".venv/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".mypy_cache/**",
    # Per-user editor / IDE local
    "**/local/**",
    "**/.vscode/**",
    "**/.idea/**",
    # Per-user cross-harness MCP/agent config (generated from .mcp.json, carries
    # local user paths) — same class as .mcp.json: never ship. A public example
    # template would ship under a *.example name (cf. .mcp.example.json), not the
    # live config dir.
    "**/.codex/**",
    "**/.cursor/**",
    # Experimental Copilot-consumable harness layer. The public portability
    # contract is the CLI (see .github/copilot-instructions.md): slash-command
    # equivalents for Copilot (prompt files, chat modes) are an experiment that
    # lives in the `copilot-preview` lab distribution and is held from public
    # until it graduates. Held at repo root too, so an experiment placed there
    # by habit cannot leak. NOTE: .github/copilot-instructions.md and
    # .github/*_TEMPLATE.md still ship — only prompts/ + chatmodes/ are held.
    "**/.github/prompts/**",
    "**/.github/chatmodes/**",
    # Cross-harness skill projection (generated). The lab's .agents/ is an
    # UNFILTERED mirror of every .claude/skill (incl. held/experimental/deny-
    # prefixed ones) and is gitignored. It must NEVER be walked/copied directly:
    # the skill-maturity gate only inspects .claude/skills|commands, so a raw
    # copy of .agents/skills would leak held skills straight past the gate. The
    # published .agents/skills is instead REGENERATED from the FILTERED target
    # .claude/skills after materialisation (see project_agents_catalog).
    ".agents/**",
    # Deck-building feature (experimental, TICK-005) — migrating out of ade-ops
    # to the ade-product-family repo; present here only temporarily and held from
    # ALL channels. The skill body is already held (experimental), but the engine,
    # branded templates, per-seat config (OneDrive paths) and convention doc are
    # not covered by the maturity gate — hold them explicitly so the feature
    # cannot leak. (main.py still carries lazy-imported deck commands; stripping
    # them lands with the full migration — tracked in docs/backlog.)
    "core/engine/decks/**",
    "core/conventions/deck-template.md",
    "core/templates/decks/**",
    "config/decks.yaml",
    "config/decks.yaml.example",
    # PBI runtime cache (deployable items only)
    "**/.pbi/cache.abf",
    "**/.playwright-mcp/**",
)

# Skill name prefixes that are lab/enterprise-only and never publish. This is
# the always-on deny floor for skills, applied before the maturity gate below.
_DEFAULT_DENY_SKILL_PREFIXES: tuple[str, ...] = (
    "cnh-",          # noqa: ade-ops-sanitize=client-slug-cnh reason="literal prefix used as deny-list key, not a client reference"
    "ddf-",          # Databricks→Fabric demo-claude skills
    "marketing-",    # marketing-manager (lab-only meta-agent)
    "ops-manager",   # framework manager (enterprise-tier, never public)
    "ops-local-manager",  # rich multi-operator steward (enterprise-tier, not in the public 3-tier-light scope)
    "ops-port-back", # lab port-back skill (DevOps→lab)
    "weekly-team-",  # weekly-team-update (private team reporting)
)

# Skill maturity gate (TICK-006 ratified model). A skill ships iff:
#   - its name is NOT in _DEFAULT_DENY_SKILL_PREFIXES, AND
#   - it does NOT carry ``lab_only: true`` in its frontmatter, AND
#   - its ``status`` is not experimental/deprecated, AND
#   - if ``status: preview`` it is explicitly opted-in via the distribution's
#     ``skills.include`` (otherwise preview skills are held).
# ``status: stable`` OR a *missing* status are eligible: legacy unflagged core
# skills are grandfathered in, while NEW skills are born experimental/preview
# per the maturity convention — so default-deny still holds for new content.
_NEVER_PUBLIC_STATUSES: frozenset[str] = frozenset({"experimental", "deprecated"})

# Core first-level subtrees that may ship publicly (TICK-006 allowlist). Any
# ``core/<x>/**`` whose ``<x>`` is not listed is held by default — so a new
# core subtree is private until explicitly promoted here. Top-level files
# directly under ``core/`` (e.g. ``core/__init__.py``) always ship: the package
# must import. ``docs`` is omitted (also covered by the lab-only floor);
# ``pm`` is omitted (PM tooling held per the ratified model); ``__pycache__``
# is omitted (build artefact, also covered by the floor).
_PUBLIC_CORE_SUBTREES: frozenset[str] = frozenset({
    "cli",
    "connectors",
    "conventions",
    "engine",
    "parsers",
    "platforms",
    "playbooks",
    "templates",
})

# PM tooling that lives *inside* an otherwise-shipping core subtree and must be
# held as part of the "PM tooling stays private" unit (TICK-006 Q3). Unlike
# _LAB_ONLY_PATH_GLOBS this is a curation hold, not a security floor — revisit
# when the PM tooling is promoted to the public distribution.
_CORE_PM_HOLD_GLOBS: tuple[str, ...] = (
    "core/templates/pm-substrate/**",
    "core/playbooks/build-verify-run-delegate.md",
    "core/conventions/commit-discipline.md",
)

# Core conventions / playbooks / templates that document the lab's own farm and
# multi-seat operations (real client paths, the client farm map, seat-isolation
# values, release-propagation cadence). They ship to the client distribution as
# operational guidance but are NOT generic, public-ready framework content — and
# carry client references that the BLOCK pass would reject. Held as a unit like
# _CORE_PM_HOLD_GLOBS (a curation hold, not a security floor). The genuinely
# generic conventions woven into shipping skills (ops-log, knowledge-base,
# lean-seat-loadout) are kept public and genericized at source instead.
# Surfaced by the TICK-002 publish dry-run 2026-06-13.
_CORE_LAB_OPERATIONAL_HOLD_GLOBS: tuple[str, ...] = (
    "core/conventions/distribution-layout.md",
    "core/conventions/seat-isolation.md",
    "core/conventions/service-cadence.md",
    "core/conventions/release-versioning.md",
    "core/conventions/worktree-isolation.md",
    "core/conventions/session-coordination.md",
    # Playwright same-PC parallelism reference — accreted into core/ after the
    # last clean publish (~2026-06-15) and is heavily client-laden (real seat
    # slugs in its worked examples). Held from BOTH public and enterprise until
    # genericized; surfaced by the TICK-036 Lavazza farm dry-run (the BLOCK pass
    # would otherwise refuse it on every profile). Generic pattern, client-laden
    # examples — same disposition as seat-isolation.md.
    "core/conventions/playwright-parallelism.md",
    "core/playbooks/operating-flow.md",
    "core/templates/seat/**",
)


# ---------------------------------------------------------------------------
# Publish profiles — the curation layer (TICK-036 ACT-003-lite).
# ---------------------------------------------------------------------------
#
# A profile bundles the curation knobs that differ between the PUBLIC release
# channel and the internal ENTERPRISE channel that seeds client farms. The
# SECURITY FLOOR (``lab_only_path_globs``) and the BLOCK / REPLACE / ALLOW
# sanitization rules are the SAME across profiles by design: a profile only
# relaxes *curation* holds (what is appropriate/ready for an audience), never
# the floor that protects secrets, and never the cross-client BLOCK pass that
# is the second leak boundary (another client's literals can never ship into a
# farm). See core/conventions/enterprise-leak-boundary.md.


@dataclass(frozen=True)
class PublishProfile:
    """A named curation profile for a publish / propagate target.

    The historical public values live in the module-level constants and are
    wired into ``PUBLIC`` so the pre-profile behaviour is reproduced exactly
    (regression-gated by test_publish_filter.py, which calls the helpers with
    the default profile). FARM / ENTERPRISE instances differ only in the four
    curation knobs below.

    Attributes:
        name: Stable identifier — the CLI ``--profile`` value and audit label.
        lab_only_path_globs: The always-on security/curation floor (never
            ships). Same set across profiles by design — a safety invariant,
            not a per-audience choice.
        deny_skill_prefixes: Skill-name prefixes that never ship for this
            target (applied before the maturity gate).
        core_subtrees: First-level ``core/<x>`` subtrees allowed to ship.
        core_hold_globs: Curation holds *inside* shipping core subtrees (PM
            tooling held from public; client-laden ops docs held until
            genericized). A curation hold, not a security floor.
    """

    name: str
    lab_only_path_globs: tuple[str, ...]
    deny_skill_prefixes: tuple[str, ...]
    core_subtrees: frozenset[str]
    core_hold_globs: tuple[str, ...]


# The PUBLIC release channel — historical values, behaviour-identical to the
# pre-profile engine. This is the default profile for every helper below.
PUBLIC = PublishProfile(
    name="public",
    lab_only_path_globs=_LAB_ONLY_PATH_GLOBS,
    deny_skill_prefixes=_DEFAULT_DENY_SKILL_PREFIXES,
    core_subtrees=_PUBLIC_CORE_SUBTREES,
    core_hold_globs=_CORE_PM_HOLD_GLOBS + _CORE_LAB_OPERATIONAL_HOLD_GLOBS,
)

# Skills that never ship to ANY client farm: another client's prefix
# (cross-client isolation), demo (ddf-, demo-mode), lab-meta (marketing-), the
# lab-side service skills (the lab operates ON farms; a farm does not run
# ops-manager / ops-publish / ops-port-back / ops-sweep itself), and
# lab-personal reporting (weekly-team-).
# Deliberate DIFFERENCE from the public deny set: ``ops-local-manager`` is NOT
# denied — the rich multi-operator steward is the farm FRONT DOOR (the
# enterprise tier the public 3-tier-light scope omits). It still passes through
# the maturity gate, so a farm opts it in via ``skills.include``.
_ENTERPRISE_DENY_SKILL_PREFIXES: tuple[str, ...] = (
    "cnh-",          # noqa: ade-ops-sanitize=client-slug-cnh reason="deny-list key, not a client reference"
    "ddf-",
    "demo-mode",
    "marketing-",
    "ops-manager",
    "ops-publish",
    "ops-port-back",
    "ops-sweep",
    "weekly-team-",
)

# The ENTERPRISE baseline channel (TICK-036): the internal release channel that
# seeds client farms. Same security floor as public; relaxes the curation layer
# to ship the PM tooling (the multi-team acceleration delta) + the steward
# persona. ``pm`` joins the shippable core subtrees and the PM hold is dropped;
# the client-laden operational docs (seat-isolation, distribution-layout, …)
# stay HELD until ACT-005 genericizes them into reusable baseline conventions
# (the BLOCK pass is the backstop if one ships before it is cleaned).
ENTERPRISE_BASE = PublishProfile(
    name="enterprise-base",
    lab_only_path_globs=_LAB_ONLY_PATH_GLOBS,
    deny_skill_prefixes=_ENTERPRISE_DENY_SKILL_PREFIXES,
    core_subtrees=_PUBLIC_CORE_SUBTREES | frozenset({"pm"}),
    core_hold_globs=_CORE_LAB_OPERATIONAL_HOLD_GLOBS,
)

# Platform-shape skill filters, applied ON TOP of the enterprise deny set. The
# two are MIRRORS: a farm = enterprise baseline + exactly one of these. Keeping
# them as named tuples makes the generalisation visible (the profiles below
# differ only by which one they add) and reusable (a future client of the same
# shape reuses the tuple; only its cross-client denies would differ).
_PURE_FABRIC_DROP: tuple[str, ...] = (
    "databricks-",       # no Databricks platform skills
    "migration-assess",  # source != Databricks; the migration is the client's, out of scope
)
_NO_FABRIC_DROP: tuple[str, ...] = (
    "fabric-",             # no Fabric platform skills
    "powerbi-directlake",  # DirectLake REQUIRES a Fabric lakehouse — Import-mode only here
    "migration-assess",    # migration-assess targets Fabric; there is no Fabric here
)

# The Lavazza farm (TICK-036 ACT-006): enterprise baseline + the PURE-FABRIC
# filter (the client estate is Fabric; no Databricks).
LAVAZZA_FARM = PublishProfile(
    name="lavazza-farm",
    lab_only_path_globs=_LAB_ONLY_PATH_GLOBS,
    deny_skill_prefixes=_ENTERPRISE_DENY_SKILL_PREFIXES + _PURE_FABRIC_DROP,
    core_subtrees=_PUBLIC_CORE_SUBTREES | frozenset({"pm"}),
    core_hold_globs=_CORE_LAB_OPERATIONAL_HOLD_GLOBS,
)

# The Generali farm (TICK-036): enterprise baseline + the NO-FABRIC filter — the
# MIRROR of Lavazza. DBR + Power BI Import-mode, no Fabric capacity / lakehouse /
# DirectLake (the acme-powerbi pattern). Keeps databricks-* + powerbi-model-*/
# publish + pbir-*; drops fabric-* + powerbi-directlake-create. That powerbi-*
# family split (DirectLake out, Import in) is the deny-prefix granularity the
# taxonomy flagged to verify before Generali — it works because the deny is a
# prefix match: ``powerbi-directlake`` catches only the DirectLake skill.
GENERALI_FARM = PublishProfile(
    name="generali-farm",
    lab_only_path_globs=_LAB_ONLY_PATH_GLOBS,
    deny_skill_prefixes=_ENTERPRISE_DENY_SKILL_PREFIXES + _NO_FABRIC_DROP,
    core_subtrees=_PUBLIC_CORE_SUBTREES | frozenset({"pm"}),
    core_hold_globs=_CORE_LAB_OPERATIONAL_HOLD_GLOBS,
)

# Registry for CLI / propagate lookup by name.
PROFILES: dict[str, PublishProfile] = {
    p.name: p for p in (PUBLIC, ENTERPRISE_BASE, LAVAZZA_FARM, GENERALI_FARM)
}


def get_profile(name: str) -> PublishProfile:
    """Look up a publish profile by name; ``ValueError`` on an unknown name."""
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"unknown publish profile {name!r}; "
            f"known profiles: {', '.join(sorted(PROFILES))}"
        ) from None


# Frontmatter fence at the very top of a skill ``.md`` file.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _read_skill_meta(src: Path) -> tuple[str | None, bool]:
    """Return ``(status, lab_only)`` from a skill's YAML frontmatter.

    Missing frontmatter, an unreadable file, or absent fields yield
    ``(None, False)`` — i.e. a status-less, non-lab-only skill (grandfathered
    eligible). Malformed frontmatter is treated the same rather than crashing
    the publish.
    """
    try:
        text = src.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return (None, False)
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return (None, False)
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return (None, False)
    if not isinstance(fm, dict):
        return (None, False)
    status = fm.get("status")
    return (status if isinstance(status, str) else None, bool(fm.get("lab_only", False)))


def _skill_ships(
    skill_name: str,
    status: str | None,
    lab_only: bool,
    skills_include: set[str] | None,
    profile: PublishProfile = PUBLIC,
) -> bool:
    """Apply the TICK-006 maturity gate to a single skill. See the constants.

    ``profile`` selects the deny-prefix set (defaults to PUBLIC so existing
    callers and tests are behaviour-identical).
    """
    if any(skill_name.startswith(p) for p in profile.deny_skill_prefixes):
        return False
    if lab_only:
        return False
    if status in _NEVER_PUBLIC_STATUSES:
        return False
    if status == "preview":
        # Preview ships only when the distribution explicitly opts it in.
        return skills_include is not None and skill_name in skills_include
    # stable, or missing (grandfathered) → eligible
    return True


def _core_path_ships(rel: str, profile: PublishProfile = PUBLIC) -> bool:
    """Whether a ``core/...`` path is allowed to ship (subtree allowlist).

    Top-level files directly under ``core/`` always ship. A path
    ``core/<x>/...`` ships iff ``<x>`` is in the profile's ``core_subtrees``
    and the path is not held by the profile's ``core_hold_globs``. (The
    always-on lab-only floor is applied separately, before this gate.)
    ``profile`` defaults to PUBLIC — whose ``core_hold_globs`` is the union of
    the PM-tooling hold and the lab-operational hold — so existing callers and
    tests are behaviour-identical.
    """
    parts = rel.split("/")
    if len(parts) <= 2:
        return True  # top-level file under core/ (e.g. core/__init__.py)
    if parts[1] not in profile.core_subtrees:
        return False
    if _matches_any_glob(rel, profile.core_hold_globs):
        return False
    return True

# Text file extensions we run BLOCK / REPLACE on. Binary files are copied
# byte-for-byte without content scan. Includes non-extensioned conventions
# (.gitignore, .gitattributes, .env.example) so the REPLACE pass catches
# corporate-name mentions in those files.
_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".md", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini",
    ".txt", ".rst", ".sh", ".ps1", ".bat", ".sql", ".tmdl", ".tmsl",
    ".gitignore", ".gitattributes", ".env.example",
})

# Files without an extension that are nonetheless text and should be
# scanned (e.g. ``LICENSE``, ``Makefile``, ``Dockerfile``).
_TEXT_NAMES_NO_EXT: frozenset[str] = frozenset({
    "LICENSE", "Makefile", "Dockerfile", "CODEOWNERS",
})

# Wrapper suffixes on config templates (``decks.yaml.example``,
# ``foo.json.template``). The file is text and MUST be scanned on its inner
# type — these are the public-facing config samples, exactly where a stray
# corporate name or client slug would leak. Without unwrapping, ``.suffix``
# is ``.example`` (not in _TEXT_EXTENSIONS) and the file would be byte-copied
# verbatim, bypassing both REPLACE and BLOCK.
_TEXT_WRAPPER_SUFFIXES: frozenset[str] = frozenset({
    ".example", ".template", ".sample",
})


def _is_text_file(src: Path) -> bool:
    """Whether to run REPLACE/BLOCK scanning on ``src`` (vs byte-copy).

    Unwraps a trailing template suffix so ``foo.yaml.example`` is scanned as
    ``.yaml`` and ``foo.json.template`` as ``.json``.
    """
    if src.name in _TEXT_NAMES_NO_EXT:
        return True
    suffix = src.suffix.lower()
    if suffix in _TEXT_WRAPPER_SUFFIXES:
        suffix = Path(src.stem).suffix.lower()
    return suffix in _TEXT_EXTENSIONS


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Compile a gitignore-style glob into a regex.

    Supports gitignore semantics:

    - ``**/X`` matches ``X`` at any depth, including the root (zero dirs).
      Implemented as ``(?:.*/)?X``. Without this, ``**/.mcp.json`` would
      match ``subdir/.mcp.json`` but miss the root-level ``.mcp.json``.
    - ``**`` standalone (not followed by ``/``) matches anything including
      slashes — ``.*``.
    - ``*`` matches within a single path segment — ``[^/]*``.
    - ``?`` matches a single non-slash character — ``[^/]``.

    Other regex metacharacters are escaped. Pattern is anchored ``^...$``.
    """
    escaped: list[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if i + 1 < len(glob) and glob[i + 1] == "*":
                # ``**/`` → zero or more directory segments (incl. root)
                if i + 2 < len(glob) and glob[i + 2] == "/":
                    escaped.append("(?:.*/)?")
                    i += 3
                    continue
                # Standalone ``**`` → anything including slashes
                escaped.append(".*")
                i += 2
                continue
            escaped.append(r"[^/]*")
        elif c == "?":
            escaped.append(r"[^/]")
        elif c in r".+()[]{}^$|\\":
            escaped.append("\\" + c)
        else:
            escaped.append(c)
        i += 1
    return re.compile("^" + "".join(escaped) + "$")


# Cached compiled lab-only globs, keyed by profile name (compiled on first use).
_LAB_ONLY_REGEX_CACHE: dict[str, list[re.Pattern[str]]] = {}


def _matches_any_glob(rel_path: str, globs: Iterable[str]) -> bool:
    """Return True if ``rel_path`` matches any of the given glob patterns."""
    rel_path = rel_path.replace("\\", "/")
    for g in globs:
        if _glob_to_regex(g).match(rel_path):
            return True
    return False


def _matches_lab_only(rel_path: str, profile: PublishProfile = PUBLIC) -> bool:
    """Return True if ``rel_path`` is in the profile's lab-only exclusion list.

    ``profile`` defaults to PUBLIC. The floor is the same set across profiles
    by design (a safety invariant), but the regex set is cached per profile
    name so a future profile with a different floor stays correct.
    """
    regexes = _LAB_ONLY_REGEX_CACHE.get(profile.name)
    if regexes is None:
        regexes = [_glob_to_regex(g) for g in profile.lab_only_path_globs]
        _LAB_ONLY_REGEX_CACHE[profile.name] = regexes
    rel_path = rel_path.replace("\\", "/")
    return any(rgx.match(rel_path) for rgx in regexes)


# ---------------------------------------------------------------------------
# Sanitization rules — parsed from sanitization-patterns.md
# ---------------------------------------------------------------------------

Category = Literal["block", "replace", "allow"]


@dataclass(frozen=True)
class SanitizationRule:
    name: str
    pattern: re.Pattern
    category: Category
    scope_globs: tuple[str, ...]  # which files the rule applies to
    replacement: str | None = None  # only for REPLACE
    rationale: str = ""

    def applies_to(self, rel_path: str) -> bool:
        if not self.scope_globs:
            return True
        # Use the engine's _glob_to_regex (gitignore-style ``**/X`` matches at
        # any depth including root) rather than pathlib.Path.match, which
        # silently misses root-level files for ``**/*`` patterns.
        rel = rel_path.replace("\\", "/")
        for g in self.scope_globs:
            # Fast-path: ``**/*`` means "any file" — pathlib disagrees.
            if g == "**/*":
                return True
            if _glob_to_regex(g).match(rel):
                return True
        return False


def parse_patterns_yaml(patterns_path: Path) -> list[SanitizationRule]:
    """Parse the private sanitization values YAML and return the rule list.

    Expected shape (under each of ``block``, ``replace``, ``allow`` keys):

    .. code-block:: yaml

        block:
          - name: <rule-name>
            pattern: '<python-regex>'
            scope: ['**/*']
            rationale: "<why>"
            last_updated: '2026-MM-DD'

        replace:
          - name: ...
            pattern: ...
            replacement: '<sub-string>'
            scope: [...]

        allow:
          - name: ...
            pattern: ...
            scope: [...]
    """
    with patterns_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    rules: list[SanitizationRule] = []
    for category in ("block", "replace", "allow"):
        for entry in data.get(category) or []:
            name = entry.get("name", "")
            pattern_str = entry.get("pattern")
            if not pattern_str:
                continue
            try:
                pat = re.compile(pattern_str)
            except re.error:
                continue  # malformed — skip rather than crash publish
            scope = entry.get("scope") or ["**/*"]
            if isinstance(scope, str):
                scope = [scope]
            rules.append(
                SanitizationRule(
                    name=name,
                    pattern=pat,
                    category=category,  # type: ignore[arg-type]
                    scope_globs=tuple(scope),
                    replacement=entry.get("replacement"),
                    rationale=entry.get("rationale", ""),
                )
            )
    return rules


# Back-compat shim — callers/tests that still reference the old name get the
# YAML loader. The .md file is now structural-only documentation.
parse_patterns_file = parse_patterns_yaml


# ---------------------------------------------------------------------------
# Publish report
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    file: str
    line: int
    pattern_name: str
    matched_text: str

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.line} pattern={self.pattern_name} "
            f"match={self.matched_text!r}"
        )


@dataclass
class Replacement:
    file: str
    pattern_name: str
    count: int


@dataclass
class PublishReport:
    target_dir: Path
    files_published: int = 0
    files_filtered: int = 0
    replacements: list[Replacement] = field(default_factory=list)
    block_violations: list[Violation] = field(default_factory=list)
    allow_misses: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.block_violations and not self.allow_misses


# ---------------------------------------------------------------------------
# Walk + filter
# ---------------------------------------------------------------------------


def walk_publishable(
    lab_root: Path,
    distribution_slug: str,
    skills_include: set[str] | None,
    profile: PublishProfile = PUBLIC,
) -> Iterator[Path]:
    """Yield lab-relative paths that should be copied to the target.

    Applies, in order:
    - VCS / cache pruning + lab-only path globs (the always-on deny floor:
      ops.log, feedback, marketing, state, credentials, ...)
    - Other distributions excluded (only ``distributions/{slug}/`` survives)
    - Core subtree allowlist on ``core/...`` (default-deny new core subtrees;
      hold PM tooling) — see ``_core_path_ships``
    - Skill maturity gate on ``.claude/commands/<name>.md`` (legacy) and on
      ``.claude/skills/<name>/**`` (canonical Agent-Skills folder, gated as a
      unit by the status in its ``SKILL.md`` so bundled files follow the skill)
      — see ``_skill_ships``. ``skills_include`` is the preview opt-in set (the
      distribution's ``skills.include``); ``None`` means no preview is opted in.

    ``profile`` selects the curation knobs (deny set, core subtrees + holds,
    lab-only floor). Defaults to PUBLIC so the public publish is unchanged.
    """
    for src in lab_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(lab_root).as_posix()

        # Exclude .git and other VCS / cache aggressively at the top
        if any(seg in {".git", ".venv", "__pycache__", "node_modules"}
               for seg in src.relative_to(lab_root).parts):
            continue

        # Other distributions: keep only the requested slug
        if rel.startswith("distributions/") and not rel.startswith(
            f"distributions/{distribution_slug}/"
        ):
            continue

        # Lab-only path globs (security floor — applied before curation gates)
        if _matches_lab_only(rel, profile):
            continue

        # Core subtree allowlist (default-deny new subtrees + PM-tooling hold)
        if rel.startswith("core/") and not _core_path_ships(rel, profile):
            continue

        # Skill maturity gate — legacy .claude/commands/<name>.md AND the
        # canonical Agent-Skills folder .claude/skills/<name>/** (the whole
        # folder is gated as a unit by the status in its SKILL.md, so bundled
        # files ship iff the skill ships).
        if rel.startswith(".claude/commands/") and rel.endswith(".md"):
            skill_name = Path(rel).stem
            status, lab_only = _read_skill_meta(src)
            if not _skill_ships(skill_name, status, lab_only, skills_include, profile):
                continue
        elif rel.startswith(".claude/skills/"):
            parts = rel.split("/")
            if len(parts) >= 4:  # .claude/skills/<name>/<file...>
                skill_name = parts[2]
                skill_md = lab_root / ".claude" / "skills" / skill_name / "SKILL.md"
                status, lab_only = _read_skill_meta(skill_md)
                if not _skill_ships(skill_name, status, lab_only, skills_include, profile):
                    continue

        yield src


# ---------------------------------------------------------------------------
# Sanitization application
# ---------------------------------------------------------------------------


_NOQA_PATTERN = re.compile(
    r"noqa:\s*ade-ops-sanitize=([\w\-]+)",
    re.IGNORECASE,
)


def _line_has_noqa(line: str, rule_name: str) -> bool:
    """Return True if the line carries a noqa exemption for ``rule_name``."""
    for m in _NOQA_PATTERN.finditer(line):
        if m.group(1) == rule_name:
            return True
    return False


def apply_replacements(
    text: str, rel_path: str, rules: list[SanitizationRule]
) -> tuple[str, list[Replacement]]:
    """Run all REPLACE rules in scope on ``text``. Return new text + log."""
    log: list[Replacement] = []
    for rule in rules:
        if rule.category != "replace":
            continue
        if not rule.applies_to(rel_path):
            continue
        new_text, count = rule.pattern.subn(rule.replacement or "", text)
        if count:
            log.append(Replacement(rel_path, rule.name, count))
            text = new_text
    return text, log


def scan_block_violations(
    text: str, rel_path: str, rules: list[SanitizationRule]
) -> list[Violation]:
    """Run all BLOCK rules in scope. Honours per-line noqa exemptions."""
    violations: list[Violation] = []
    lines = text.splitlines()
    for rule in rules:
        if rule.category != "block":
            continue
        if not rule.applies_to(rel_path):
            continue
        for n, line in enumerate(lines, start=1):
            for m in rule.pattern.finditer(line):
                if _line_has_noqa(line, rule.name):
                    continue
                violations.append(
                    Violation(rel_path, n, rule.name, m.group(0))
                )
    return violations


def verify_allow_assertions(
    target_dir: Path, rules: list[SanitizationRule]
) -> list[str]:
    """Return the names of ALLOW rules whose pattern is missing in target."""
    misses: list[str] = []
    for rule in rules:
        if rule.category != "allow":
            continue
        # The scope globs identify which file(s) must contain the pattern.
        found = False
        candidate_paths = list(target_dir.rglob("*"))
        for g in rule.scope_globs:
            for path in candidate_paths:
                if not path.is_file():
                    continue
                rel = path.relative_to(target_dir).as_posix()
                if not Path(rel).match(g):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if rule.pattern.search(text):
                    found = True
                    break
            if found:
                break
        if not found:
            misses.append(rule.name)
    return misses


# ---------------------------------------------------------------------------
# Cross-harness catalog projection (published target)
# ---------------------------------------------------------------------------


def project_agents_catalog(target_dir: Path) -> int:
    """Regenerate ``target_dir/.agents/skills`` from ``target_dir/.claude/skills``.

    ``.agents/skills`` is the vendor-neutral catalog that Codex (and other
    Agent-Skills consumers) read — they do NOT fall back to ``.claude/skills``.
    A published distribution must therefore carry it. It is regenerated from the
    MATERIALISED (post-maturity-filter, post-sanitization) ``.claude/skills`` in
    the target — never the lab's unfiltered ``.agents/`` (which ``walk_publishable``
    excludes) — so the neutral catalog contains exactly the skills that shipped.
    Exact mirror (stale entries cleaned), idempotent. Returns the skill count.
    """
    src = target_dir / ".claude" / "skills"
    dst = target_dir / ".agents" / "skills"
    if not src.is_dir():
        return 0
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    return sum(1 for _ in dst.glob("*/SKILL.md"))


def _publish_gitignore_tracks_agents(target_dir: Path) -> None:
    """Drop the ``.agents/`` ignore entry from the published ``.gitignore``.

    In the lab ``.agents/`` is a gitignored generated artifact. In a published
    distribution the projected ``.agents/skills`` IS a shipped artifact (Codex
    reads it), so it must be tracked — otherwise ``publish_to_git``'s
    ``git add .`` would skip it and a fresh clone would carry no neutral catalog.
    Removes only an exact ``.agents`` / ``.agents/`` line; the rest of the file
    is untouched. No-op if the file or the entry is absent.
    """
    gi = target_dir / ".gitignore"
    if not gi.exists():
        return
    lines = gi.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [ln for ln in lines if ln.strip().rstrip("/") != ".agents"]
    if len(kept) != len(lines):
        gi.write_text("".join(kept), encoding="utf-8")


# ---------------------------------------------------------------------------
# Top-level publish
# ---------------------------------------------------------------------------


def publish(
    lab_root: Path,
    distribution_slug: str,
    target_dir: Path,
    *,
    patterns_file: Path | None = None,
    dry_run: bool = False,
    profile: PublishProfile = PUBLIC,
    extra_skills_include: set[str] | None = None,
) -> PublishReport:
    """Materialise a publish of the given distribution for ``profile``.

    Args:
        lab_root: Lab repo root (contains ``core/`` and ``distributions/``).
        distribution_slug: e.g. ``reference``. Only this distribution + ``core/``
            + whitelisted skills + root files survive in the target.
        target_dir: Destination directory. Created if missing. Existing
            contents are preserved unless overwritten by this publish
            (idempotent re-runnable, no destructive delete).
        patterns_file: Override the default
            ``{lab_root}/core/conventions/sanitization-patterns.md``.
        dry_run: When True, no files are written and target_dir is not
            touched. The report still includes the violation list and the
            replacement log (computed in memory).
        profile: Curation profile (defaults to ``PUBLIC``). Selects the deny
            set, core subtrees + holds, and lab-only floor. The BLOCK / REPLACE
            / ALLOW sanitization rules are profile-independent — the
            cross-client leak boundary applies to every target.
        extra_skills_include: Preview skills to opt in beyond the distribution's
            project.yaml ``skills.include`` (e.g. the enterprise baseline's full
            preview set). Unioned with the distribution-derived set; the maturity
            gate + profile deny floor still apply.

    Returns:
        ``PublishReport`` with the publish stats + any violations / misses.
        Caller (CLI) decides whether to abort on ``not report.ok``.
    """
    lab_root = lab_root.resolve()
    target_dir = target_dir.resolve()
    patterns_file = patterns_file or (
        lab_root / "core" / "conventions" / "_private_sanitization_values.yaml"
    )
    if not patterns_file.exists():
        raise FileNotFoundError(
            f"private sanitization values not found at {patterns_file}. "
            f"This file is lab-only (gitignored) and required for the publish "
            f"engine to construct the BLOCK / REPLACE / ALLOW rule set."
        )

    rules = parse_patterns_yaml(patterns_file)

    # Resolve distribution's skill whitelist
    dist_project_yaml = (
        lab_root / "distributions" / distribution_slug / "projects"
    )
    skills_include: set[str] | None = None
    for proj_dir in dist_project_yaml.glob("*"):
        cfg_path = proj_dir / "config" / "project.yaml"
        if not cfg_path.exists():
            continue
        try:
            cfg = load_project(proj_dir)
        except (FileNotFoundError, KeyError):
            continue
        if cfg.skills_include is not None:
            # The preview opt-in set is distribution-wide: each project declares
            # the preview skills it uses; the publish unions them across the
            # distribution's projects (a multi-project distro like reference
            # spreads its scenario skills across project.yaml files).
            if skills_include is None:
                skills_include = set()
            skills_include |= set(cfg.skills_include)

    # Explicit additions (e.g. the enterprise baseline opts in its full preview
    # skill set, beyond what any single distribution's project.yaml declares).
    if extra_skills_include:
        skills_include = (skills_include or set()) | set(extra_skills_include)

    report = PublishReport(target_dir=target_dir)

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for src in walk_publishable(lab_root, distribution_slug, skills_include, profile):
        rel = src.relative_to(lab_root).as_posix()
        dst = target_dir / rel

        # Binary files: byte copy, no content scan. ``LICENSE``, ``Makefile``,
        # ``Dockerfile``, ``CODEOWNERS`` are extensionless but text; ``*.example``
        # / ``*.template`` config samples are scanned on their inner type —
        # ``_is_text_file`` handles both so REPLACE/BLOCK reach them.
        if not _is_text_file(src):
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            report.files_published += 1
            continue

        # Text file: read, REPLACE, BLOCK-scan, write
        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Treat as binary if UTF-8 fails
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            report.files_published += 1
            continue

        new_text, replacements = apply_replacements(text, rel, rules)
        report.replacements.extend(replacements)

        violations = scan_block_violations(new_text, rel, rules)
        report.block_violations.extend(violations)

        if not dry_run and not violations:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(new_text, encoding="utf-8")
        report.files_published += 1

    if not dry_run and report.ok:
        report.allow_misses = verify_allow_assertions(target_dir, rules)
        # Cross-harness catalog: regenerate .agents/skills from the FILTERED
        # target .claude/skills (exactly the skills that shipped — never the
        # lab's unfiltered .agents/, which the walk excludes) so Codex sees the
        # published catalog, and untrack .agents/ in the published .gitignore so
        # publish_to_git's `git add .` commits it.
        project_agents_catalog(target_dir)
        _publish_gitignore_tracks_agents(target_dir)

    return report


# ---------------------------------------------------------------------------
# Orphan release model: wipe target + single-commit force-push.
# ---------------------------------------------------------------------------

# Rationale: the public preview is a release artefact, not a developer
# workshop. Keeping the full git history would expose the prior state of
# every security fix and IP redaction via ``git log -p`` — even when the
# current HEAD is clean. Wiping the target before each publish + force-
# pushing a single commit guarantees that the public history reveals
# nothing about what was sanitized when. Provenance lives in the lab
# private repo, which retains the full author + co-author trail.
#
# Opt-out via ``preserve_history=True`` exists for the rare case of an
# incremental publish (e.g. CI re-run after a transient network failure).
# It is intentionally NOT the default.


def _on_rm_error(func, path, exc_info):
    """``shutil.rmtree`` error handler that clears read-only bits.

    Windows marks files under ``.git/objects/`` read-only; the default
    ``rmtree`` raises on those. This handler chmods +write and retries.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def wipe_for_orphan(target_dir: Path) -> int:
    """Remove every entry under ``target_dir`` (the dir itself survives).

    Returns the number of top-level entries removed. Safe on Windows
    against read-only ``.git/objects`` blobs.
    """
    target_dir = target_dir.resolve()
    if not target_dir.exists():
        return 0
    removed = 0
    for entry in target_dir.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, onerror=_on_rm_error)
        else:
            try:
                entry.chmod(stat.S_IWRITE)
            except OSError:
                pass
            entry.unlink()
        removed += 1
    return removed


@dataclass
class GitPublishResult:
    """Result of ``publish_to_git()``."""

    target_dir: Path
    remote: str
    branch: str
    commit_sha: str = ""
    commit_message: str = ""
    pushed: bool = False
    skipped_reason: str = ""


def _run_git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git subprocess in ``cwd`` and surface stderr on failure."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (cwd={cwd}):\n"
            f"  stdout: {proc.stdout.strip()}\n"
            f"  stderr: {proc.stderr.strip()}"
        )
    return proc


def publish_to_git(
    target_dir: Path,
    *,
    remote: str,
    branch: str = "main",
    lab_rev: str = "",
    commit_message: str | None = None,
    author_name: str | None = None,
    author_email: str | None = None,
    dry_run: bool = False,
) -> GitPublishResult:
    """Initialise a fresh repo in ``target_dir`` and force-push a single commit.

    Implements the orphan release model: there is no resumption of any
    prior history. The caller is expected to have wiped ``target_dir``
    before populating it with publish output, but this function does NOT
    wipe — it only refuses to run if a ``.git/`` is already present
    (anti-foot-gun).

    Args:
        target_dir: Populated with publish output, ``.git`` absent.
        remote: HTTPS or SSH remote URL.
        branch: Branch name on the remote (default ``main``).
        lab_rev: Short SHA of the lab HEAD at publish time, recorded in
            the commit message for traceability back to the lab.
        commit_message: Override the auto-generated message. If None,
            generates ``Release YYYY-MM-DDTHH:MMZ | rev <lab_rev>``.
        author_name, author_email: Override identity. If None, uses
            target repo's local config or falls back to global config.
        dry_run: If True, validate inputs but do not execute git.

    Returns:
        ``GitPublishResult`` with commit SHA + message + push flag.

    Raises:
        RuntimeError: target has a ``.git/`` (caller must wipe first),
            or any git command fails.
        FileNotFoundError: target is empty (nothing to publish).
    """
    target_dir = target_dir.resolve()
    if not target_dir.exists():
        raise FileNotFoundError(f"target dir does not exist: {target_dir}")
    if (target_dir / ".git").exists():
        raise RuntimeError(
            f"target dir already contains a .git: {target_dir}. "
            f"The orphan release model requires a fresh repo per publish. "
            f"Wipe the target first (or pass --preserve-history to opt out)."
        )
    if not any(target_dir.iterdir()):
        raise FileNotFoundError(
            f"target dir is empty: {target_dir}. "
            f"Run the publish materialise step before the git step."
        )

    if commit_message is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        rev_part = f" | rev {lab_rev}" if lab_rev else ""
        commit_message = f"Release {ts}{rev_part}"

    result = GitPublishResult(
        target_dir=target_dir,
        remote=remote,
        branch=branch,
        commit_message=commit_message,
    )

    if dry_run:
        result.skipped_reason = "dry_run"
        return result

    # Fresh init. Use ``--initial-branch`` so we don't depend on whatever
    # ``init.defaultBranch`` is configured globally.
    _run_git(["init", f"--initial-branch={branch}"], cwd=target_dir)

    if author_name:
        _run_git(["config", "user.name", author_name], cwd=target_dir)
    if author_email:
        _run_git(["config", "user.email", author_email], cwd=target_dir)

    _run_git(["add", "."], cwd=target_dir)
    _run_git(["commit", "-m", commit_message], cwd=target_dir)

    sha_proc = _run_git(["rev-parse", "HEAD"], cwd=target_dir)
    result.commit_sha = sha_proc.stdout.strip()

    _run_git(["remote", "add", "origin", remote], cwd=target_dir)
    _run_git(["push", "--force", "origin", branch], cwd=target_dir)
    result.pushed = True

    return result


def lab_head_short(lab_root: Path) -> str:
    """Return the 7-char SHA of the lab repo HEAD, or '' if not a git repo."""
    try:
        proc = _run_git(
            ["rev-parse", "--short=7", "HEAD"],
            cwd=lab_root.resolve(),
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (FileNotFoundError, RuntimeError):
        pass
    return ""
