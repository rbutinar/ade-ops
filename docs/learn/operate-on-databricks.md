---
description: "A ~5-minute hands-on lab: stand up a small synthetic project on your own Databricks workspace, then deploy, run and query it — driving the ade-ops engine end to end."
---

# Operate on Databricks in ~5 minutes

**What you'll do:** stand up a small synthetic project on your own Databricks
workspace, deploy it, run it, and query the result — driving the ade-ops engine
end to end. No Fabric, no Power BI, no migration: this module is the purest look
at *what the engine does*.

**You'll need:** a Databricks workspace (Community Edition works) and a personal
access token. That's it.

!!! tip "Video walkthrough"
    A short screen-recorded walkthrough of this module is on the way — it will be
    embedded here. Until then, the steps below are the full path.

## 1. Set up the playground project

The reference distribution ships a self-contained, Databricks-only project that
generates its own synthetic data (pure Spark — no external dataset). Follow the
[getting started](../getting-started/README.md) bootstrap, then point onboarding
at the `databricks-only` scenario:

```
/ade-ops-onboarding
```

It routes you to `distributions/reference/projects/playground/` — a synthetic
data generator plus one analytics notebook, designed to be operational in about
five minutes.

## 2. See what would change, then push

ade-ops never writes to a remote without showing you the diff first.

```bash
python -m core.cli status                              # env × scope overview
python -m core.cli push --env dev --scope notebooks --dry-run   # preview
python -m core.cli push --env dev --scope notebooks             # upload (after you confirm)
```

The `--dry-run` shows exactly what will land. The real push asks for explicit
confirmation — this human gate is the heart of the framework.

## 3. Run it

```bash
python -m core.cli databricks-run --env dev <notebook>
```

This seeds the synthetic tables and runs the analytics notebook on your
workspace.

## 4. Query the result

```bash
python -m core.cli databricks-query --env dev "SELECT * FROM pg_daily_sales_summary LIMIT 20"
```

You've now driven the full loop — author → preview → push → run → query — on your
own Databricks, with every remote write gated. That loop is the same regardless
of which BI layer (if any) you add later.

## Where to go next

- Add a BI layer: serve this Databricks gold layer to **Power BI** — see the
  [`databricks-to-powerbi` quickstart](../quickstart/databricks-to-powerbi.md).
- Understand the machinery: the [assembly pipeline](../concepts/architecture.md).
- Go multi-environment: promote DEV → CERT → PROD with the human-gated push
  (module landing soon).
