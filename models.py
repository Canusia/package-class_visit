# Compatibility shim: allows ``from class_visit.models import …`` to work when
# the editable submodule layout (class_visit/class_visit/) is active on sys.path.
from class_visit.class_visit.models import *  # noqa: F401, F403
from class_visit.class_visit.models import (  # noqa: F401 — explicit for IDE / static analysis
    VisitSchedule,
    VisitReport,
    VisitReportFile,
    NotNeededVisit,
)
