from django.shortcuts import render
from django.utils.translation import gettext as _
from arches.app.views.base import BaseManagerView


POLICY_PAGES = {
    "privacy": {
        "template": "pages/privacy.htm",
        "title": "Privacy policy",
        "icon": "fa fa-lock",
    },
    "terms": {
        "template": "pages/terms.htm",
        "title": "Terms & conditions",
        "icon": "fa fa-file-text-o",
    },
    "accessibility": {
        "template": "pages/accessibility.htm",
        "title": "Accessibility",
        "icon": "fa fa-universal-access",
    },
    "cookies": {
        "template": "pages/cookies.htm",
        "title": "Cookies",
        "icon": "fa fa-info-circle",
    },
}


class PolicyPageView(BaseManagerView):
    """Public policy pages in the Arches manager chrome. No new webpack entry."""

    page_key = "privacy"

    def get(self, request, *args, **kwargs):
        meta = POLICY_PAGES[self.page_key]
        context = self.get_context_data()
        context["main_script"] = None
        context["nav"]["icon"] = meta["icon"]
        context["nav"]["title"] = _(meta["title"])
        context["nav"]["help"] = ""
        context["policy_page"] = self.page_key
        context["policy_title"] = _(meta["title"])
        context["body_class"] = "ipad-policy-page"
        return render(request, meta["template"], context)
