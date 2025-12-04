"""
Deployment Group Loader

Loads deployment group definitions from configs/deployment_groups.yaml.
Provides helper functions to retrieve group metadata for the dashboard
and process manager.
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import field
from pathlib import Path
from typing import Any

import yaml

from ax_agent_studio.dashboard.backend.config_loader import ConfigLoader


@dataclasses.dataclass
class DeploymentAgent:
    """Agent entry inside a deployment group."""

    id: str
    role: str | None = None
    monitor: str | None = None
    provider: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    start_delay_ms: int | None = None
    process_backlog: bool | None = (
        None  # DEPRECATED: Kept for backward compatibility, defaults to False
    )


@dataclasses.dataclass
class DeploymentGroup:
    """Deployment group definition."""

    id: str
    name: str
    description: str
    defaults: dict[str, Any]
    agents: list[DeploymentAgent]
    tags: list[str]
    environment: str = "any"
    delegation_pattern: str | None = None
    collaboration_pattern: str | None = None
    mcp_servers: list[str] = field(default_factory=list)
    execution_preset: str | None = None
    delegation_pattern_details: dict[str, Any] | None = None
    collaboration_pattern_details: dict[str, Any] | None = None
    mcp_server_details: list[dict[str, Any]] = field(default_factory=list)
    execution_preset_details: dict[str, Any] | None = None


class DeploymentLoader:
    """Loads deployment group configuration."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.config_path = self.base_dir / "configs" / "deployment_groups.yaml"
        self._groups: dict[str, DeploymentGroup] = {}
        self._config_loader = ConfigLoader(base_dir)
        self._delegation_patterns: dict[str, Any] = {}
        self._collaboration_patterns: dict[str, Any] = {}
        self._mcp_servers: dict[str, Any] = {}
        self._mcp_server_groups: dict[str, Any] = {}
        self._execution_presets: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        """Reload deployment groups from disk."""
        self._groups = {}
        self._load_orchestration_configs()

        if not self.config_path.exists():
            return

        try:
            with open(self.config_path) as f:
                raw_config = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error loading deployment groups: {e}")
            return

        groups_data = raw_config.get("deployment_groups", {})
        if not isinstance(groups_data, dict):
            print("deployment_groups.yaml: 'deployment_groups' must be a mapping")
            return

        existing_agents: set[str] = {
            entry["agent_name"] for entry in self._config_loader.list_configs()
        }

        for group_id, group_info in groups_data.items():
            try:
                group = self._parse_group(group_id, group_info, existing_agents)
                if group:  # Only add if group was successfully parsed
                    self._groups[group_id] = group
            except Exception as e:
                print(f"  Skipping deployment group '{group_id}': {e}")

    def _load_orchestration_configs(self) -> None:
        """Load auxiliary orchestration configuration files."""
        self._delegation_patterns = self._load_yaml_section(
            "configs/delegation_patterns.yaml", "delegation_patterns"
        )
        self._collaboration_patterns = self._load_yaml_section(
            "configs/collaboration_patterns.yaml", "collaboration_patterns"
        )

        mcp_data = self._load_yaml_file("configs/mcp_servers.yaml")
        mcp_servers = mcp_data.get("mcp_servers", {})
        server_groups = mcp_data.get("server_groups", {})

        self._mcp_servers = mcp_servers if isinstance(mcp_servers, dict) else {}
        self._mcp_server_groups = server_groups if isinstance(server_groups, dict) else {}

        self._execution_presets = self._load_yaml_section(
            "configs/execution_presets.yaml", "execution_presets"
        )

    def _load_yaml_file(self, relative_path: str) -> dict[str, Any]:
        """Load a YAML file relative to the project root."""
        path = self.base_dir / relative_path
        if not path.exists():
            return {}

        try:
            with open(path, encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
                if isinstance(data, dict):
                    return data
                print(f"  ⚠  {relative_path} root node must be a mapping")
        except Exception as exc:
            print(f"  ⚠  Failed to load {relative_path}: {exc}")
        return {}

    def _load_yaml_section(self, relative_path: str, section_key: str) -> dict[str, Any]:
        """Load a specific mapping section from a YAML file."""
        data = self._load_yaml_file(relative_path)
        section = data.get(section_key, {})
        if isinstance(section, dict):
            return section
        if section:
            print(f"  ⚠  {relative_path}: '{section_key}' must be a mapping")
        return {}

    def _parse_group(
        self,
        group_id: str,
        group_info: dict[str, Any],
        existing_agents: set[str],
    ) -> DeploymentGroup:
        """Parse a single group entry."""
        if not isinstance(group_info, dict):
            raise ValueError("Group definition must be a mapping")

        name = group_info.get("name", group_id.replace("_", " ").title())
        description = group_info.get("description", "")
        defaults = group_info.get("defaults", {}) or {}
        tags = group_info.get("tags", []) or []
        environment = group_info.get("environment", "any") or "any"

        delegation_pattern = self._normalize_string(group_info.get("delegation_pattern"))
        collaboration_pattern = self._normalize_string(group_info.get("collaboration_pattern"))
        execution_preset = self._normalize_string(group_info.get("execution_preset"))
        mcp_servers = self._normalize_list(group_info.get("mcp_servers"))

        delegation_pattern_details = self._get_mapping_entry(
            self._delegation_patterns, delegation_pattern, "Delegation pattern"
        )
        collaboration_pattern_details = self._get_mapping_entry(
            self._collaboration_patterns, collaboration_pattern, "Collaboration pattern"
        )
        execution_preset_details = self._get_mapping_entry(
            self._execution_presets, execution_preset, "Execution preset"
        )
        mcp_server_details = self._resolve_mcp_servers(mcp_servers)

        if "agents" not in group_info or not isinstance(group_info["agents"], list):
            raise ValueError("Group must define an 'agents' list")

        agents: list[DeploymentAgent] = []
        skipped_agents: list[str] = []

        for raw_agent in group_info["agents"]:
            try:
                if isinstance(raw_agent, str):
                    agent_id = raw_agent
                    agent_data: dict[str, Any] = {}
                elif isinstance(raw_agent, dict):
                    if "id" not in raw_agent:
                        print(f"    Skipping agent entry without 'id' in group '{group_id}'")
                        continue
                    agent_id = raw_agent["id"]
                    agent_data = {k: v for k, v in raw_agent.items() if k != "id"}
                else:
                    print(f"    Skipping invalid agent entry in group '{group_id}'")
                    continue

                # Validate agent exists, but don't fail - just skip
                if not self._agent_exists(agent_id, existing_agents):
                    if agent_id.startswith("YOUR_") or "EXAMPLE" in agent_id.upper():
                        print(
                            f"   Placeholder agent '{agent_id}' - replace with your actual agent ID"
                        )
                    else:
                        print(f"    Agent '{agent_id}' not found in configs/agents/ - skipping")
                        print(f"     Available agents: {', '.join(sorted(existing_agents))}")
                    skipped_agents.append(agent_id)
                    continue

                agents.append(
                    DeploymentAgent(
                        id=agent_id,
                        role=agent_data.get("role"),
                        monitor=agent_data.get("monitor"),
                        provider=agent_data.get("provider"),
                        model=agent_data.get("model"),
                        system_prompt=agent_data.get("system_prompt"),
                        start_delay_ms=agent_data.get("start_delay_ms"),
                        process_backlog=agent_data.get("process_backlog"),
                    )
                )
            except Exception as e:
                print(f"    Error processing agent in group '{group_id}': {e}")
                continue

        if skipped_agents:
            has_placeholders = any(
                a.startswith("YOUR_") or "EXAMPLE" in a.upper() for a in skipped_agents
            )
            if has_placeholders:
                print(
                    f"   Group '{group_id}': Update placeholder agent names in deployment_groups.yaml"
                )
            else:
                print(
                    f"   Group '{group_id}': {len(agents)} agents loaded, {len(skipped_agents)} skipped"
                )

        if not agents:
            print(
                f"  ℹ  Group '{group_id}' has no valid agents - check agent IDs in deployment_groups.yaml"
            )
            print(f"     Available agents: {', '.join(sorted(existing_agents))}")
            return None  # Return None instead of raising error

        return DeploymentGroup(
            id=group_id,
            name=name,
            description=description,
            defaults=defaults,
            agents=agents,
            tags=tags,
            environment=environment,
            delegation_pattern=delegation_pattern,
            collaboration_pattern=collaboration_pattern,
            mcp_servers=mcp_servers,
            execution_preset=execution_preset,
            delegation_pattern_details=delegation_pattern_details,
            collaboration_pattern_details=collaboration_pattern_details,
            mcp_server_details=mcp_server_details,
            execution_preset_details=execution_preset_details,
        )

    def _normalize_string(self, value: Any) -> str | None:
        """Return a trimmed string or None."""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return None

    def _normalize_list(self, value: Any) -> list[str]:
        """Normalize a string/list value to a list of strings."""
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        if isinstance(value, list):
            normalized: list[str] = []
            for item in value:
                if isinstance(item, str):
                    stripped = item.strip()
                    if stripped:
                        normalized.append(stripped)
            return normalized
        return []

    def _get_mapping_entry(
        self,
        mapping: dict[str, Any],
        key: str | None,
        label: str,
    ) -> dict[str, Any] | None:
        """Fetch a mapping entry and provide a deep-copied payload with the id."""
        if not key:
            return None

        entry = mapping.get(key)
        if not isinstance(entry, dict):
            print(f"  ⚠  {label} '{key}' not found in configuration")
            return None

        result = copy.deepcopy(entry)
        result["id"] = key
        return result

    def _resolve_mcp_servers(self, references: list[str]) -> list[dict[str, Any]]:
        """Resolve MCP server group references with metadata."""
        resolved: list[dict[str, Any]] = []
        for ref in references:
            entry: Any = self._mcp_server_groups.get(ref) or self._mcp_servers.get(ref)
            if not isinstance(entry, dict):
                print(f"  ⚠  MCP server group '{ref}' not found")
                continue

            result = copy.deepcopy(entry)
            result["id"] = ref
            resolved.append(result)
        return resolved

    def _agent_exists(self, agent_id: str, existing_agents: set[str] | None = None) -> bool:
        """Check if agent configuration file exists (non-throwing)."""
        if existing_agents is None:
            existing_agents = {entry["agent_name"] for entry in self._config_loader.list_configs()}
        return agent_id in existing_agents

    def list_groups(self, environment: str | None = None) -> list[DeploymentGroup]:
        """List deployment groups, optionally filtered by environment."""
        groups = list(self._groups.values())
        if environment and environment != "any":
            return [g for g in groups if g.environment in ("any", environment)]
        return groups

    def get_group(self, group_id: str) -> DeploymentGroup | None:
        """Return a group by id."""
        return self._groups.get(group_id)


# Helper accessor used by other modules
_deployment_loader: DeploymentLoader | None = None


def get_deployment_loader(base_dir: Path | None = None) -> DeploymentLoader:
    """Get (and cache) the deployment loader instance."""
    global _deployment_loader
    if _deployment_loader is None:
        if base_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent
        _deployment_loader = DeploymentLoader(base_dir)
    return _deployment_loader
