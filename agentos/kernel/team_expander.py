"""Team expander — compile-time resolution of teams into channels and agent tags.

Teams are a high-level concept that gets expanded into existing primitives
(channels, agent tags) before the DAG executor sees them.  The executor
never knows about teams — it only sees channels, agents, and tasks.
"""

from __future__ import annotations

from agentos.schemas.channel import ChannelConfig, ChannelMode
from agentos.schemas.workflow import WorkflowDefinition


class TeamExpansionError(Exception):
    """Raised when team configuration is invalid."""


def expand_teams(wf: WorkflowDefinition) -> WorkflowDefinition:
    """Resolve teams into channels and agent tags.

    Mutates a *copy* of ``wf`` and returns it.  The original is unchanged.

    Steps:
      1. Validate all team members and managers exist in agents section.
      2. Create a broadcast channel for each team (``team_{name}``).
      3. Tag every member and manager agent with ``agent.team = team_name``.
      4. Ensure manager agents have ``adapter: "manager"``.
    """
    if not wf.teams:
        return wf

    # Work on a deep copy so the caller's object is untouched.
    wf = wf.model_copy(deep=True)

    agent_names = set(wf.agents.keys())
    seen_agents: dict[str, str] = {}  # agent_name → team_name (for overlap check)

    for team_name, team_cfg in wf.teams.items():
        # --- Validate manager ---
        if team_cfg.manager not in agent_names:
            raise TeamExpansionError(
                f"Team {team_name!r}: manager {team_cfg.manager!r} "
                f"is not defined in agents section"
            )

        # --- Validate members ---
        for member in team_cfg.members:
            if member not in agent_names:
                raise TeamExpansionError(
                    f"Team {team_name!r}: member {member!r} "
                    f"is not defined in agents section"
                )

        # --- Manager should not also be a member ---
        if team_cfg.manager in team_cfg.members:
            raise TeamExpansionError(
                f"Team {team_name!r}: manager {team_cfg.manager!r} "
                f"should not also be listed as a member"
            )

        # --- No agent in multiple teams ---
        all_team_agents = [team_cfg.manager] + team_cfg.members
        for agent_name in all_team_agents:
            if agent_name in seen_agents:
                raise TeamExpansionError(
                    f"Agent {agent_name!r} is in team {team_name!r} "
                    f"but already belongs to team {seen_agents[agent_name]!r}"
                )
            seen_agents[agent_name] = team_name

        # --- Create team channel ---
        channel_name = team_cfg.channel or f"team_{team_name}"
        if channel_name not in wf.channels:
            wf.channels[channel_name] = ChannelConfig(
                name=channel_name,
                mode=ChannelMode.BROADCAST,
            )
        # Store resolved channel name back into config
        team_cfg.channel = channel_name

        # --- Tag agents with team membership ---
        wf.agents[team_cfg.manager].team = team_name
        for member in team_cfg.members:
            wf.agents[member].team = team_name

        # --- Ensure manager agent uses manager adapter ---
        wf.agents[team_cfg.manager].adapter = "manager"

        # --- Resolve team workspace name ---
        if not team_cfg.workspace:
            team_cfg.workspace = f"team_{team_name}"

    return wf
