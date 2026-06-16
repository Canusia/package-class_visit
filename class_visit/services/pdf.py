"""
PDF generation for class visit letters using pdfkit + wkhtmltopdf.

Design mirrors Student.as_pdf in cis/models/student.py:
- _build_letter_html(report, public_only) → inner body HTML string (no pdfkit, testable)
- visit_letter_pdf(report, public_only) → bytes  (wraps in cis/print_base.html, single pdfkit call)
- visit_letters_pdf(reports, public_only) → bytes (concat inner HTML, one pdfkit call, page-breaks between)

The public-facing PDF includes only report fields marked public=True.
The internal PDF includes all fields.
"""
import pdfkit

from django.template.loader import get_template

from class_visit.class_visit.services.report_fields import report_values_for_display


def _build_letter_html(visit_report, public_only: bool = False) -> str:
    """
    Render the inner body HTML for one visit letter.

    Uses the template ``class_visit/letter_body.html`` with context:
      - report: the VisitReport instance
      - visit: the VisitSchedule instance (visit_report.visit_schedule)
      - rows: output of report_values_for_display(visit_report, public_only)

    This function is intentionally thin and directly testable without pdfkit.
    """
    visit = visit_report.visit_schedule
    teacher = visit.teacher
    rows = report_values_for_display(visit_report, public_only=public_only)
    body = get_template('class_visit/letter_body.html').render({
        'report': visit_report,
        'visit': visit,
        'teacher_first_name': teacher.user.first_name if teacher else '',
        'teacher_last_name': teacher.user.last_name if teacher else '',
        'visit_date': visit.visit_date_sexy,
        'type_of_visit': visit.type_of_visit,
        'class_sections_sexy': visit.class_sections_sexy,
        'rows': rows,
    })
    return body


def visit_letter_pdf(visit_report, public_only: bool = False) -> bytes:
    """
    Generate and return a PDF visit letter for a single report as bytes.

    Wraps the inner letter body in ``cis/print_base.html`` (same pattern as
    Student.as_pdf) and calls pdfkit once.

    Args:
        visit_report: VisitReport instance.
        public_only: if True, only include fields marked public=True in settings.

    Returns:
        bytes — the raw PDF content (suitable for HttpResponse).

    Requires wkhtmltopdf to be installed in the Docker container.
    """
    html = _build_letter_html(visit_report, public_only=public_only)
    html = get_template('cis/print_base.html').render({'main_content': html})
    return pdfkit.from_string(html, False, {'page-size': 'Letter'})


def visit_letters_pdf(visit_reports, public_only: bool = False) -> bytes:
    """
    Combine MANY visit letters into ONE PDF.

    Concatenates each report's inner HTML with a page-break separator, wraps
    the whole thing once in ``cis/print_base.html``, then makes a single
    pdfkit call.  No zipfile, no pypdf.

    Args:
        visit_reports: iterable of VisitReport instances.
        public_only: passed through to _build_letter_html for each report.

    Returns:
        bytes — the raw combined PDF content (suitable for HttpResponse).
    """
    bodies = []
    for report in visit_reports:
        bodies.append(_build_letter_html(report, public_only=public_only))
    combined = '<div style="page-break-after: always;"></div>'.join(bodies)
    html = get_template('cis/print_base.html').render({'main_content': combined})
    return pdfkit.from_string(html, False, {'page-size': 'Letter'})
