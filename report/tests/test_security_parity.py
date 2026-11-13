"""
Security parity tests for the report module (API rights + row scope) against the
openimis-dev-tools reference (release/26.10).

Each test asserts the REFERENCE behaviour: a failure is a gap in Cameroon.
Tags: [REF <reference file>::<test or line>] ported, [NEW] no reference equivalent.

Run: python manage.py test report.test_security_parity --keepdb
"""
import json
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from core.test_helpers import (
    create_right_only_user,
    create_security_tree,
    get_test_token,
)
from insuree.test_helpers import create_test_insuree
from report.apps import ReportConfig

REPORT_QUERY_RIGHT = 131200  # gql_query_report_perms
FAMILY_REPORT_RIGHT = 131215  # gql_reports_families_insurees_overview_perms
CLAIM_OVERVIEW_RIGHT = 131213

REPORTS_GQL = "query { reports { name } }"


def _body(response):
    return getattr(response, "content", b"<stream>")[:300]


def _url(path):
    return f"/{settings.SITE_ROOT()}report/{path}"


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tree = create_security_tree("SPRP")
        cls.no_right = create_right_only_user("sprp_noright", [], [cls.tree.d1.id])
        cls.report_user = create_right_only_user(
            "sprp_rep", [REPORT_QUERY_RIGHT, FAMILY_REPORT_RIGHT, CLAIM_OVERVIEW_RIGHT],
            [cls.tree.d1.id])

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {get_test_token(user)}")
        return client


@mock.patch("report.views.generate_report", return_value=b"%PDF-fake")
class ReportViewRightsTest(_Base):
    """The REST report runner: `GET report/<name>/<format>/`."""

    def test_anonymous_cannot_run_a_report(self, _gen):
        """[REF report/views.py:28 @permission_classes([IsAuthenticated])]"""
        response = self.client_for(None).get(_url("insuree_family_overview/pdf/"))
        self.assertIn(response.status_code, (401, 403), _body(response))

    def test_user_without_report_right_is_refused(self, _gen):
        """[REF report/views.py:28 requires gql_query_report_perms OR report permission]"""
        response = self.client_for(self.no_right).get(_url("insuree_family_overview/pdf/"))
        self.assertEqual(403, response.status_code, _body(response))

    def test_user_with_the_report_right_can_run_it(self, _gen):
        """[REF report/views.py:28] positive control"""
        response = self.client_for(self.report_user).get(_url("insuree_missing_photo/pdf/"))
        self.assertEqual(200, response.status_code, _body(response))

    def test_report_without_declared_permission_still_requires_the_report_right(self, _gen):
        """[NEW] Cameroon report/views.py:44 only checks rights `if report_config.get("permission")`:
        a report definition without a `permission` key runs for anyone (reference: rights
        always checked, IsAuthenticated first)."""
        query = mock.Mock(return_value={"data": []})
        fake = {"name": "sprp_fake_report", "engine": 0, "default_report": {},
                "description": "fake", "module": "report", "python_query": query}
        with mock.patch.object(ReportConfig, "reports", ReportConfig.reports + [fake]):
            response = self.client_for(self.no_right).get(_url("sprp_fake_report/pdf/"))
        self.assertIn(response.status_code, (401, 403), _body(response))
        query.assert_not_called()


@mock.patch("report.views.loader.get_template",
            return_value=mock.Mock(render=mock.Mock(return_value="designer")))
class ReportBroViewsTest(_Base):
    """The ReportBro designer/previewer (templates authoring). The template loader is
    stubbed (no collected static manifest in tests); only the access gate is tested."""

    def test_designer_requires_authentication(self, _tpl):
        """[REF report/views.py reportbro_designer check_user_rights(gql_query_report_perms)]"""
        response = self.client_for(None).get(_url("reportbro/designer"))
        self.assertIn(response.status_code, (302, 401, 403), response.status_code)

    def test_designer_requires_the_report_right(self, _tpl):
        """[REF report/views.py reportbro_designer check_user_rights(gql_query_report_perms)]"""
        response = self.client_for(self.no_right).get(_url("reportbro/designer"))
        self.assertIn(response.status_code, (302, 401, 403), response.status_code)

    def test_previewer_requires_authentication(self, _tpl):
        """[REF report/views.py reportbro_previewer check_user_rights(gql_query_report_perms)]"""
        response = self.client_for(None).put(
            _url("reportbro/preview"),
            data=json.dumps({"outputFormat": "pdf", "report": {}, "data": {}, "isTestData": True}),
            content_type="application/json")
        self.assertIn(response.status_code, (401, 403), response.status_code)


class ReportGraphQLRightsTest(_Base):
    def _gql(self, user):
        response = self.client_for(user).post(
            f"/{settings.SITE_ROOT()}graphql", data={"query": REPORTS_GQL}, format="json")
        return json.loads(response.content)

    def test_query_reports_right(self):
        """[REF report/test_rights_roles.py::ReportRightsTests::test_query_reports_right]"""
        allowed = self._gql(self.report_user)
        self.assertFalse(allowed.get("errors"), allowed)
        denied = self._gql(self.no_right)
        self.assertTrue(denied.get("errors"), denied)


