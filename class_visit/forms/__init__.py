"""Form package for class_visit.

The CE and faculty forms live in `forms/ce.py` and `forms/faculty.py`; import
from those modules directly.

This file used to hold a legacy `VisitScheduleForm` / `VisitReportForm` pair that
no view imported. They were the only code that created `VisitReportFile`, which
is why attachments were "advertised but unreachable" (#9 part B) -- the live
report form has no file input. Attachment upload is being added properly in #14;
the legacy pair was deleted rather than revived.
"""
