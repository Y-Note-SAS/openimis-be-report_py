from django.db import migrations


def assign_updated_report_permissions(apps, schema_editor):
    RoleRight = apps.get_model('core', 'RoleRight')
    Role = apps.get_model('core', 'Role')
    role_ids = RoleRight.objects.filter(right_id=131200).values_list('role__id', flat=True)

    relevant_roles = Role.objects\
        .filter(id__in=role_ids)\
        .filter(validity_to__isnull=True)\
        .all()

    new_perms = [131201, 131202, 131203]
    for role in relevant_roles:
        new_rights = [RoleRight(role=role, right_id=right, audit_user_id=None) for right in new_perms]
        RoleRight.objects.bulk_create(new_rights)


class Migration(migrations.Migration):

    dependencies = [
        ('report', '0002_auto_20220308_1414'),
    ]

    operations = [
        migrations.RunPython(assign_updated_report_permissions),
    ]
