import io
import json
import logging
import os
import tempfile

from django.contrib.staticfiles import finders
from django.http import Http404, HttpResponse, HttpResponseBadRequest, FileResponse
from django.template import loader
from django.utils.translation import gettext as _
from django.views.decorators.clickjacking import xframe_options_exempt
from reportbro import Report, ReportBroError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from report.services import generate_report, get_report_definition

from .apps import ReportConfig
from .scope import out_of_scope_parameters, unscoped_run_refused

logger = logging.getLogger(__file__)


def _report_right_required():
    """Permission class (ported from the reference `core.views.check_user_rights`):
    authenticated AND holding the generic report right."""

    class UserWithReportRight(IsAuthenticated):
        def has_permission(self, request, view):
            return super().has_permission(request, view) and \
                request.user.has_perms(ReportConfig.gql_query_report_perms)

    return UserWithReportRight


@api_view(["GET"])
# Only authentication is enforced here: which right grants *this* report depends
# on the report being asked for. The rights check is below (reference logic).
@permission_classes([IsAuthenticated])
def report(request, report_name, report_format="pdf", alternate=None):
    """
    Run a report
    :param request: Predefined by Django
    :param report_name: Report name within the module
    :param report_format: pdf (default) or xlsx
    :param alternate: Future use, allows several templates for a single report: different languages or report variants
    :return: view
    """
    logger.debug(
        "report name %s in %s format",
        report_name,
        report_format,
    )
    report_config = ReportConfig.get_report(report_name)
    if not report_config:
        raise Http404("Poll does not exist")
    report_definition = get_report_definition(
        report_name, report_config["default_report"]
    )
    # Either the generic "may run reports" right or the right the report declares
    # for itself is enough. A report that declares none needs the generic right.
    report_permission = report_config.get("permission")
    if not (
        request.user.has_perms(ReportConfig.gql_query_report_perms)
        or (report_permission and request.user.has_perms(report_permission))
    ):
        raise PermissionDenied(_("unauthorized"))

    # parameters tend to get put in lists because they *could* be repeated
    unlisted = {
        k: (v[0] if isinstance(v, list) and len(v) == 0 else v)
        for k, v in request.GET.items()
    }

    # A location / health facility parameter outside the user's scope is refused
    # before the query runs (the queries do not check it themselves).
    refused = out_of_scope_parameters(request.user, unlisted)
    if refused:
        logger.warning("report %s refused, parameters out of scope: %s", report_name, refused)
        raise PermissionDenied(_("unauthorized"))
    # ... and so is a run on "all" (every district) or a national-only report, for a user
    # narrowed to their districts
    reason = unscoped_run_refused(request.user, report_name, unlisted)
    if reason:
        logger.warning("report %s refused for a location-restricted user: %s", report_name, reason)
        raise PermissionDenied(_("unauthorized"))

    data = report_config["python_query"](request.user, **unlisted)
    filename_from_data = data.get("report_filename", report_name)

    # The queries signal a bad (or out of scope) parameter by returning
    # {"error": ...}: answer 400 instead of rendering the error into a PDF.
    if isinstance(data, dict) and data.get("error"):
        raise ValidationError(data["error"])

    return FileResponse(
        io.BytesIO(
            generate_report(
                report_name,
                report_definition,
                data,
                report_format,
            )
        ), filename=f"{filename_from_data}.{report_format}", as_attachment=False
    )


@api_view(["GET", "PUT", "POST"])
@xframe_options_exempt
@permission_classes([_report_right_required()])
def reportbro_designer(request):
    template = loader.get_template("report/reportbro.html")

    context = {}
    return HttpResponse(template.render(context, request))


@api_view(["GET", "PUT", "POST"])
@xframe_options_exempt
@permission_classes([_report_right_required()])
def reportbro_previewer(request):
    """
    Generates a report preview within the designer. This can work in two ways:
    1. The report details are passed as a PUT. We generate the report and store the result in a temporary file.
       The Designer then runs a GET request to retrieve the generated report with the key returned by the PUT request.
       This only generates PDFs in theory.
    2. The report is generated on the fly. This is used by the Designer to generate PDFs and XLSX files.
    """
    response = HttpResponse('')
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = 'GET, PUT, OPTIONS'
    response['Access-Control-Allow-Headers'] = \
        'Origin, X-Requested-With, X-HTTP-Method-Override, Content-Type, Accept, Authorization, Z-Key'

    if request.method == "PUT":
        json_data = json.loads(request.body.decode('utf-8'))
        output_format = json_data.get('outputFormat')
        if output_format not in ('pdf', 'xlsx'):
            return HttpResponseBadRequest('outputFormat parameter missing or invalid')
        if not isinstance(json_data, dict) or not isinstance(json_data.get('report'), dict) or \
                not isinstance(json_data.get('data'), dict) or not isinstance(json_data.get('isTestData'), bool):
            return HttpResponseBadRequest('invalid report values')
        report_definition = json_data.get('report')
        data = json_data.get('data')
        is_test_data = json_data.get('isTestData')
        try:
            temp_file=tempfile.NamedTemporaryFile(delete=False)
            key = os.path.basename(temp_file.name)
            generate_report("preview", report_definition, data, output_format,
                            local_file=temp_file.name, is_test_data=is_test_data)
            return HttpResponse('key:'+key)
        except ReportBroError as e:
            logger.exception(e.error)
            return HttpResponse(json.dumps(dict(errors=[e.error])))
        except Exception as e:
            logger.exception(e)
            return HttpResponseBadRequest('failed to generate report: ' + str(e))
    if request.method == 'GET':
        output_format = request.GET.get('outputFormat')
        if output_format not in ('pdf', 'xlsx'):
            return HttpResponseBadRequest('outputFormat parameter missing or invalid')
        key = request.GET.get('key')
        if not key:
            # in case there is a GET request without a key we expect all report data to be available.
            # this is NOT used by ReportBro Designer and only added for the sake of completeness.
            json_data = json.loads(request.body.decode('utf-8'))
            if not isinstance(json_data, dict) or not isinstance(json_data.get('report'), dict) or \
                    not isinstance(json_data.get('data'), dict) or not isinstance(json_data.get('isTestData'), bool):
                return HttpResponseBadRequest('invalid report values')
            report_definition = json_data.get('report')
            data = json_data.get('data')
            is_test_data = json_data.get('isTestData')
            if not isinstance(report_definition, dict) or not isinstance(data, dict):
                return HttpResponseBadRequest('report_definition or data missing')
            return FileResponse(
                io.BytesIO(
                    generate_report(
                        "preview",
                        report_definition,
                        data,
                        output_format,
                        is_test_data=is_test_data,
                    )
                ), filename=f"preview.{output_format}", as_attachment=False
            )
        try:
            with open(os.path.join(tempfile.gettempdir(), key), 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/pdf')
                response['Content-Disposition'] = 'inline; filename="report_preview.pdf"'
                return response
        except Exception as e:
            logger.exception(e)
            return HttpResponseBadRequest('failed to generate report: ' + str(e))
    return HttpResponseBadRequest('invalid request method')