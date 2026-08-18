"""No test module may hardcode the nested `class_visit.class_visit` path.

The suite ships inside the wheel and runs in two deployment shapes: the
in-tree editable submodule, where this package imports as
`class_visit.class_visit`, and a pip-only tenant, where it is flat. A module
that spells either prefix out fails to import in the other layout — and when
that module is `tests/__init__.py`, it takes every test in the package down
with it, which is what ewu#62 reported.

Use a relative import, or `PKG` from this package's `__init__` where a string
is required.
"""
import os
import re

from django.test import SimpleTestCase

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
# Only a *leading* class_visit.class_visit is wrong. The settings module is
# genuinely `class_visit.settings.class_visit.class_visit` (a class named
# after its module), so the pattern requires no preceding dotted segment.
NESTED_PREFIX = re.compile(r'(?<![\w.])class_visit\.class_visit(?![\w])')
# The resolver itself names both layouts; that is its job.
EXEMPT = {'__init__.py', os.path.basename(__file__)}


class NoHardcodedPackagePrefixTests(SimpleTestCase):

    def test_no_test_module_spells_out_the_nested_prefix(self):
        offenders = []
        for name in sorted(os.listdir(TESTS_DIR)):
            if not name.endswith('.py') or name in EXEMPT:
                continue
            with open(os.path.join(TESTS_DIR, name), encoding='utf-8') as fh:
                for lineno, line in enumerate(fh, 1):
                    if NESTED_PREFIX.search(line):
                        offenders.append(f'{name}:{lineno}: {line.strip()}')
        self.assertEqual(offenders, [], '\n'.join(offenders))
