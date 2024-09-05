# Generated by Django 3.2.17 on 2023-03-01 15:02
import logging

from django.db import migrations

from core.utils import insert_role_right_for_system

logger = logging.getLogger(__name__)

ENROLMENT_OFFICER_ROLE_IS_SYSTEM = 1
ROLE_RIGHT_ID = 131201


def add_rights(apps, schema_editor):
    """
    Add reports_primary_operational_indicator_policies permission to the Enrolment Officer.
    """
    insert_role_right_for_system(ENROLMENT_OFFICER_ROLE_IS_SYSTEM, ROLE_RIGHT_ID, apps)


class Migration(migrations.Migration):
    dependencies = [
        ('report', '0004_generatedreports'),
    ]

    operations = [
        migrations.RunPython(add_rights, migrations.RunPython.noop),
    ]
