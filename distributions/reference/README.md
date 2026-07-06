# Reference distribution

OSS reference implementation of the ade-ops Databricks → Fabric +
Power BI workflow. Backed by Databricks built-in `samples.tpch.*` so any
adopter can run end-to-end without provisioning a dataset.

## Projects

| Project | Path | Purpose |
|---|---|---|
| Playground (Databricks-only) | [`projects/playground/`](projects/playground/) | **Start here** — operational in ~5 min: synthetic data (pure Spark, no CSV) + one analytics notebook, no Fabric/PBI. Just a free Databricks workspace + PAT |
| Databricks → Fabric migration | [`projects/databricks-fabric-migration/`](projects/databricks-fabric-migration/) | Medallion (bronze / silver / gold) + DirectLake semantic + PBIR report |
| Databricks → Power BI (Import) | [`projects/acme-powerbi/`](projects/acme-powerbi/) | Same medallion, but an Import-mode semantic model reading Databricks directly — no Fabric capacity / lakehouse (PBI Pro is enough) |

## Getting started

Each project's `CLAUDE.md` has the first-run setup, environment variables, and
end-to-end workflow:

- [`projects/playground/CLAUDE.md`](projects/playground/CLAUDE.md)
  — fastest start, Databricks-only, ~5 minutes
- [`projects/databricks-fabric-migration/CLAUDE.md`](projects/databricks-fabric-migration/CLAUDE.md)
  — the full Databricks → Fabric → Power BI chain (DirectLake)
- [`projects/acme-powerbi/CLAUDE.md`](projects/acme-powerbi/CLAUDE.md)
  — the lighter Databricks → Power BI Import variant

## Brand

Sample brand is **AcmeSales** — an industry-standard fake-company name
(à la Acme Corp). Used consistently across the semantic model, the
report, and the Fabric workspace naming. Replace with your own brand
when you fork this distribution for a real project.
