"""Tests for email classification schema, routing, and graph wiring (stdlib unittest)."""
import unittest

from src.workflows.state import EmailClassification, EmailAnalysis
from langgraph.graph import END
from src.workflows import agent


class SchemaTests(unittest.TestCase):
    def test_classification_defaults(self):
        c = EmailClassification(category="notification")
        self.assertEqual(c.category, "notification")
        self.assertEqual(c.reason, "")

    def test_analysis_has_needs_task(self):
        a = EmailAnalysis()
        self.assertFalse(a.needs_task)


class RoutingTests(unittest.TestCase):
    def test_empty_body_classified_as_promotion(self):
        self.assertEqual(
            agent._empty_body_classification({"email_content": "   "}),
            {"category": "promotion", "reason": "Email had no readable text content."},
        )

    def test_non_empty_body_returns_none(self):
        self.assertIsNone(agent._empty_body_classification({"email_content": "Hi there"}))

    def test_route_actionable(self):
        state = {"classification": {"category": "actionable"}}
        self.assertEqual(agent.route_after_classification(state), "extract")

    def test_route_notification(self):
        state = {"classification": {"category": "notification"}}
        self.assertEqual(agent.route_after_classification(state), "notify")

    def test_route_promotion_ends(self):
        state = {"classification": {"category": "promotion"}}
        self.assertEqual(agent.route_after_classification(state), END)

    def test_route_missing_classification_ends(self):
        self.assertEqual(agent.route_after_classification({}), END)


class GraphWiringTests(unittest.TestCase):
    def test_graph_has_expected_nodes(self):
        graph = agent.build_agent_graph()
        node_names = set(graph.get_graph().nodes.keys())
        for expected in ("classifier", "extractor", "notification_review", "human_review", "executor"):
            self.assertIn(expected, node_names)


class NotificationNodeTests(unittest.TestCase):
    def test_notification_review_acknowledges(self):
        import asyncio
        from unittest.mock import patch
        state = {"classification": {"category": "notification", "reason": "x"}}
        with patch.object(agent, "interrupt", return_value=None) as mock_interrupt:
            result = asyncio.run(agent.notification_review(state))
        mock_interrupt.assert_called_once()
        self.assertEqual(result["approval_status"], "acknowledged")


if __name__ == "__main__":
    unittest.main()
