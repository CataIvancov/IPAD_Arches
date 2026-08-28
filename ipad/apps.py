from django.apps import AppConfig


class IpadConfig(AppConfig):
    name = "ipad"
    is_arches_application = True

    def ready(self):
        from arches.app.views.resource import ResourceReportView
        from arches.app.views.search import SearchView

        from ipad.knockout_basemaps import inject_settings_basemaps

        self._patch_map_context(SearchView, inject_settings_basemaps)
        self._patch_map_context(ResourceReportView, inject_settings_basemaps)

    @staticmethod
    def _patch_map_context(view_cls, inject):
        original = view_cls.get_context_data
        if getattr(original, "_ipad_settings_basemaps", False):
            return

        def get_context_data(self, **kwargs):
            context = original(self, **kwargs)
            return inject(context)

        get_context_data._ipad_settings_basemaps = True
        view_cls.get_context_data = get_context_data

