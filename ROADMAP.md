# Roadmap

Where ade-ops is heading. This is **direction, not commitment** — items move,
re-order, and drop as real use teaches us what matters. Dates are deliberately
absent; the [CHANGELOG](CHANGELOG.md) records what has actually shipped.

ade-ops is in **public preview**. The engine, connectors, and operational skills
are working and used in production by the maintainer's team; the reference
distribution and onboarding flow are early.

## Now — public preview

- Three onboarding scenarios (Databricks-only, Databricks → Power BI, Databricks
  → Fabric) on synthetic data, BYO environment.
- The sync engine (`pull` / `push` / `diff` / `status`), preflight, and the
  Databricks / Fabric / Power BI operational skills.
- Scenario-aware onboarding as the canonical entry point.
- Contributor onboarding (issues, discussions, feedback).

## Next — adoption & feedback loop

- A per-user feedback loop and a pull-based **update** path so existing clones
  can take upstream improvements cleanly.
- Onboarding **walk-through videos** and written tutorials, linked from the docs.
- Onboarding that does more of the scaffolding for you (less manual quickstart).
- Command-first parity: every operational skill leads with a runnable CLI
  command, so the framework works well with any AI coding assistant.

## Later — widening

- A zero-setup **playground** scenario (fully local, synthetic data, no cloud
  account required).
- Additional scenarios (e.g. Fabric-first).
- Broader community surface as adoption grows.

## Tiers

The open-source **Community** tier stays a clean, single-operator-friendly
subset. Team-scale and governance capabilities — multi-operator coordination,
real-time fleet awareness, project-management cadence, managed publishing,
curated distribution baselines — live in a managed **Enterprise** tier. See
[capabilities & tiers](docs/reference/capabilities.md). Enterprise inquiries:
open an issue tagged `enterprise-inquiry` or reach the maintainer.

---

Have a need that isn't here? [Open a feature request](https://github.com/rbutinar/ade-ops/issues/new?template=feature_request.yml)
or [start a discussion](https://github.com/rbutinar/ade-ops/discussions) — the
roadmap is shaped by what adopters actually hit.
