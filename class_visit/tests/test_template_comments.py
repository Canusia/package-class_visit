"""No multi-line `{# ... #}` comments in this package's templates.

Django's `{# #}` is single-line only. Spanning two lines leaks the comment
text into the rendered page, and if a `{% %}` tag sits inside it the template
fails to compile outright ("Unclosed tag ... looking for endblock"). Use
`{% comment %}` for anything longer than a line.
"""
import os
import re

from django.test import SimpleTestCase

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')


def _template_files():
    for root, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if name.endswith('.html'):
                yield os.path.join(root, name)


class TemplateCommentStyleTest(SimpleTestCase):
    def test_no_unterminated_single_line_comments(self):
        offenders = []
        for path in _template_files():
            with open(path, encoding='utf-8') as fh:
                for lineno, line in enumerate(fh, start=1):
                    # a `{#` with no `#}` after it on the same line
                    for match in re.finditer(r'\{#', line):
                        if '#}' not in line[match.end():]:
                            rel = os.path.relpath(path, TEMPLATES_DIR)
                            offenders.append(f'{rel}:{lineno}: {line.strip()}')
        self.assertEqual(
            offenders, [],
            'multi-line {# #} comments leak into the page — use '
            '{% comment %}:\n' + '\n'.join(offenders))
