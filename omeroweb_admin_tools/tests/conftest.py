from __future__ import annotations

import django
from django.conf import settings


if not settings.configured:
    settings.configure(
        SECRET_KEY="test-secret-key",
        DEFAULT_CHARSET="utf-8",
        ALLOWED_HOSTS=["testserver", "localhost"],
        USE_I18N=False,
        USE_TZ=True,
        INSTALLED_APPS=[],
        ROOT_URLCONF="omeroweb_admin_tools.tests._test_urls",
        SECURE=False,
    )
    django.setup()
