"""Read-only Place External Media presentation API."""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.views.generic import View

from arches.app.models.models import ResourceInstance
from arches.app.utils.permission_backend import user_can_read_resource
from arches.app.utils.response import JSONResponse

from ipad.external_media import (
    ExternalMediaConfigError,
    PLACE_SLUG,
    list_place_drive_pdfs,
    source_graph,
)


class ExternalMediaView(View):
    def dispatch(self, request, *args, **kwargs):
        resourceid = kwargs.get("resourceid")
        try:
            allowed = user_can_read_resource(request.user, resourceid=resourceid)
        except ResourceInstance.DoesNotExist:
            raise Http404()
        if not allowed:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, resourceid):
        try:
            place = ResourceInstance.objects.get(pk=resourceid)
        except (ResourceInstance.DoesNotExist, ValueError, TypeError):
            raise Http404()

        try:
            place_graph = source_graph(PLACE_SLUG)
        except ExternalMediaConfigError as exc:
            return JSONResponse({"message": str(exc)}, status=500)

        if place.graph_id != place_graph.graphid:
            raise Http404()

        try:
            items = list_place_drive_pdfs(place)
        except ExternalMediaConfigError as exc:
            return JSONResponse({"message": str(exc)}, status=500)

        visible = [
            item
            for item in items
            if user_can_read_resource(request.user, resourceid=item["resource_id"])
        ]
        return JSONResponse({"items": visible})
