"""Project scaffolding for ade-ops.

Generates a new project directory from the template, populated with
the configuration collected during interactive setup.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "full"


@dataclass
class PlatformConfig:
    """Configuration for a single platform."""
    name: str                          # "databricks" or "fabric"
    host: str = ""                     # Databricks workspace URL
    tenant: str = ""                   # Fabric tenant
    auth_method: str = "token"         # token, az_cli, device_code


@dataclass
class EnvironmentConfig:
    """Configuration for a single environment."""
    name: str                          # "dev", "cert", "prod"
    description: str = ""
    # Databricks
    db_workspace_path: str = ""
    db_catalog: str = ""
    db_schema: str = ""
    # Fabric / Power BI
    fabric_workspace_id: str = ""
    fabric_workspace_name: str = ""
    pbi_model_name: str = ""
    pbi_model_id: str = ""
    pbi_report_workspace_id: str = ""
    pbi_report_suffix: str = ""
    pbi_auth_method: str = "az_cli"
    pbi_tables_excluded: list[str] = field(default_factory=list)


@dataclass
class ProjectSetup:
    """All information needed to scaffold a project."""
    client: str
    project: str
    description: str = ""
    # Where to create the project
    target_dir: str = ""               # If empty, defaults to projects/{client}/{project}
    # Platforms
    platforms: list[PlatformConfig] = field(default_factory=list)
    # Environments
    environments: list[EnvironmentConfig] = field(default_factory=list)
    # Scopes
    scopes: dict[str, str] = field(default_factory=dict)  # scope_name -> connector_name
    # Work mode
    work_mode: str = "solo"            # "solo" or "team"
    base_catalog: str = ""             # The catalog used in src/ (for overlay remap)
    patch_max_age_days: int = 7


def scaffold_project(setup: ProjectSetup, repo_root: Path | None = None) -> Path:
    """Create a new project from template with populated config.

    Args:
        setup: Collected project configuration.
        repo_root: Root of the ade-ops repository. If None, uses template parent.

    Returns:
        Path to the created project directory.
    """
    if repo_root is None:
        repo_root = TEMPLATE_DIR.parent.parent.parent

    # Determine target directory
    if setup.target_dir:
        project_dir = Path(setup.target_dir).resolve()
    else:
        project_dir = repo_root / "projects" / setup.client / setup.project

    if project_dir.exists():
        raise FileExistsError(f"Project directory already exists: {project_dir}")

    # Copy template structure
    shutil.copytree(TEMPLATE_DIR, project_dir)

    # Generate config files
    _write_project_yaml(project_dir, setup)
    _write_credentials_yaml(project_dir, setup)
    _write_overlays(project_dir, setup)
    _write_gitignore(project_dir)

    return project_dir


def _write_project_yaml(project_dir: Path, setup: ProjectSetup) -> None:
    """Generate project.yaml from setup data."""
    config: dict = {
        "project": {
            "name": setup.project,
            "client": setup.client,
            "description": setup.description,
        },
    }

    # Platforms
    platforms = {}
    for p in setup.platforms:
        if p.name == "databricks":
            platforms["databricks"] = {"host": p.host}
        elif p.name == "fabric":
            platforms["fabric"] = {"tenant": p.tenant}
    if platforms:
        config["platforms"] = platforms

    # Environments
    envs = {}
    for env in setup.environments:
        env_cfg: dict = {
            "description": env.description,
            "overlay": f"overlays/{env.name}.yaml",
            "platforms": {},
        }
        if env.db_workspace_path:
            env_cfg["platforms"]["databricks"] = {
                "workspace_path": env.db_workspace_path,
                "catalog": env.db_catalog,
                "schema": env.db_schema,
            }
        if env.fabric_workspace_id:
            env_cfg["platforms"]["fabric"] = {
                "workspace_id": env.fabric_workspace_id,
                "workspace_name": env.fabric_workspace_name,
            }
        envs[env.name] = env_cfg
    if envs:
        config["environments"] = envs

    # Scopes
    if setup.scopes:
        scopes = {}
        for scope_name, connector in setup.scopes.items():
            scopes[scope_name] = {
                "path": f"src/{scope_name}",
                "connector": connector,
            }
        config["scopes"] = scopes

    config["patch_max_age_days"] = setup.patch_max_age_days

    path = project_dir / "config" / "project.yaml"
    path.write_text(
        f"# ade-ops project configuration — {setup.client}/{setup.project}\n"
        + yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _write_credentials_yaml(project_dir: Path, setup: ProjectSetup) -> None:
    """Generate credentials.example.yaml template (committable).

    The real credentials.yaml is gitignored and must be created by the user
    by copying this example and filling in real values.
    """
    lines = [
        "# Template — copy this file to credentials.yaml and fill in your values.",
        "# credentials.yaml is gitignored. Never commit it.",
        "",
    ]

    for p in setup.platforms:
        if p.name == "databricks":
            lines.extend([
                "databricks:",
                f"  host: \"{p.host}\"",
                "  token: \"${DATABRICKS_TOKEN}\"   # env var reference (recommended)",
                "",
            ])
        elif p.name == "fabric":
            lines.extend([
                "fabric:",
                f"  tenant_id: \"{p.tenant}\"",
                f"  auth_method: {p.auth_method}",
                "",
            ])

    path = project_dir / "config" / "credentials.example.yaml"
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_overlays(project_dir: Path, setup: ProjectSetup) -> None:
    """Generate overlay files for each environment."""
    overlays_dir = project_dir / "overlays"

    # Remove template overlays
    for f in overlays_dir.glob("*.yaml"):
        f.unlink()

    for env in setup.environments:
        overlay: dict = {}

        # Databricks section
        if env.db_catalog:
            db_section: dict = {
                "catalog": env.db_catalog,
                "schema": env.db_schema,
                "workspace_path": env.db_workspace_path,
            }
            overlay["databricks"] = db_section

        # Power BI section
        if env.pbi_model_name:
            pbi_section: dict = {
                "model_workspace_id": env.fabric_workspace_id,
                "model_name": env.pbi_model_name,
                "model_id": env.pbi_model_id,
                "report_workspace_id": env.pbi_report_workspace_id or env.fabric_workspace_id,
                "report_suffix": env.pbi_report_suffix,
                "auth_method": env.pbi_auth_method,
                "tables_excluded": env.pbi_tables_excluded,
                "column_exclusions": {},
                "item_renames": {},
            }
            overlay["power_bi"] = pbi_section

        # Base catalog for overlay remap
        if setup.base_catalog:
            overlay["_base_catalog"] = setup.base_catalog

        path = overlays_dir / f"{env.name}.yaml"
        path.write_text(
            f"# Overlay — {env.name.upper()} environment\n"
            f"# Applied during push to transform src/ assets for {env.name} target\n\n"
            + yaml.dump(overlay, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    # Create state directories for each environment
    for env in setup.environments:
        for scope in setup.scopes:
            state_dir = project_dir / "state" / env.name / scope
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / ".gitkeep").touch()


def _write_gitignore(project_dir: Path) -> None:
    """Generate .gitignore for the project repo."""
    content = """\
# Credentials — NEVER commit
config/credentials.yaml
.env
.env.*

# Working data
_data/

# Local workspace (personal, not shared)
local/

# Python
__pycache__/
*.pyc
*.pyo
.venv/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
"""
    (project_dir / ".gitignore").write_text(content, encoding="utf-8")
