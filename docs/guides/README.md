---
description: "Task-oriented ade-ops how-tos — diff before push, deploy, run and more — each mapped to a Claude Code skill and its plain-CLI equivalent."
---

# Guides

Task-oriented how-tos. Each assumes you've completed
[getting started](../getting-started/) and have a scaffolded project.

ade-ops is usable from a plain CLI, but reaches its potential when paired with an
AI coding assistant that drives its skills. Each task below maps to a **skill**
(Claude Code) and its **CLI** equivalent — pick whichever fits your workflow.

| Task | Skill | CLI |
|---|---|---|
| See what would change before pushing | `/ops-diff` | `python -m core.cli diff --env <env> --scope <scope>` |
| Deploy notebooks to a remote | `/ops-push`, `/databricks-deploy` | `python -m core.cli push --env <env> --scope notebooks` |
| Run a notebook or job | `/databricks-run` | `python -m core.cli databricks-run ...` |
| Query a SQL warehouse | `/databricks-query` | `python -m core.cli databricks-query ...` |
| Inspect job/notebook lineage | `/databricks-lineage` | `python -m core.cli databricks-lineage ...` |
| Deploy a notebook / pipeline to Fabric | `/fabric-notebook-deploy`, `/fabric-pipeline-deploy` | `python -m core.cli fabric-notebook-deploy ...` |
| Scaffold a Power BI semantic model | `/powerbi-model-create`, `/powerbi-directlake-create` | — |
| Publish a Power BI model | `/powerbi-publish` | — |
| Build a Power BI (PBIR) report | `/pbir-create`, `/pbir-report` | — |
| Assess a Databricks → Fabric migration | `/migration-assess` | `python -m core.cli migration-assess ...` |
| Promote across environments | `/ops-push --env cert` / `--env prod` | `python -m core.cli push --env cert` |

## How skills and the CLI relate

Each skill body (under `.claude/commands/` in the repo) leads with a runnable
`python -m core.cli …` command, then layers the agentic workflow on top. So a
skill doubles as a **how-to recipe** even if you're not using Claude Code — read
the command block and the steps, run them yourself.

> Step-by-step long-form guides are landing here as the docs build out. Until
> then, the skill bodies are the authoritative recipes, and the
> [quickstarts](../quickstart/) cover end-to-end scenario setup.
