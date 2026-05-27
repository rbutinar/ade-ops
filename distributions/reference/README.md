# Reference distribution

OSS reference implementation of the ade-ops Databricks → Fabric +
Power BI workflow. Backed by Databricks built-in `samples.tpch.*` so any
adopter can run end-to-end without provisioning a dataset.

## Projects

| Project | Path | Purpose |
|---|---|---|
| Databricks → Fabric migration | [`projects/databricks-fabric-migration/`](projects/databricks-fabric-migration/) | Medallion (bronze / silver / gold) + DirectLake semantic + PBIR report |

## Getting started

See [`projects/databricks-fabric-migration/CLAUDE.md`](projects/databricks-fabric-migration/CLAUDE.md)
for the first-run setup, environment variables, and end-to-end workflow.

## Brand

Sample brand is **AcmeSales** — an industry-standard fake-company name
(à la Acme Corp). Used consistently across the semantic model, the
report, and the Fabric workspace naming. Replace with your own brand
when you fork this distribution for a real project.
