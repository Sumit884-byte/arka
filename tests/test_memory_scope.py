"""Tests for scoped memory, provenance, and trust tiers."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.core.memory_scope import (
    MemoryPolicy,
    Provenance,
    RecallScope,
    entry_matches_scope,
    filter_fact_rows,
    list_scratchpad,
    promote_to_facts,
    recall_scratchpad,
    resolve_memory_policy,
    write_scratchpad,
)
from arka.teams.executor import execute_workflow
from arka.teams.schema import Team, TeamMember, Workflow, WorkflowStep


class ScratchpadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scratch_file = Path(self.tmp.name) / "index.jsonl"
        self.scratch_file.parent.mkdir(parents=True, exist_ok=True)
        os.environ["MEMORY_SCRATCHPAD_TTL_HOURS"] = "72"
        os.environ.pop("ARKA_MEMORY_TRUST_MAX", None)
        os.environ.pop("ARKA_HUB_MEMORY_SCOPE", None)
        self._scratch_patch = mock.patch(
            "arka.core.memory_scope.scratchpad_path",
            return_value=self.scratch_file,
        )
        self._scratch_patch.start()
        self.addCleanup(self._scratch_patch.stop)

    def tearDown(self) -> None:
        os.environ.pop("ARKA_MEMORY_TRUST_MAX", None)

    def test_write_and_list_scratchpad(self) -> None:
        prov = Provenance(team="research", workflow="review", role="lead", trust_tier="workflow")
        entry_id = write_scratchpad("Step output text", provenance=prov)
        self.assertTrue(entry_id)
        rows = list_scratchpad(team="research")
        self.assertEqual(len(rows), 1)
        self.assertIn("Step output", rows[0]["text"])

    def test_team_isolation_in_recall(self) -> None:
        write_scratchpad(
            "Team A secret",
            provenance=Provenance(team="team-a", workflow="wf", trust_tier="workflow"),
        )
        write_scratchpad(
            "Team B note",
            provenance=Provenance(team="team-b", workflow="wf", trust_tier="workflow"),
        )
        scope = RecallScope(
            team="team-a",
            workflow="wf",
            policy=MemoryPolicy(read_tiers=["global", "team", "workflow"]),
        )
        ctx = recall_scratchpad("secret", scope=scope, limit_chars=2000)
        self.assertIn("Team A", ctx)
        self.assertNotIn("Team B", ctx)

    def test_trust_max_excludes_workflow(self) -> None:
        os.environ["ARKA_MEMORY_TRUST_MAX"] = "team"
        write_scratchpad(
            "Workflow only",
            provenance=Provenance(team="research", workflow="wf", trust_tier="workflow"),
        )
        scope = RecallScope(
            team="research",
            workflow="wf",
            policy=MemoryPolicy(read_tiers=["global", "team", "workflow"]),
        )
        ctx = recall_scratchpad("Workflow", scope=scope)
        self.assertEqual(ctx, "")

    def test_promote_to_facts(self) -> None:
        memory_file = Path(self.tmp.name) / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        entry_id = write_scratchpad(
            "Promotable fact",
            provenance=Provenance(team="research", trust_tier="workflow"),
        )
        with mock.patch("arka.agent.core.MEMORY_FILE", memory_file):
            ok, err = promote_to_facts(entry_id)
        self.assertTrue(ok, err)
        raw = json.loads(memory_file.read_text(encoding="utf-8"))
        self.assertEqual(raw[-1]["trust_tier"], "global")
        self.assertEqual(raw[-1]["text"], "Promotable fact")


class FilterFactsTests(unittest.TestCase):
    def test_legacy_facts_treated_as_global(self) -> None:
        rows = [{"text": "old fact", "tags": []}]
        scope = RecallScope(team="research", policy=MemoryPolicy())
        kept = filter_fact_rows(rows, scope=scope)
        self.assertEqual(len(kept), 1)

    def test_team_scoped_fact_filtered(self) -> None:
        rows = [
            {
                "text": "team secret",
                "trust_tier": "team",
                "provenance": {"team": "other", "trust_tier": "team"},
            }
        ]
        scope = RecallScope(team="research", policy=MemoryPolicy(read_tiers=["team"]))
        kept = filter_fact_rows(rows, scope=scope)
        self.assertEqual(len(kept), 0)


class PolicyResolutionTests(unittest.TestCase):
    def test_workflow_overrides_team(self) -> None:
        policy = resolve_memory_policy(
            {"memory_scope": {"read": ["global"], "write": "team"}},
            {"memory_scope": {"read": ["global", "workflow"], "write": "workflow"}},
        )
        self.assertIn("workflow", policy.read_tiers)
        self.assertEqual(policy.write_tier, "workflow")


class ExecutorMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scratch_file = Path(self.tmp.name) / "index.jsonl"
        self._scratch_patch = mock.patch(
            "arka.core.memory_scope.scratchpad_path",
            return_value=self.scratch_file,
        )
        self._scratch_patch.start()
        self.addCleanup(self._scratch_patch.stop)

    def test_scoped_run_writes_scratchpad(self) -> None:
        team = Team(
            name="test-team",
            members=[TeamMember(kind="model", id="gpt-4o", role="lead", provider="openai")],
            defaults={"memory": "scoped", "memory_scope": {"write": "workflow"}},
        )
        workflow = Workflow(
            name="test-wf",
            team="test-team",
            steps=[WorkflowStep(member="lead", action="plan", prompt="Plan: {task}")],
        )

        def fake_runner(member, prompt, system):
            from arka.teams.executor import StepResult

            return StepResult(
                role=member.role,
                action="plan",
                member_kind=member.member_kind,
                member_id=member.member_id,
                output="Planned output",
                ok=True,
            )

        with mock.patch("arka.teams.executor.resolve_team") as resolve:
            from arka.teams.resolve import ResolvedMember

            resolve.return_value = {
                "lead": ResolvedMember(
                    role="lead",
                    kind="model",
                    member_kind="model",
                    member_id="gpt-4o",
                    provider="openai",
                    model_id="gpt-4o",
                    agent_name="",
                )
            }
            result = execute_workflow(workflow, "test task", team=team, runner=fake_runner)

        self.assertTrue(result.get("run_id"))
        self.assertGreaterEqual(result.get("scratchpad_writes", 0), 1)
        rows = list_scratchpad(team="test-team", workflow="test-wf")
        self.assertGreaterEqual(len(rows), 1)
        prov = rows[0].get("provenance") or {}
        self.assertEqual(prov.get("team"), "test-team")

    def test_unified_memory_no_scratchpad(self) -> None:
        team = Team(
            name="unified-team",
            members=[TeamMember(kind="model", id="gpt-4o", role="lead", provider="openai")],
            defaults={"memory": "unified"},
        )
        workflow = Workflow(
            name="unified-wf",
            team="unified-team",
            steps=[WorkflowStep(member="lead", action="plan", prompt="Plan: {task}")],
        )

        def fake_runner(member, prompt, system):
            from arka.teams.executor import StepResult

            return StepResult(
                role=member.role,
                action="plan",
                member_kind=member.member_kind,
                member_id=member.member_id,
                output="Out",
                ok=True,
            )

        with mock.patch("arka.teams.executor.resolve_team") as resolve:
            from arka.teams.resolve import ResolvedMember

            resolve.return_value = {
                "lead": ResolvedMember(
                    role="lead",
                    kind="model",
                    member_kind="model",
                    member_id="gpt-4o",
                    provider="openai",
                    model_id="gpt-4o",
                    agent_name="",
                )
            }
            result = execute_workflow(workflow, "task", team=team, runner=fake_runner)

        self.assertEqual(result.get("scratchpad_writes", 0), 0)


class EntryMatchTests(unittest.TestCase):
    def test_run_id_must_match(self) -> None:
        prov = Provenance(team="t", workflow="w", run_id="abc", trust_tier="run")
        scope = RecallScope(team="t", workflow="w", run_id="xyz", policy=MemoryPolicy(read_tiers=["run"]))
        self.assertFalse(entry_matches_scope(prov, scope=scope, policy=scope.policy))


class UnifiedMemoryScopedRecallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ.pop("ARKA_MEMORY_TRUST_MAX", None)
        os.environ.pop("ARKA_HUB_MEMORY_SCOPE", None)
        os.environ["ARKA_CONFIG_DIR"] = str(Path(self.tmp.name))
        self.memory_file = Path(self.tmp.name) / "memory.json"
        self.memory_file.write_text(
            json.dumps(
                [
                    {"id": "1", "text": "global pref", "trust_tier": "global"},
                    {
                        "id": "2",
                        "text": "team alpha note",
                        "trust_tier": "team",
                        "provenance": {"team": "alpha", "trust_tier": "team"},
                    },
                ]
            ),
            encoding="utf-8",
        )

    def test_scoped_recall_filters_facts(self) -> None:
        from arka.core.unified_memory import recall

        scope = RecallScope(
            team="alpha",
            policy=MemoryPolicy(read_tiers=["global", "team"]),
        )
        with mock.patch("arka.core.unified_memory.cache_dir", return_value=Path(self.tmp.name)):
            ctx = recall("alpha note pref", scope=scope, limit_chars=3000, include_channel=False)
        self.assertIn("alpha", ctx.lower())
        self.assertIn("global", ctx.lower() or "pref" in ctx.lower())


if __name__ == "__main__":
    unittest.main()
