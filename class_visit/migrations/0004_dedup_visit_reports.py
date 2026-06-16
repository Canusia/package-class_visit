from django.db import migrations


def dedup_visit_reports(apps, schema_editor):
    """
    For each VisitSchedule that has more than one VisitReport, keep the
    most recently created one (highest createdon) and delete the rest.
    """
    VisitReport = apps.get_model('class_visit', 'VisitReport')
    # Find visit_schedule ids with multiple reports
    from django.db.models import Count
    dupes = (
        VisitReport.objects.values('visit_schedule')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
    )
    for dup in dupes:
        vs_id = dup['visit_schedule']
        reports = VisitReport.objects.filter(
            visit_schedule_id=vs_id
        ).order_by('-createdon')
        # Keep the first (most recent); delete the rest
        to_delete = reports[1:]
        for r in to_delete:
            r.delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('class_visit', '0003_add_type_of_visit'),
    ]

    operations = [
        migrations.RunPython(dedup_visit_reports, noop),
    ]
