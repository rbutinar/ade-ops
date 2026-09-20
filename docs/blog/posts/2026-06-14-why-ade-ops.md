---
date: 2026-06-14
categories:
  - Framework
authors:
  - rbutinar
---

# Why I built ade-ops

Most data-platform tooling optimises for the happy path of a single product
demo. Real analytics teams live somewhere messier: multiple environments,
remote workspaces that are the real source of truth, promotions that have to be
visible and reversible, and — increasingly — AI agents doing some of the work.
ade-ops is my answer to operating *that* reality safely.

<!-- more -->

A few principles it's built around:

- **The remote is authoritative, and every write is gated.** You diff before you
  push; nothing changes a remote environment without an explicit confirmation.
  This is the single most important property when an agent is in the loop.
- **One source of truth, many environments.** You author once in `src/`;
  declarative overlays handle what differs between DEV, CERT, and PROD. No
  copy-paste drift.
- **The framework admits what it doesn't know.** Skills carry a maturity marker,
  and converters tag their output honestly — `compat`, `light`, `heavy`, or
  `impossible`. The last two are your call, not the tool's.
- **Platform-indifferent by design.** Databricks, Microsoft Fabric, or both —
  the engine treats each the same way. ade-ops isn't here to move you off one
  platform onto another; it's here to operate whatever you run.

It's open source, in early public preview, and built in the open. If you operate
analytics platforms — with or without agents — I'd love your
[feedback](https://github.com/rbutinar/ade-ops/discussions). More notes to
follow as the work continues.
