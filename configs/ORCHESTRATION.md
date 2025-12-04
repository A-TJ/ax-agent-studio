# Turnkey Orchestration Layer

The aX Agent Studio provides a comprehensive orchestration layer that makes it easy to deploy and manage multi-agent teams with pre-built patterns, shared configurations, and opinionated best practices.

## Overview

The orchestration layer consists of four key components:

1. **Task Delegation Patterns** - How agents route work to each other
2. **Collaboration Patterns** - What workflows agents follow
3. **Shared MCP Server Configuration** - Reusable tool configurations
4. **Execution Presets** - Where and how agents run

## Quick Start

### 1. Basic Deployment Group

The simplest way to deploy a team:

```yaml
# configs/deployment_groups.yaml
deployment_groups:
  my_team:
    name: "My Team"
    description: "Simple 3-agent team"
    agents:
      - id: "agent_1"
        model: "claude-sonnet-4-5"
      - id: "agent_2"
        model: "claude-sonnet-4-5"
      - id: "agent_3"
        model: "claude-sonnet-4-5"
```

### 2. Orchestrated Deployment Group

Enhanced with orchestration patterns:

```yaml
deployment_groups:
  my_orchestrated_team:
    name: "My Orchestrated Team"
    description: "Team with structured workflow"

    # Orchestration features
    delegation_pattern: "waterfall"
    collaboration_pattern: "code_review_workflow"
    mcp_servers: ["standard_dev"]
    execution_preset: "local_development"

    agents:
      - id: "developer_agent"
        role: "developer"
        model: "claude-sonnet-4-5"
      - id: "reviewer_agent"
        role: "reviewer"
        model: "claude-sonnet-4-5"
```

## Delegation Patterns

**File:** `configs/delegation_patterns.yaml`

Delegation patterns define **how** tasks are routed between agents.

### Available Patterns

| Pattern | Description | Best For |
|---------|-------------|----------|
| `round_robin` | Even distribution across agents | Load balancing, parallel tasks |
| `waterfall` | Sequential handoff through stages | Traditional project workflows |
| `priority_routing` | Route by urgency/complexity | Support tickets, triage |
| `specialist_routing` | Route by expertise/skills | Technical teams with specializations |
| `scrum` | Sprint-based agile workflow | Product development teams |
| `escalation_ladder` | Tiered support hierarchy | Customer service |

### Example Usage

```yaml
deployment_groups:
  support_team:
    delegation_pattern: "escalation_ladder"
    agents:
      - id: "triage_agent"
      - id: "l1_support_agent"
      - id: "l2_support_agent"
```

**What this does:**
- Triage agent receives all incoming requests
- Routes simple issues to L1, complex issues to L2
- L2 can escalate critical issues to engineering

## Collaboration Patterns

**File:** `configs/collaboration_patterns.yaml`

Collaboration patterns define **what** workflows agents follow.

### Available Patterns

| Pattern | Description | Best For |
|---------|-------------|----------|
| `code_review_workflow` | Developer → Reviewer → Approver | Software development |
| `support_escalation_workflow` | Triage → L1 → L2 → Engineering | Customer support |
| `content_creation_pipeline` | Writer → Editor → Publisher | Content marketing |
| `data_analysis_workflow` | Analyst → Validator → Reporter | Data science |

### Example Usage

```yaml
deployment_groups:
  dev_team:
    collaboration_pattern: "code_review_workflow"
    agents:
      - id: "developer_agent"
        role: "developer"  # Maps to pattern role
      - id: "reviewer_agent"
        role: "reviewer"
      - id: "approver_agent"
        role: "approver"
```

**What this does:**
- Developer implements features
- Reviewer checks code quality
- Approver gives final approval and merges
- System prompts are automatically configured for each role

## Shared MCP Server Configuration

**File:** `configs/mcp_servers.yaml`

Define MCP servers once, use everywhere.

### Available Server Groups

| Group | Servers | Best For |
|-------|---------|----------|
| `common` | aX platform connection | All agents (required) |
| `github` | GitHub integration | Code-related agents |
| `filesystem` | Local file access | Development agents |
| `database_postgres` | PostgreSQL access | Data agents |
| `web_tools` | HTTP fetch, browser automation | Scraping/research agents |
| `cloud_gcp` | GCP services | Cloud deployment |
| `docker` | Container management | DevOps agents |

### Predefined Groups

```yaml
server_groups:
  standard_dev:  # Common + GitHub + Filesystem
  fullstack_dev: # Full development stack
  devops:        # Cloud + Docker + Communication
  support:       # Communication + Database
```

### Example Usage

