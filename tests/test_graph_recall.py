"""Tests for Arka Intelligence graph memory."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class GraphRecallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.graph_file = self.root / "memory_graph.json"
        os.environ["ARKA_GRAPH_MEMORY"] = "1"

    def _patch_paths(self):
        return mock.patch("arka.memory.graph_memory.GRAPH_FILE", self.graph_file)

    def test_remember_extracts_named_entity(self) -> None:
        from arka.memory.graph_memory import graph_remember, load_graph

        with self._patch_paths():
            result = graph_remember("My dog is named Max")
            self.assertTrue(result.get("ingested"))
            graph = load_graph()
        labels = {e["label"] for e in graph["entities"] if isinstance(e, dict)}
        self.assertIn("Max", labels)
        preds = {e["predicate"] for e in graph["edges"] if isinstance(e, dict)}
        self.assertTrue(any("has_dog" in p or p == "has_dog" for p in preds))

    def test_recall_traverses_related_edges(self) -> None:
        from arka.memory.graph_memory import graph_remember, graph_recall

        with self._patch_paths():
            graph_remember("My dog is named Max")
            graph_remember("I prefer Hindi TTS")
            narrative, meta = graph_recall("Max dog", limit_chars=2000)
        self.assertIn("Max", narrative)
        self.assertGreater(meta.get("edges_traversed", 0), 0)
        self.assertEqual(meta.get("backend"), "graph")

    def test_preference_triple(self) -> None:
        from arka.memory.graph_memory import graph_remember, load_graph

        with self._patch_paths():
            graph_remember("I prefer dark terminal theme")
            graph = load_graph()
        edges = [e for e in graph["edges"] if isinstance(e, dict)]
        self.assertTrue(any(e.get("predicate") == "prefer" for e in edges))

    def test_rebuild_from_memory_file(self) -> None:
        from arka.memory.graph_memory import rebuild_from_memory_file

        memory_file = self.root / "memory.json"
        memory_file.write_text(
            json.dumps(
                [
                    {"id": "f1", "text": "User lives in Bangalore", "tags": []},
                    {"id": "f2", "text": "User's favorite editor is Neovim", "tags": []},
                ]
            ),
            encoding="utf-8",
        )
        with (
            self._patch_paths(),
            mock.patch("arka.memory.graph_memory.cache_dir", return_value=self.root),
        ):
            stats = rebuild_from_memory_file()
        self.assertTrue(stats.get("rebuilt"))
        self.assertGreaterEqual(stats.get("edges", 0), 1)

    def test_status_reports_graph_backend(self) -> None:
        from arka.memory.graph_memory import status

        with self._patch_paths():
            info = status()
        self.assertTrue(info.get("enabled"))
        self.assertEqual(info.get("backend"), "local_graph")
        self.assertIn("recall_path", info)

    def test_export_mermaid(self) -> None:
        from arka.memory.graph_memory import export_mermaid, graph_remember

        with self._patch_paths():
            graph_remember("My cat is named Luna")
            mermaid = export_mermaid()
        self.assertIn("graph LR", mermaid)
        self.assertIn("Luna", mermaid)

    def test_disabled_returns_empty_recall(self) -> None:
        from arka.memory.graph_memory import graph_recall

        os.environ["ARKA_GRAPH_MEMORY"] = "0"
        with self._patch_paths():
            narrative, meta = graph_recall("anything")
        self.assertEqual(narrative, "")
        self.assertFalse(meta.get("enabled", True))


class UnifiedMemoryGraphIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        os.environ["UNIFIED_MEMORY"] = "1"
        os.environ["ARKA_GRAPH_MEMORY"] = "1"

    def test_recall_includes_graph_section(self) -> None:
        from arka.core.unified_memory import recall

        memory_file = self.root / "memory.json"
        memory_file.write_text(
            json.dumps([{"id": "a1", "text": "User's dog is named Max", "tags": []}]),
            encoding="utf-8",
        )
        graph_file = self.root / "memory_graph.json"
        with (
            mock.patch("arka.core.unified_memory.cache_dir", return_value=self.root),
            mock.patch("arka.integrations.supermemory.context_for", return_value=""),
            mock.patch("arka.memory.graph_memory.GRAPH_FILE", graph_file),
        ):
            from arka.memory.graph_memory import graph_remember

            graph_remember("User's dog is named Max")
            ctx = recall("Max dog", limit_chars=5000)
        self.assertIn("Knowledge graph", ctx)
        self.assertIn("Max", ctx)


class McpIntelligenceTests(unittest.TestCase):
    def test_handle_arka_intelligence_status(self) -> None:
        from arka.integrations.mcp_server import _handle_arka_intelligence

        with mock.patch("arka.memory.graph_memory.status", return_value={"enabled": True, "entities": 1}):
            out = _handle_arka_intelligence({"action": "status"})
        self.assertIn("enabled", out)


if __name__ == "__main__":
    unittest.main()
