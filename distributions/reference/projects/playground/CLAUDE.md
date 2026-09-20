# playground — operational on Databricks in ~5 minutes

The fastest way to see ade-ops do real work. **Databricks-only**: no Fabric, no
Power BI, no Azure. A self-contained synthetic dataset (generated with pure
Spark — no `samples.*`, no CSV) + one analytics notebook. All you need is a
Databricks workspace (free-tier / Community Edition is fine) and a PAT.

> This is the "minimal infra" slice of the zero-setup playground. A fully local
> playground (a DuckDB connector — *nothing* but your laptop) is the planned V2.
> Today you still need a free Databricks workspace; that's the only requirement.

## What you get

| Table | Created by | What it is |
|---|---|---|
| `pg_products`, `pg_customers`, `pg_sales` | `_setup/generate_synthetic_data` | synthetic dimensions + fact (50 / 200 / 5000 rows) |
| `pg_daily_sales_summary` | `analytics/daily_sales_summary` | revenue / quantity / tx-count per day · category · region |

## 5-minute run

1. **Credentials + env** (one-time)
   ```powershell
   cp config/credentials.example.yaml config/credentials.yaml   # add your PAT
   $env:DEMO_USER_EMAIL = "you@example.com"                      # your Databricks user
   $env:DATABRICKS_HOST = "https://<your-ws>.cloud.databricks.com"
   $env:DATABRICKS_TOKEN = "dapi..."                            # or put it in credentials.yaml
   ```

2. **Check you're ready**
   ```
   python -m core.cli preflight --project distributions/reference/projects/playground
   ```

3. **Seed the synthetic data** — deploy the seeder, then run it once in Databricks
   ```
   python -m core.cli push --project distributions/reference/projects/playground \
       --env dev --scope notebooks --filter _setup
   # In the Databricks UI (or /databricks-run), run _setup/generate_synthetic_data
   ```
   (The seeder is excluded from the normal synced pipeline, so push it explicitly
   with `--filter _setup` this once.)

4. **Deploy + run the analytics notebook**
   ```
   python -m core.cli push --project distributions/reference/projects/playground --env dev
   python -m core.cli databricks-run analytics/daily_sales_summary --env dev --cluster <id>
   ```

5. **Query the result**
   ```
   python -m core.cli databricks-query --env dev \
       "SELECT category, ROUND(SUM(total_revenue),2) revenue \
        FROM pg_daily_sales_summary GROUP BY category ORDER BY revenue DESC"
   ```

That's it — clone → push → run → query, no cloud beyond a free Databricks
workspace. The same commands back the `/databricks-*` skills, so you can also
just ask the agent ("run the playground analytics and show me revenue by
category") and it drives these for you.

## Where to go next

- Add a BI layer → [`../acme-powerbi/`](../acme-powerbi/) (Databricks → Power BI Import)
- The full migration chain → [`../databricks-fabric-migration/`](../databricks-fabric-migration/) (Databricks → Fabric → Power BI DirectLake)
