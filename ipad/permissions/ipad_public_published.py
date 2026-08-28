"""Default-deny permissions with Guest read on published resource graphs.

Arches 8.1 PERMISSION_DEFAULTS is keyed by graphid and does not support
nodegroup defaults. Listing current published graphids in settings covers
today's models; this subclass also grants Guest view_resourceinstance
when a resource's graph is published later, so new publications become
public without editing settings (search still needs an ES reindex).
Arches System Settings is never treated as public.
"""

from django.contrib.auth.models import Group

from arches.app.models.models import GraphModel
from arches.app.models.system_settings import settings
from arches.app.permissions.arches_default_deny import (
    ArchesDefaultDenyPermissionFramework,
)


class IpadPublicPublishedPermissionFramework(ArchesDefaultDenyPermissionFramework):
    def get_all_default_permissions(self, model=None):
        defaults = super().get_all_default_permissions(model)
        if defaults:
            return defaults
        if model is None or not getattr(model, "graph_id", None):
            return []

        graph_id = str(model.graph_id)
        if graph_id == str(settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID):
            return []

        is_public = GraphModel.objects.filter(
            pk=graph_id,
            isresource=True,
            publication_id__isnull=False,
            source_identifier_id__isnull=True,
        ).exists()
        if not is_public:
            return []

        try:
            guest = Group.objects.get(name="Guest")
        except Group.DoesNotExist:
            return []

        return [
            {
                "id": str(guest.id),
                "type": "group",
                "permissions": ["view_resourceinstance"],
            }
        ]
