import io
import json

from django.core.exceptions import ObjectDoesNotExist
from django.contrib.staticfiles import finders
from django.db import connection
from django.db.models import Q
from django.http import FileResponse
from reportbro import Report, ReportBroError
from .models import ReportDefinition
from .default_report import default_report
from django.core.serializers.json import DjangoJSONEncoder
import logging
logger = logging.getLogger(__name__)


def get_report_definition(report_name, default, report_date=None):
    """
    Retrieves the report definition, either the default one (as parameter) or the overridden definition
    :param report_name: name of the report to fetch, no module yet
    :param default: default template
    :param report_date: date for which we're running the report, for the definition validity
    :return:
    """
    if not report_date:
        from core import datetime

        report_date = datetime.datetime.now()
    try:
        r = ReportDefinition.objects.get(
            Q(name=report_name)
            & (Q(validity_to__isnull=True) | Q(validity_to__gte=report_date))
        ).definition
    except ObjectDoesNotExist:
        if default:
            r = default
        else:
            r = default_report
    return r


def run_stored_proc_report(stored_procedure_name, *args, **kwargs):
    """
    Used to run uspSSRS* stored procedures
    :param stored_procedure_name: For example "usbSSRSEnroledFamilies"
    :param args: Unused, don't pass unnamed parameters
    :param kwargs: All parameters to pass to the stored procedure
    :return: a list of dict with the results from the stored procedure
    """
    with connection.cursor() as cur:
        sql_params = []
        params = []
        for k, v in kwargs.items():
            sql_params.append(f"@{k} = %s")
            params.append(v)
        sql = f"EXEC [{stored_procedure_name}] {', '.join(sql_params)}"

        cur.execute(sql, params)
        res = _dictfetchall(cur)
        return res


def _dictfetchall(cursor):
    """Return all rows from a cursor as a dict, from Django documentation"""
    columns = [col[0] for col in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def generate_report(report_name, definition, data, report_format="pdf", local_file='', is_test_data=None):
    """
    Generate a PDF/XLSX report.
    :param report_name: Name of the report, only used for error reporting
    :param definition: Report definition, either a dict or a JSON string
    :param data: Data to pass to the report
    :param report_format: pdf or xlsx
    :param local_file: Leave out to get a response that will be included into a HTTP response, otherwise a local file where the report will be saved (for preview)
    :param is_test_data: If True, the report will be generated with test data
    :return: A FileResponse or None if local_file is set
    """
    try:
        r = Report(definition if isinstance(definition, dict) else json.loads(definition), data,
                   additional_fonts=[
                       dict(
                           value='firefly', filename=finders.find("report/reportbro/fonts/fireflysung.ttf")
                       ),
                       dict(
                           value='dejavusans',
                           filename=finders.find('report/reportbro/fonts/DejaVuSans.ttf'),
                           bold_filename=finders.find('report/reportbro/fonts/DejaVuSans-Bold.ttf'),
                           italic_filename=finders.find('report/reportbro/fonts/DejaVuSans-Oblique.ttf'),
                           bold_italic_filename=finders.find('report/reportbro/fonts/DejaVuSans-BoldOblique.ttf'),
                       ),
                       dict(
                           value='notosans',
                           filename=finders.find('report/reportbro/fonts/NotoSans-Regular.ttf'),
                           bold_filename=finders.find('report/reportbro/fonts/NotoSans-Bold.ttf'),
                           italic_filename=finders.find('report/reportbro/fonts/NotoSans-Italic.ttf'),
                           bold_italic_filename=finders.find('report/reportbro/fonts/NotoSans-BoldItalique.ttf'),
                       ),
                       dict(
                           value='notosans-myanmar',
                           filename=finders.find('report/reportbro/fonts/NotoSansMyanmar-Regular.ttf'),
                           bold_filename=finders.find('report/reportbro/fonts/NotoSansMyanmar-Bold.ttf'),
                       ),
                       dict(
                           value='notosans-arabic',
                           filename=finders.find('report/reportbro/fonts/NotoSansArabic.ttf'),
                       ),
                       dict(
                           value='notosans-naskh-arabic',
                           filename=finders.find('report/reportbro/fonts/NotoNaskhArabic.ttf'),
                       ),
                       dict(
                           value='notosans-ethiopic',
                           filename=finders.find('report/reportbro/fonts/NotoSansEthiopic.ttf'),
                       ),
                       dict(
                           value='freesans',
                           filename=finders.find('report/reportbro/fonts/FreeSans.ttf'),
                           bold_filename=finders.find('report/reportbro/fonts/FreeSansBold.ttf'),
                           italic_filename=finders.find('report/reportbro/fonts/FreeSansOblique.ttf'),
                           bold_italic_filename=finders.find('report/reportbro/fonts/FreeSansBoldOblique.ttf'),
                       ),
                       dict(
                           value="unifont",
                           filename=finders.find("report/reportbro/fonts/unifont.ttf"),
                       ),
                   ],
                   encode_error_handling="strict",
                   is_test_data=is_test_data,
                   #core_fonts_encoding="utf-8",
                   )
    except Exception as e:
        logger.exception(f"Error loading report definition {report_name}")
        raise ReportBroError(str(e))
    if r.errors:
        logger.error(f"Error generating report {report_name}: {r.errors[0]}")
        raise ReportBroError(r.errors[0])

    if report_format == "pdf":
        try:
            generated_report = r.generate_pdf(filename=local_file)
        except Exception as e:
            logger.exception(f"Error generating PDF report {report_name}")
            raise ReportBroError(str(e))
    elif report_format == "xlsx":
        try:
            generated_report = r.generate_xlsx(filename=local_file)
        except Exception as e:
            logger.exception(f"Error generating XLSX report {report_name}")
            raise ReportBroError(str(e))
    else:
        raise Exception("unknown report format")
    return generated_report


class ReportService(object):
    def __init__(self, user):
        self.user = user

    def process(self, report, data, default=None, filename=None, report_format="pdf"):
        try:
            r = ReportDefinition.objects.get(name=report).definition
        except ObjectDoesNotExist:
            if default:
                r = default
            else:
                r = default_report
                data = {
                    "report_name": report,
                    "data_dump": json.dumps(data, cls=DjangoJSONEncoder),
                }

        r = Report(json.loads(r), data)
        fname = filename if filename else f"{report}.{report_format}"
        if r.errors:
            raise ReportBroError(r.errors[0])

        if report_format == "pdf":
            generated_report = r.generate_pdf()
        elif report_format == "xlsx":
            generated_report = r.generate_xlsx()
        else:
            raise Exception("unknown report format")
        return FileResponse(
            io.BytesIO(generated_report), filename=fname, as_attachment=False
        )
