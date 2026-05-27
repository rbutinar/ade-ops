# /fabric-warehouse-test — Read/Write Permission Test on a Fabric Warehouse

You are running a fixed set of 7 read/write probes against a Microsoft Fabric Warehouse schema to confirm deployment readiness (or diagnose a permissions issue).

> Needs the same Fabric Warehouse SQL connector + MSAL cache as `/fabric-sql-deploy` — both shipped: ``core.connectors.fabric_warehouse`` + ``core.platforms.fabric.auth``. Not relevant for <client> <project> today; kept for parity.

## Prerequisites

- ODBC Driver 17/18 for SQL Server
- `pyodbc`, `msal` Python packages
- Azure AD account that's expected to have at least Contributor on the schema

## Usage

```
/fabric-warehouse-test {schema} --env {env}
```

Where `schema` defaults to `automation` and otherwise is a specific schema to probe.

## The 7 Tests

1. **Schema exists** — `SELECT * FROM sys.schemas WHERE name = '{schema}'`
2. **Read existing objects** — count views + tables + procedures via `INFORMATION_SCHEMA`
3. **CREATE VIEW** — `CREATE VIEW {schema}.v_ade_access_test AS SELECT 1 AS ok, CURRENT_TIMESTAMP AS ts`
4. **SELECT** the test view
5. **CREATE TABLE** — minimal Fabric-compatible CREATE TABLE (no PK/IDENTITY/FK)
6. **INSERT** a couple of rows
7. **DROP** test view + table (cleanup; runs in `finally` even on test failures)

All test objects use the `ade_access_test` prefix so they can't collide with real objects.

## Behavior

### Step 1: Resolve & Connect

Same as `/fabric-sql-deploy`.

### Step 2: Run Tests in Order

Each test is `try/except`. Report PASS / FAIL per test with the error message on failure.

### Step 3: Cleanup

Cleanup runs in a `finally`:

```sql
DROP VIEW IF EXISTS {schema}.v_ade_access_test;
DROP TABLE IF EXISTS {schema}.t_ade_access_test;
```

### Step 4: Summary

```
=== FABRIC WAREHOUSE TEST — {env} / {schema} ===

✓ PASS  schema_exists
✓ PASS  read_objects
✓ PASS  create_view
✓ PASS  query_view
✓ PASS  create_table
✓ PASS  insert_data
✓ PASS  drop_objects

Result: 7/7 — ready for deploy.
```

On failures, surface the recommended action:

| Failed test | Likely cause | Recommended action |
|---|---|---|
| `schema_exists` | Schema not yet created | `/fabric-sql-deploy schema --env {env}` |
| `read_objects` | Viewer role missing | Ask admin for Viewer + Contributor |
| `create_view` / `create_table` | Contributor role missing | Ask admin |
| `insert_data` | Same as create | — |

### Step 5: Log

Read/write probe — only log on failure (success is the boring case):

```
{ISO_timestamp} | {role} | FABRIC-WH-TEST | {env} | {schema}: {n_failed} of 7 failed | fail
```

## Notes

- Token cached by MSAL (~1h validity, auto-refreshed).
- Test objects use `ade_access_test` prefix — easy to identify and clean up if the run dies mid-way.
- This skill is most useful when onboarding a new user to a workspace and you need to confirm their grants are right before they try a real deploy.
