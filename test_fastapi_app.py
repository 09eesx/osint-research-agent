import unittest

from fastapi.testclient import TestClient

from fastapi_app import SearchIntake, app, build_research_seed


class FastAPIAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.original_execute = app.state.execute_research
        self.captured_intake = None

        def fake_execute(intake: SearchIntake) -> dict:
            self.captured_intake = intake
            return {
                "node_count": 3,
                "edge_count": 2,
                "graph": {"nodes": [], "edges": []},
                "partial_results": True,
                "warnings": ["rate limited"],
                "rate_limit_hits": 1,
            }

        app.state.execute_research = fake_execute

    def tearDown(self) -> None:
        app.state.execute_research = self.original_execute

    def test_intake_form_page_renders(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Octopus Structured Intake", response.text)
        self.assertIn('name="target_name"', response.text)
        self.assertIn('action="/search"', response.text)

    def test_submit_search_parses_structured_input(self) -> None:
        response = self.client.post(
            "/search",
            data={
                "target_name": "Elon Musk",
                "entity_type": "person",
                "purpose": "aday değerlendirmesi",
                "aliases": "Elon Reeve Musk\nE. Musk",
                "known_info": "Tesla\nSpaceX",
                "search_scope": ["github", "wikipedia"],
                "constraints": "2020 sonrası",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.captured_intake)
        self.assertEqual(self.captured_intake.target_name, "Elon Musk")
        self.assertEqual(self.captured_intake.aliases, ["Elon Reeve Musk", "E. Musk"])
        self.assertEqual(self.captured_intake.known_info, ["Tesla", "SpaceX"])
        self.assertEqual(self.captured_intake.search_scope, ["github", "wikipedia"])
        self.assertEqual(self.captured_intake.constraints, "2020 sonrası")
        self.assertIn("Arama Başlatıldı", response.text)
        self.assertIn("Düğüm:</b> 3", response.text)

    def test_api_search_returns_json_payload(self) -> None:
        response = self.client.post(
            "/api/search",
            json={
                "target_name": "OpenAI",
                "entity_type": "company",
                "purpose": "genel şirket araştırması",
                "aliases": ["OpenAI Inc."],
                "known_info": ["San Francisco"],
                "search_scope": ["github", "general_web"],
                "constraints": "yalnızca kamuya açık kaynaklar",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["intake"]["target_name"], "OpenAI")
        self.assertEqual(payload["node_count"], 3)
        self.assertEqual(payload["edge_count"], 2)
        self.assertIn("graph", payload)
        self.assertTrue(payload["partial_results"])
        self.assertEqual(payload["rate_limit_hits"], 1)

    def test_healthcheck(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_build_research_seed_includes_structured_fields(self) -> None:
        intake = SearchIntake(
            target_name="OpenAI",
            entity_type="company",
            purpose="genel şirket araştırması",
            aliases=["OpenAI Inc."],
            known_info=["San Francisco"],
            search_scope=["github", "general_web"],
            constraints="yalnızca kamuya açık kaynaklar",
        )
        seed = build_research_seed(intake)
        self.assertIn("Target: OpenAI", seed)
        self.assertIn("Entity type: company", seed)
        self.assertIn("Aliases: OpenAI Inc.", seed)
        self.assertIn("Search scope: github, general_web", seed)


if __name__ == "__main__":
    unittest.main()
