# reference — ade-ops public reference distribution

OSS reference implementation of the Databricks → Fabric + Power BI workflow,
backed by Databricks built-in `samples.tpch.*` data so any adopter can run
end-to-end without provisioning their own dataset.

## Scope

- Showcase the DBR → Fabric migration + medallion (bronze / silver / gold)
  + DirectLake semantic model + PBIR report workflow
- Multi-environment lifecycle (DEV / CERT / PROD) on synthetic TPC-H samples
- Brand kept as **AcmeSales** for continuity with the original DDF demo
- Zero credentials shipped — adopters supply their own via `credentials.yaml`

## Projects

| Project | Path | Status |
|---|---|---|
| Databricks → Fabric migration | `projects/databricks-fabric-migration/` | reference |

## Conventions

- All synthetic data — bronze layer reads from `samples.tpch.*` (Databricks
  built-in UC catalog, available on every workspace including free-tier)
- No PII, no real client references, safe to publish and demo openly
- English-only outputs (`/demo-mode` available for recording-safety overrides)

## Personas (publicly available)

The 6 generalist personas listed in the root `README.md` are the recommended
entry points. Sub-skills (`/databricks-*`, `/fabric-*`, `/pbir-*`,
`/powerbi-*`) are available as direct tool invocations for users who prefer
explicit control.
