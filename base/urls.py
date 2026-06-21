from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path(
        "anonymous-drawing-in-masbate-online/",
        views.anonymous_drawing_masbate_online,
        name="anonymous_drawing_masbate_online",
    ),
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("account/", views.account_dashboard, name="account_dashboard"),
    path("account/drawings/", views.my_drawings_view, name="my_drawings"),
    path("account/drawings/claim/", views.claim_drawing_view, name="claim_drawing"),
    path("account/profile-picture/", views.account_profile_picture_view, name="account_profile_picture"),
    path("draw/start/", views.start_drawing, name="start_drawing"),
    path("draw/<uuid:public_id>/", views.drawing_detail, name="drawing_detail"),
    path("draw/<uuid:public_id>/save/", views.save_drawing, name="save_drawing"),
    path("draw/<uuid:public_id>/publish/", views.publish_drawing, name="publish_drawing"),
    path("recover/", views.recover_drawing, name="recover_drawing"),
    path("showcase/", views.showcase, name="showcase"),
    path("showcase/<uuid:public_id>/", views.showcase_detail, name="showcase_detail"),
    path("showcase/<uuid:public_id>/heart/", views.toggle_drawing_heart, name="toggle_drawing_heart"),
    path("showcase/<uuid:public_id>/comments/", views.create_drawing_comment, name="create_drawing_comment"),
    path("comments/<int:comment_id>/delete/", views.delete_drawing_comment, name="delete_drawing_comment"),
    path("about/", views.about, name="about"),
    path("faq/", views.faq, name="faq"),
    path("privacy-policy/", views.privacy_policy, name="privacy_policy"),
    path("terms/", views.terms, name="terms"),
]