```yaml
deployment_groups:
  dev_team:
    mcp_servers: ["standard_dev"]  # All agents get GitHub + Filesystem
    agents:
      - id: "developer_1"
      - id: "developer_2"
```

**Benefits:**
- **DRY**: Define servers once, use everywhere
- **Consistency**: All agents use same configs
- **Easy updates**: Change server URL in one place
- **Environment-aware**: Different configs for local/production

## Execution Presets

**File:** `configs/execution_presets.yaml`

Define where and how agents run.

### Available Presets

| Preset | Environment | Cost | Best For |
|--------|-------------|------|----------|
| `local_development` | Your machine | Free | Testing, debugging |
| `docker_local` | Docker containers | Free | Better isolation |
| `gcp_cloud_run` | GCP serverless | $0.00002/req | Auto-scaling production |
| `gcp_compute_engine` | GCP VMs | $50-150/mo | High-throughput workloads |
| `aws_lambda` | AWS serverless | $0.0000166/GB-s | AWS-native deployments |
| `aws_ecs_fargate` | AWS containers | $30-100/mo/task | Long-running agents |
| `hybrid_dev_prod` | Mix local + cloud | Varies | Cost-optimized development |

### Example Usage

```yaml
deployment_groups:
  dev_team:
    execution_preset: "local_development"  # Run locally for testing

  prod_team:
    execution_preset: "gcp_cloud_run"  # Run in cloud for production
```

**What this does:**
- Configures MCP server URLs (local vs production)
- Sets resource limits (memory, CPU)
- Configures network and security settings
- Sets environment variables

## Complete Example

Here's a fully orchestrated code review team:

```yaml
# configs/deployment_groups.yaml
deployment_groups:
  code_review_team_prod:
    name: "Code Review Team (Production)"
    description: "Production code review workflow with full orchestration"

    # How tasks flow between agents
    delegation_pattern: "waterfall"

    # What workflow agents follow
    collaboration_pattern: "code_review_workflow"

    # Shared tools (GitHub, filesystem access)
    mcp_servers: ["standard_dev"]

    # Run in GCP Cloud Run
    execution_preset: "gcp_cloud_run"

    defaults:
      monitor: "claude_agent_sdk"
      start_delay_ms: 500

    agents:
      - id: "developer_agent"
        role: "developer"
        model: "claude-sonnet-4-5"

      - id: "reviewer_agent"
        role: "reviewer"
        model: "claude-sonnet-4-5"

      - id: "approver_agent"
        role: "approver"
        model: "claude-haiku-4-5"

    tags: ["production", "code-review", "orchestrated"]
    environment: "production"
```

## How It Works

When you deploy this group:

1. **Delegation Pattern** (`waterfall`):
   - Developer completes work → passes to Reviewer
   - Reviewer approves → passes to Approver
   - Approver merges to main branch

2. **Collaboration Pattern** (`code_review_workflow`):
   - Developer: System prompt configured for implementation
   - Reviewer: System prompt configured for code review
   - Approver: System prompt configured for final approval

3. **MCP Servers** (`standard_dev`):
   - All agents get: aX platform + GitHub + Filesystem access
   - Same server configs across all agents

4. **Execution Preset** (`gcp_cloud_run`):
   - Agents run in GCP Cloud Run
   - Auto-scale based on demand
   - Production MCP server URLs

## Mixing Patterns

You can combine any delegation pattern with any collaboration pattern:

```yaml
# Support team with priority routing
support_team:
  delegation_pattern: "priority_routing"  # Route by urgency
  collaboration_pattern: "support_escalation_workflow"  # Tiered support

# Sprint team with scrum ceremonies
sprint_team:
  delegation_pattern: "scrum"  # Sprint-based
  collaboration_pattern: "code_review_workflow"  # Code quality gates
```

## Creating Custom Patterns

### 1. Custom Delegation Pattern

Add to `configs/delegation_patterns.yaml`:

```yaml
delegation_patterns:
  my_custom_pattern:
    name: "My Custom Pattern"
    description: "How my team routes tasks"
    routing_strategy: "custom"

    roles:
      coordinator:
        can_delegate_to: ["worker_a", "worker_b"]
      worker_a:
        receives_from: ["coordinator"]
      worker_b:
        receives_from: ["coordinator"]
```

### 2. Custom Collaboration Pattern

Add to `configs/collaboration_patterns.yaml`:

```yaml
collaboration_patterns:
  my_workflow:
    name: "My Workflow"
    description: "My team's specific workflow"

    roles:
      role_a:
        responsibilities: ["Task 1", "Task 2"]
        system_prompt_template: "You are role A..."
      role_b:
        responsibilities: ["Task 3", "Task 4"]
        system_prompt_template: "You are role B..."
```

