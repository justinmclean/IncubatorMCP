from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from ipmc import data, tools


def _projects_fixture() -> list[dict[str, Any]]:
    return [
        {"name": "Apache Foo", "url": "https://foo.apache.org", "description": "Test PMC", "type": "tlp"},
        {"name": "Apache Bar", "url": "https://bar.apache.org", "description": "Another PMC", "type": "tlp"},
    ]


class ProposedNameCheckTests(unittest.TestCase):
    def test_unavailable_when_package_missing(self) -> None:
        with mock.patch.object(data, "trademark_projects", None), \
                mock.patch.object(data, "trademark_policy", None):
            payload = data.load_proposed_name_check("Quux")
        self.assertFalse(payload["available"])
        self.assertEqual(payload["proposed_name"], "Quux")
        self.assertIn("apache-trademark-mcp", payload["reason"])

    def test_pass_path_uses_upstream_policy_helpers(self) -> None:
        fake_policy = mock.Mock()
        fake_policy.check_reserved.return_value = []
        fake_policy.check_native_american.return_value = []
        fake_policy.check_format.return_value = ([], [])
        fake_policy.normalize.side_effect = lambda value: value.lower()
        fake_policy.policy_citations.return_value = [{"title": "Trademark policy", "url": "https://example/"}]

        fake_projects = mock.Mock()
        fake_projects.fetch_projects.return_value = _projects_fixture()
        fake_projects.find_name_conflicts.return_value = ([], ["nearby-name"])
        fake_projects.find_similar.return_value = []
        fake_projects.project_descriptions.return_value = {}
        fake_projects.cache_age_hours.return_value = 1.0
        fake_projects.cache_dir_from_env.return_value = "/tmp/cache"

        with mock.patch.object(data, "trademark_projects", fake_projects), \
                mock.patch.object(data, "trademark_policy", fake_policy), \
                mock.patch.object(data, "trademark_search", None):
            payload = data.load_proposed_name_check("Quux")

        self.assertTrue(payload["available"])
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["blocking_issues"], [])
        self.assertEqual(payload["nearby_asf_names"], ["nearby-name"])
        self.assertEqual(payload["policy_citations"], [{"title": "Trademark policy", "url": "https://example/"}])

    def test_exact_conflict_is_blocking(self) -> None:
        fake_policy = mock.Mock()
        fake_policy.check_reserved.return_value = []
        fake_policy.check_native_american.return_value = []
        fake_policy.check_format.return_value = ([], [])
        fake_policy.normalize.side_effect = lambda value: value.lower()
        fake_policy.policy_citations.return_value = []

        fake_projects = mock.Mock()
        fake_projects.fetch_projects.return_value = _projects_fixture()
        fake_projects.find_name_conflicts.return_value = (
            [{"name": "Apache Foo", "match_type": "exact", "similarity": 1.0}],
            [],
        )
        fake_projects.find_similar.return_value = []
        fake_projects.project_descriptions.return_value = {}
        fake_projects.cache_age_hours.return_value = 0.0
        fake_projects.cache_dir_from_env.return_value = "/tmp/cache"

        with mock.patch.object(data, "trademark_projects", fake_projects), \
                mock.patch.object(data, "trademark_policy", fake_policy), \
                mock.patch.object(data, "trademark_search", None):
            payload = data.load_proposed_name_check("Foo")

        self.assertEqual(payload["verdict"], "FAIL")
        self.assertTrue(payload["blocking_issues"])
        self.assertIn("Apache Foo", payload["blocking_issues"][0])


