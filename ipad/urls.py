from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.urls import include, path

from ipad.api_external_media import ExternalMediaView
from ipad.views import PolicyPageView

urlpatterns = [
    path(
        "api/ipad/external-media/<uuid:resourceid>/",
        ExternalMediaView.as_view(),
        name="ipad_external_media",
    ),
    path("privacy/", PolicyPageView.as_view(page_key="privacy"), name="privacy"),
    path("terms/", PolicyPageView.as_view(page_key="terms"), name="terms"),
    path(
        "accessibility/",
        PolicyPageView.as_view(page_key="accessibility"),
        name="accessibility",
    ),
    path("cookies/", PolicyPageView.as_view(page_key="cookies"), name="cookies"),
    path("", include("arches_controlled_lists.urls")),
    path("", include("arches_vue_components.urls")),
    path("", include("arches_modular_reports.urls")),
]

handler400 = "arches.app.views.main.custom_400"
handler403 = "arches.app.views.main.custom_403"
handler404 = "arches.app.views.main.custom_404"
handler500 = "arches.app.views.main.custom_500"

# Ensure Arches core urls are superseded by project-level urls
urlpatterns.append(path('', include('arches.urls')))

# Adds URL pattern to serve media files during development
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Only handle i18n routing in active project. This will still handle the routes provided by Arches core and Arches applications,
# but handling i18n routes in multiple places causes application errors.
if settings.ROOT_URLCONF == __name__:
    if settings.SHOW_LANGUAGE_SWITCH is True:
        urlpatterns = i18n_patterns(*urlpatterns)

    urlpatterns.append(path("i18n/", include("django.conf.urls.i18n")))
