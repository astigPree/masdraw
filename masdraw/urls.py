"""
URL configuration for masdraw project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from base.sitemaps import PublishedDrawingSitemap, StaticViewSitemap
from base.views import clean_sitemap, favicon, robots_txt


sitemaps = {
    "static": StaticViewSitemap,
    "drawings": PublishedDrawingSitemap,
}

urlpatterns = [
    path('3/admin/', admin.site.urls),
    path("favicon.ico", favicon, name="favicon"),
    path('', include('base.urls')),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("sitemap.xml", clean_sitemap, {"sitemaps": sitemaps}, name="sitemap"),
]