class BrandingCheckTests(unittest.TestCase):
    def test_unavailable_when_package_missing(self) -> None:
        with mock.patch.object(data, "trademark_compliance", None), \
                mock.patch.object(data, "trademark_web", None), \
                mock.patch.object(data, "trademark_projects", None), \
                mock.patch.object(data, "trademark_policy", None):
            payload = data.load_project_website_branding_check("https://foo.apache.org")
        self.assertFalse(payload["available"])
        self.assertEqual(payload["target_url"], "https://foo.apache.org")

    def test_invalid_stage_raises(self) -> None:
        fake_policy = mock.Mock(VALID_BRANDING_STAGES={"podling", "graduation", "tlp"})
        with mock.patch.object(data, "trademark_compliance", mock.Mock()), \
                mock.patch.object(data, "trademark_web", mock.Mock()), \
                mock.patch.object(data, "trademark_projects", mock.Mock()), \
                mock.patch.object(data, "trademark_policy", fake_policy):
            with self.assertRaises(ValueError):
                data.load_project_website_branding_check("https://foo.apache.org", stage="bogus")

    def test_success_path_returns_report_payload(self) -> None:
        fake_report = mock.Mock()
        fake_report.to_dict.return_value = {
            "target_url": "https://foo.apache.org",
            "final_url": "https://foo.apache.org/",
            "verdict": "PASS",
            "counts": {"PASS": 5},
            "severity_counts": {},
            "fetch_error": None,
            "findings": [],
        }
        fake_compliance = mock.Mock()
        fake_compliance.check_project_website.return_value = fake_report
        fake_compliance.project_names_for_bare_scan.return_value = []
        fake_compliance.POLICY_URLS = {"branding": "https://example/"}
        fake_compliance._infer_project_name.return_value = "Foo"

        fake_web = mock.Mock()
        fake_web.fetch_page.return_value = mock.Mock()

        fake_projects = mock.Mock()
        fake_projects.fetch_projects.return_value = []
        fake_projects.cache_dir_from_env.return_value = "/tmp/cache"

        fake_policy = mock.Mock(VALID_BRANDING_STAGES={"podling", "graduation", "tlp"})
        fake_policy.branding_checklist.return_value = {"stage": "podling", "items": []}

        with mock.patch.object(data, "trademark_compliance", fake_compliance), \
                mock.patch.object(data, "trademark_web", fake_web), \
                mock.patch.object(data, "trademark_projects", fake_projects), \
                mock.patch.object(data, "trademark_policy", fake_policy):
            payload = data.load_project_website_branding_check(
                "https://foo.apache.org", project_name="Foo", stage="podling"
            )

        self.assertTrue(payload["available"])
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["project_name"], "Foo")
        self.assertEqual(payload["stage"], "podling")
        self.assertEqual(payload["policy_references"], {"branding": "https://example/"})

    def test_fetch_failure_returns_unavailable(self) -> None:
        fake_web = mock.Mock()
        fake_web.fetch_page.side_effect = RuntimeError("network down")
        fake_policy = mock.Mock(VALID_BRANDING_STAGES={"podling", "graduation", "tlp"})

        with mock.patch.object(data, "trademark_compliance", mock.Mock()), \
                mock.patch.object(data, "trademark_web", fake_web), \
                mock.patch.object(data, "trademark_projects", mock.Mock()), \
                mock.patch.object(data, "trademark_policy", fake_policy):
            payload = data.load_project_website_branding_check("https://foo.apache.org")
        self.assertFalse(payload["available"])
        self.assertIn("network down", payload["reason"])


class ThirdPartyCheckTests(unittest.TestCase):
    def test_success_path(self) -> None:
        fake_report = mock.Mock()
        fake_report.to_dict.return_value = {
            "target_url": "https://third.example",
            "final_url": "https://third.example/",
            "verdict": "WARN",
            "counts": {"WARN": 1, "PASS": 2},
            "severity_counts": {},
            "fetch_error": None,
            "findings": [{"rule": "branding_form", "status": "WARN", "detail": "...", "policy_url": "https://x"}],
        }
        fake_compliance = mock.Mock()
        fake_compliance.check_third_party_use.return_value = fake_report
        fake_compliance.project_names_for_bare_scan.return_value = []
        fake_compliance.POLICY_URLS = {"trademark_policy": "https://example/"}

        fake_web = mock.Mock()
        fake_web.fetch_page.return_value = mock.Mock()

        fake_projects = mock.Mock()
        fake_projects.fetch_projects.return_value = []
        fake_projects.cache_dir_from_env.return_value = "/tmp/cache"

        with mock.patch.object(data, "trademark_compliance", fake_compliance), \
                mock.patch.object(data, "trademark_web", fake_web), \
                mock.patch.object(data, "trademark_projects", fake_projects):
            payload = data.load_third_party_use_check("https://third.example", mark="Kafka")

        self.assertTrue(payload["available"])
        self.assertEqual(payload["verdict"], "WARN")
        self.assertEqual(payload["mark"], "Kafka")
        self.assertEqual(payload["findings"][0]["rule"], "branding_form")


class TrademarkToolDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._configured = data.configured_defaults_snapshot()

    def tearDown(self) -> None:
        data.restore_configured_defaults(self._configured)

    def test_tools_are_registered(self) -> None:
        for name in (
            "trademark_naming_check",
            "trademark_branding_check",
            "trademark_third_party_check",
            "refresh_trademark_cache",
        ):
            self.assertIn(name, tools.TOOLS)

    def test_configure_sources_accepts_trademark_cache(self) -> None:
        payload = tools.tool_configure_sources({"trademark_cache": "/tmp/trademark-cache"})
        self.assertIn("trademark_cache", payload["updated"])
        self.assertEqual(
            payload["source_defaults"]["effective"]["trademark_cache"], "/tmp/trademark-cache"
        )

    def test_naming_tool_passes_through(self) -> None:
        fake_payload = {
            "available": True,
            "verdict": "PASS",
            "blocking_issues": [],
            "warnings": [],
            "asf_name_conflicts": [],
            "nearby_asf_names": [],
            "fuzzy_asf_results": [],
            "policy_citations": [],
            "apache_form": "Apache Quux",
            "cache_dir": "/tmp/cache",
            "cache_age_hours": 0.5,
        }
        with mock.patch.object(tools, "load_proposed_name_check", return_value=fake_payload) as loader:
            payload = tools.tool_trademark_naming_check(
                {"proposed_name": "Quux", "include_external_search": False}
            )
        loader.assert_called_once()
        self.assertEqual(payload["generated_for"], "trademark_naming_check")
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["proposed_name"], "Quux")

    def test_branding_tool_requires_podling_or_url(self) -> None:
        with self.assertRaises(ValueError):
            tools.tool_trademark_branding_check({})

    def test_branding_tool_resolves_url_from_podlings_xml(self) -> None:
        fake_podlings = [{"name": "Alpha", "resource": "https://alpha.apache.org"}]
        fake_payload = {
            "available": True,
            "target_url": "https://alpha.apache.org",
            "final_url": "https://alpha.apache.org/",
            "verdict": "PASS",
            "counts": {"PASS": 3},
            "severity_counts": {},
            "findings": [],
            "project_name": "Alpha",
            "stage": "podling",
            "checklist": None,
            "policy_references": {},
            "fetch_error": None,
            "cache_dir": None,
        }
        with mock.patch.object(tools, "load_podlings", return_value=(fake_podlings, {"source": "x"})), \
                mock.patch.object(tools, "load_project_website_branding_check", return_value=fake_payload) as loader:
            payload = tools.tool_trademark_branding_check({"podling": "Alpha"})
        loader.assert_called_once()
        called_url = loader.call_args.args[0]
        self.assertEqual(called_url, "https://alpha.apache.org")
        self.assertEqual(loader.call_args.kwargs["stage"], "podling")
        self.assertEqual(payload["podling"], "Alpha")
        self.assertEqual(payload["verdict"], "PASS")

    def test_third_party_tool_requires_url(self) -> None:
        with self.assertRaises(ValueError):
            tools.tool_trademark_third_party_check({})

    def test_third_party_tool_passes_through(self) -> None:
        fake_payload = {
            "available": True,
            "target_url": "https://t.example",
            "final_url": "https://t.example/",
            "verdict": "FAIL",
            "counts": {"FAIL": 1},
            "severity_counts": {"CRITICAL": {"FAIL": 1}},
            "findings": [{"rule": "logo_misuse", "status": "FAIL", "detail": "", "policy_url": "x"}],
            "mark": "Kafka",
            "policy_references": {},
            "fetch_error": None,
            "cache_dir": None,
        }
        with mock.patch.object(tools, "load_third_party_use_check", return_value=fake_payload):
            payload = tools.tool_trademark_third_party_check({"url": "https://t.example", "mark": "Kafka"})
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["mark"], "Kafka")
        self.assertEqual(payload["generated_for"], "trademark_third_party_check")


if __name__ == "__main__":
    unittest.main()
