"""
Send pending visit-report reminder emails to visitors.

For each past VisitSchedule whose report is missing or not yet Submitted,
and where reminder_every_days have elapsed since the last reminder (or no
reminder has been sent), emails each visitor asking them to submit their report.

Usage:
    python manage.py send_visit_report_reminders
    python manage.py send_visit_report_reminders -t "2024-01-15 07:00:00"
"""
import json
import logging

from django.core.management.base import BaseCommand

from cis.signals.crontab import cron_task_done, cron_task_started
from class_visit.class_visit.models import VisitSchedule

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send pending visit-report reminder emails to class-visit visitors'

    def add_arguments(self, parser):
        parser.add_argument(
            '-t', '--time',
            type=str,
            help='Scheduled time of run (YYYY-MM-DD HH:MM:SS)',
        )

    def handle(self, *args, **kwargs):
        summary = ''
        detailed_log = {}

        scheduled_time = kwargs.get('time')
        if scheduled_time:
            cron_task_started.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=scheduled_time,
            )

        summary, detailed_log = VisitSchedule.send_pending_report_reminders()

        self.stdout.write(self.style.SUCCESS(summary))

        if scheduled_time:
            cron_task_done.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=scheduled_time,
                summary=summary,
                detailed_log=json.dumps(detailed_log),
            )
