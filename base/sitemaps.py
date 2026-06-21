from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import DrawingProject


class StaticViewSitemap(Sitemap):
    protocol = "https"

    def items(self):
        return [
            "home",
            "anonymous_drawing_masbate_online",
            "showcase",
            "about",
            "faq",
            "privacy_policy",
            "terms",
        ]

    def changefreq(self, item):
        if item == "home":
            return "daily"
        if item in ("anonymous_drawing_masbate_online", "showcase"):
            return "weekly"
        if item in ("about", "faq"):
            return "monthly"
        return "yearly"

    def priority(self, item):
        if item == "home":
            return 1.0
        if item == "anonymous_drawing_masbate_online":
            return 0.9
        if item == "showcase":
            return 0.8
        if item in ("about", "faq"):
            return 0.7
        return 0.5

    def location(self, item):
        return reverse(item)


class PublishedDrawingSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6
    protocol = "https"

    def items(self):
        return DrawingProject.objects.filter(is_published=True).order_by("-updated_at")

    def lastmod(self, item):
        return item.updated_at

    def location(self, item):
        return reverse("showcase_detail", args=[item.public_id])