class ReportLocationScopeTest(_Base):
    """A report run by a user granted D1 must not return rows from D2 - whatever location
    parameter the caller sends."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ins1 = create_test_insuree(
            custom_props={"chf_id": "SPRPI001", "current_village": cls.tree.v1},
            family_custom_props={"location": cls.tree.v1})
        cls.ins2 = create_test_insuree(
            custom_props={"chf_id": "SPRPI002", "current_village": cls.tree.v2},
            family_custom_props={"location": cls.tree.v2})

    def test_insuree_family_overview_is_scoped(self):
        """[REF insuree/reports/insuree_family_overview.py:1722 (the one scoped report)]"""
        from django.core.exceptions import FieldError
        from insuree.reports.insuree_family_overview import insuree_family_overview_query

        try:
            rows = insuree_family_overview_query(self.report_user)["data"]
        except FieldError as exc:
            self.fail(f"report crashes for a district-restricted user: {exc}")
        chf_ids = {r["chf_id"] for r in rows}
        self.assertIn("SPRPI001", chf_ids)
        self.assertNotIn("SPRPI002", chf_ids)

    def test_missing_photo_report_on_a_foreign_district_returns_nothing(self):
        """[NEW] insuree_missing_photo takes `locationId` from the request and never checks
        it against the user's districts (reference: same gap, flagged)."""
        from insuree.reports.insuree_missing_photo import insuree_missing_photo_query

        rows = insuree_missing_photo_query(self.report_user, locationId=self.tree.d2.id)["data"]
        self.assertNotIn("SPRPI002", {r["chf_id"] for r in (rows or [])})

    def test_missing_photo_report_without_location_is_scoped(self):
        """[NEW] locationId omitted/None = whole country: must still be limited to D1."""
        from insuree.reports.insuree_missing_photo import insuree_missing_photo_query

        rows = insuree_missing_photo_query(self.report_user, locationId=None)["data"]
        self.assertNotIn("SPRPI002", {r["chf_id"] for r in (rows or [])})

    def test_report_view_with_foreign_district_parameter_is_refused_or_empty(self):
        """[NEW] End to end through the view: the parameters reach `python_query` unchecked."""
        captured = {}

        def fake_render(name, definition, data, fmt, **kw):
            captured["data"] = data
            return b"%PDF-fake"

        with mock.patch("report.views.generate_report", side_effect=fake_render):
            response = self.client_for(self.report_user).get(
                _url("insuree_missing_photo/pdf/"), {"locationId": self.tree.d2.id})
        if response.status_code in (401, 403, 404):
            return
        rows = (captured.get("data") or {}).get("data") or []
        self.assertNotIn("SPRPI002", {r["chf_id"] for r in rows})


class ReportUnscopedRunTest(_Base):
    """[NEW] Run on "all" (no specific location), most report queries cover every district:
    a location-restricted user must name a location in scope, and may not run the
    national-only reports; the unscoped-location right (location module) lifts it."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from location.apps import LocationConfig
        cls.national_user = create_right_only_user(
            "sprp_nat", [REPORT_QUERY_RIGHT, CLAIM_OVERVIEW_RIGHT]
            + [int(r) for r in LocationConfig.gql_unscoped_location_perms], [cls.tree.d1.id])

    def test_location_report_on_all_refused(self):
        from report.scope import unscoped_run_refused
        for params in ({}, {"requested_region_id": "-1", "requested_district_id": "-1"}, {"locationId": "0"}):
            self.assertTrue(unscoped_run_refused(self.report_user, "claims_overview", params), params)

    def test_location_report_with_own_district_allowed(self):
        from report.scope import unscoped_run_refused
        self.assertIsNone(unscoped_run_refused(
            self.report_user, "claims_overview", {"requested_district_id": str(self.tree.d1.id)}))

    def test_national_report_refused(self):
        from report.scope import unscoped_run_refused
        self.assertTrue(unscoped_run_refused(self.report_user, "contributions_distribution", {}))

    def test_self_limiting_reports_unaffected(self):
        from report.scope import unscoped_run_refused
        for name in ("insuree_missing_photo", "insuree_family_overview"):
            self.assertIsNone(unscoped_run_refused(self.report_user, name, {}), name)

    def test_unscoped_location_right_lifts_it(self):
        from report.scope import unscoped_run_refused
        self.assertIsNone(unscoped_run_refused(self.national_user, "claims_overview", {}))
        self.assertIsNone(unscoped_run_refused(self.national_user, "contributions_distribution", {}))

    @mock.patch("report.views.generate_report", return_value=b"%PDF-fake")
    def test_view_refuses_before_running_the_query(self, _gen):
        config = ReportConfig.get_report("claims_overview")
        with mock.patch.dict(config, {"python_query": mock.Mock(return_value={"data": []})}):
            response = self.client_for(self.report_user).get(_url("claims_overview/pdf/"))
            self.assertEqual(403, response.status_code, _body(response))
            config["python_query"].assert_not_called()
