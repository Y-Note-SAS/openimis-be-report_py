from django.apps import AppConfig
from openIMIS.openimisapps import openimis_apps
import importlib.util
import logging

logger = logging.getLogger(__file__)

MODULE_NAME = "report"

DEFAULT_CFG = {
    "gql_query_report_perms": ["131200"],
    "gql_reports_primary_operational_indicator_policies_perms": ["131201"],
    "gql_reports_primary_operational_indicators_claims_perms": ["131202"],
    "gql_reports_derived_operational_indicators_perms": ["131203"],
    "gql_reports_contribution_collection_perms": ["131204"],
    "gql_reports_product_sales_perms": ["131205"],
    "gql_reports_contribution_distribution_perms": ["131206"],
    "gql_reports_user_activity_perms": ["131207"],
    "gql_reports_enrolment_performance_indicators_perms": ["131208"],
    "gql_reports_status_of_register_perms": ["131209"],
    "gql_reports_insuree_without_photos_perms": ["131210"],
    "gql_reports_payment_category_overview_perms": ["131211"],
    "gql_reports_matching_funds_perms": ["131212"],
    "gql_reports_claim_overview_report_perms": ["131213"],
    "gql_reports_percentage_referrals_perms": ["131214"],
    "gql_reports_families_insurees_overview_perms": ["131215"],
    "gql_reports_pending_insurees_perms": ["131216"],
    "gql_reports_renewals_perms": ["131217"],
    "gql_reports_capitation_payment_perms": ["131218"],
    "gql_reports_rejected_photo_perms": ["131219"],
    "gql_reports_contribution_payment_perms": ["131220"],
    "gql_reports_control_number_assignment_perms": ["131221"],
    "gql_reports_overview_of_commissions_perms": ["131222"],
    "gql_reports_claim_history_report_perms": ["131223"],

    "gql_mutation_report_add_perms": ["131224"],
    "gql_mutation_report_edit_perms": ["131225"],
    "gql_mutation_report_delete_perms": ["131226"],
}


class ReportConfig(AppConfig):
    name = MODULE_NAME

    gql_query_report_perms = []
    gql_mutation_report_add_perms = []
    gql_mutation_report_edit_perms = []
    gql_mutation_report_delete_perms = []
    gql_reports_primary_operational_indicator_policies_perms = []
    gql_reports_primary_operational_indicators_claims_perms = []
    gql_reports_derived_operational_indicators_perms = []
    gql_reports_contribution_collection_perms = []
    gql_reports_product_sales_perms = []
    gql_reports_contribution_distribution_perms = []
    gql_reports_user_activity_perms = []
    gql_reports_enrolment_performance_indicators_perms = []
    gql_reports_status_of_register_perms = []
    gql_reports_insuree_without_photos_perms = []
    gql_reports_payment_category_overview_perms = []
    gql_reports_matching_funds_perms = []
    gql_reports_claim_overview_report_perms = []
    gql_reports_percentage_referrals_perms = []
    gql_reports_families_insurees_overview_perms = []
    gql_reports_pending_insurees_perms = []
    gql_reports_renewals_perms = []
    gql_reports_capitation_payment_perms = []
    gql_reports_rejected_photo_perms = []
    gql_reports_contribution_payment_perms = []
    gql_reports_control_number_assignment_perms = []
    gql_reports_overview_of_commissions_perms = []
    gql_reports_claim_history_report_perms = []

    reports = []

    def __load_config(self, cfg):
        for field in cfg:
            if hasattr(ReportConfig, field):
                setattr(ReportConfig, field, cfg[field])

    @classmethod
    def get_report(cls, report_name):
        for report in cls.reports:
            if report["name"] == report_name:
                return report
        return None

    def ready(self):
        from core.models import ModuleConfiguration

        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CFG)
        self.__load_config(cfg)

        all_apps = openimis_apps()

        for app in all_apps:
            try:
                self.load_app_reports(app)
            except Exception as exc:
                logger.debug(f"{app}: unknown exception occurred while adding report_definitions: {exc}")

        logger.debug("done loading reports")

    def load_app_reports(self, app_):
        spec = importlib.util.find_spec(f"{app_}.report")
        if spec:
            app = __import__(f"{app_}.report")
            if (
                hasattr(app, "report") and
                hasattr(app.report, "report_definitions")and
                isinstance(app.report.report_definitions, list)
            ):
                self.reports += app.report.report_definitions
                logger.debug(
                    f"{app_} {len(app.report.report_definitions)} reports loaded"
                )
            else:
                logger.debug(
                    f"{app_} has report submodule but no valid report_definitions"
                )
        else:
            logger.debug(
                logger.debug(f"{app_} has no report submodule, skipping")
            )