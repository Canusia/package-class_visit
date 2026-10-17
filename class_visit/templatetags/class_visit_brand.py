"""Campus branding tags that also load on a cis without them (issue #20).

``{% load brand %}`` cannot be made conditional, and a cis older than
package-cis #61 has no ``brand`` library, so those templates failed with
``TemplateSyntaxError``. Templates load this library instead: it passes
through to ``cis.templatetags.brand`` when it exists, and otherwise registers
the same tags returning nothing. Named ``class_visit_brand``, not ``brand``,
since two libraries with one name trigger ``templates.E003``.
"""
from django import template

from ..compat import has_module

if has_module('cis.templatetags.brand'):
    from cis.templatetags.brand import register  # noqa: F401
else:
    register = template.Library()

    @register.simple_tag
    def brand():
        return ''

    @register.simple_tag
    def brand_logo_url():
        return ''

    @register.simple_tag
    def brand_background_url():
        return ''

    @register.simple_tag
    def brand_css():
        return ''
