# Canusia Class Visit Module Native Capabilities

*Last updated: 2026-07-22 · Reflects `package-class_visit` v0.0.9.*

This document outlines the native functionality supported by the Canusia Class Visit Module, as requested for review prior to providing institutional cost and time estimates. The features listed below are core to the platform and can be configured to meet institutional needs during implementation.

# Scheduling & Visit Management

The module provides a centralized system for scheduling and tracking classroom observation visits to concurrent-enrollment sections. It is designed around the way CE programs actually run site visits — with central oversight, delegated scheduling, and per-course assignment.

- **Flexible Scheduling Roles:** Visits can be scheduled centrally by CE office staff, by faculty course administrators for their own courses, or both.
- **Configurable Visit Types:** A program-defined list of visit types (e.g., Initial, Follow-up, Annual) is presented at scheduling time and recorded on each visit.
- **Multi-Section Visits:** A single visit can cover multiple class sections taught by the same instructor, reflecting real-world site visits that observe several periods in one trip.
- **Section Eligibility Controls:** The list of schedulable sections is filtered by section status (active, inactive, or all), and individual sections can be flagged as "visit not needed" to keep exempt or alternate-delivery sections off the unscheduled list.
- **Pre-Visit Notes:** Visitors can attach a private pre-visit note, visible only to the visiting team.

# Visit Reports

Each visit produces a structured report whose fields are fully defined by the institution.

| Feature | Native Capability |
| :-- | :-- |
| **Custom Report Fields** | Institution-defined fields with configurable label, input type (short text, paragraph, dropdown, checkbox, date), required flag, and dropdown options. Fields can be **targeted to specific visit types** (shown only for those types), and the configuration is **validated on save**. |
| **Public vs. Internal Fields** | Each field can be marked public (shared with the instructor and included in their downloadable report) or internal (visible only to CE/faculty). |
| **Draft & Submit Workflow** | Reports are saved as Draft while in progress and finalized as Submitted, with notifications firing only on submission. |
| **File Attachments** | Supporting files (photos, signed forms, handouts) can be attached to a report. |
| **Instructor Confirmation** | Optional one-click email link lets instructors confirm a scheduled visit date without logging in. |

# Notifications & Communication

Professional, configurable email communication keeps instructors and administrators informed at each stage.

- **Notification Points:** Configurable emails on (1) visit scheduled — to the instructor, (2) report submitted — to the instructor, (3) report submitted — to your office, and (4) report marked paid — to the visitor (when payment tracking is on).
- **Template Engine:** Each email has a configurable subject and message body utilizing shortcodes for dynamic data population (e.g., instructor name, visit date, visitors, class sections, type of visit, confirmation and report links).
- **Routing Options:** The internal "report submitted" notification can route automatically to each course's administrator or to a single shared inbox.
- **Automated Overdue Reminders:** Visitors with outstanding reports for past visits are reminded on a configurable repeating cadence (e.g., every 7 days) until the report is submitted.
- **Safe Activation Controls:** A master email switch supports On (live), Debug (redirect all mail to a test list for safe preview), and Off (suppress), so communications can be validated before go-live.

# Tracking & Payments

- **Visit Status Visibility:** Scheduled, pending, and completed visits are tracked per section and per instructor. The CE and faculty visit tables show a **Report Status** column, and — when payment tracking is on — a **Payment Status** column.
- **Payment Tracking:** Submitted reports can be marked **payment-processed** (individually or in bulk from the CE visits page), letting programs that pay a stipend or honorarium per visit track which visits have been paid out. When enabled, each **visitor can be automatically emailed when their report is marked paid** (configurable subject/message using the same shortcodes as the overdue-report reminder).

# Reporting & Compliance

Standardized reporting and exports ensure CE staff and compliance teams have the visibility they need.

- **Scheduled Visits Export:** All scheduled visits with sections, visitors, and report status.
- **Visit Reports Export:** Submitted reports with a column per configured report field.
- **Pending Visit Reports Export:** Past visits whose reports are missing or unsubmitted.
- **Unscheduled Classes Export:** Sections with no visit scheduled and not marked "not needed."
- **PDF Output:** Visit reports can be downloaded as a combined PDF — instructors and faculty receive public fields only; CE staff receive the full report.
- **Role-Based Access:** CE coordinators see all visits across the program, while faculty are scoped to their own courses.

# Portal Integration

Each role interacts with class visits through its existing Canusia portal — CE staff, faculty course administrators, and instructors each see the visits and reports relevant to them, with no separate login or system to maintain.