### 3. Custom MCP Server Group

Add to `configs/mcp_servers.yaml`:

```yaml
server_groups:
  my_tools:
    name: "My Custom Tools"
    includes: ["common", "github", "my_custom_server"]
```

### 4. Custom Execution Preset

Add to `configs/execution_presets.yaml`:

```yaml
execution_presets:
  my_environment:
    name: "My Environment"
    environment: "custom"
    mcp_config:
      default_base_url: "https://my-mcp-server.com"
    resources:
      memory: "2Gi"
      cpu: "1.0"
```

## Best Practices

### 1. Start Simple, Add Orchestration

```yaml
# Start with basic deployment
my_team:
  agents: [...]

# Add orchestration incrementally
my_team:
  delegation_pattern: "round_robin"  # Add task routing
  mcp_servers: ["standard_dev"]  # Add shared tools
  execution_preset: "local_development"  # Add environment config
```

### 2. Use Predefined Patterns First

Before creating custom patterns, check if existing patterns fit your needs:
- **Delegation**: 6 patterns covering most routing scenarios
- **Collaboration**: 4 patterns covering common workflows
- **MCP Servers**: 10+ predefined server groups
- **Execution**: 7 presets from local to cloud

### 3. Environment-Specific Configurations

```yaml
# Development environment
dev_team:
  execution_preset: "local_development"
  mcp_servers: ["common_local", "docker"]

# Production environment
prod_team:
  execution_preset: "gcp_cloud_run"
  mcp_servers: ["common", "cloud_gcp"]
```

### 4. Cost Optimization

```yaml
# Use lite models for triage/routing
support_team:
  agents:
    - id: "triage"
      model: "claude-haiku-4-5"  # Fast, cheap
    - id: "specialist"
      model: "claude-sonnet-4-5"  # Powerful, expensive
```

## Troubleshooting

### Pattern not found

**Error:** `Pattern 'waterfall' not found`

**Solution:** Check pattern name spelling in:
- `configs/delegation_patterns.yaml`
- `configs/collaboration_patterns.yaml`

### Agent role mismatch

**Error:** `Role 'developer' not defined in collaboration pattern`

**Solution:** Ensure agent roles match collaboration pattern roles:

```yaml
collaboration_pattern: "code_review_workflow"
agents:
  - id: "dev_agent"
    role: "developer"  # Must match pattern role
```

### MCP server not loading

**Error:** `Server group 'standard_dev' not found`

**Solution:** Check server group definition in `configs/mcp_servers.yaml`

## Examples by Use Case

### Software Development

```yaml
dev_team:
  delegation_pattern: "waterfall"
  collaboration_pattern: "code_review_workflow"
  mcp_servers: ["fullstack_dev"]
  execution_preset: "local_development"
```

### Customer Support

```yaml
support_team:
  delegation_pattern: "escalation_ladder"
  collaboration_pattern: "support_escalation_workflow"
  mcp_servers: ["support"]
  execution_preset: "gcp_cloud_run"
```

### Content Production

```yaml
content_team:
  delegation_pattern: "waterfall"
  collaboration_pattern: "content_creation_pipeline"
  mcp_servers: ["web_tools", "communication"]
  execution_preset: "aws_lambda"
```

### Data Analysis

```yaml
analytics_team:
  delegation_pattern: "specialist_routing"
  collaboration_pattern: "data_analysis_workflow"
  mcp_servers: ["data_analyst"]
  execution_preset: "gcp_compute_engine"
```

## Learn More

- **Delegation Patterns**: See `configs/delegation_patterns.yaml` for all patterns and usage examples
- **Collaboration Patterns**: See `configs/collaboration_patterns.yaml` for workflow templates
- **MCP Servers**: See `configs/mcp_servers.yaml` for server configurations
- **Execution Presets**: See `configs/execution_presets.yaml` for environment configs
- **Examples**: See `configs/deployment_groups.example.yaml` for more deployment examples

## Summary

The orchestration layer provides:

✅ **Pre-built "agent team" templates** - 3+ ready-to-use deployment groups
✅ **Task delegation patterns** - 6 routing strategies (round-robin, waterfall, priority, etc.)
✅ **Shared MCP server configuration** - 10+ reusable server configs and groups
✅ **Opinionated defaults for collaboration patterns** - 4 workflow patterns (code review, support, content, data)
✅ **Optional cloud agent execution presets** - 7 execution environments (local, Docker, GCP, AWS, hybrid)

This makes it trivial to deploy sophisticated multi-agent teams with enterprise-grade orchestration patterns!
