from datetime import timedelta

from django.contrib.auth import get_user, get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AnonymousDrawingSession, DrawingComment, DrawingHeart, DrawingProject, UserProfile
from .admin import (
    feature_selected_drawings,
    hide_selected_comments,
    publish_selected_drawings,
    unfeature_selected_drawings,
    unhide_selected_comments,
    unpublish_selected_drawings,
)
from .views import BROWSER_COOKIE_NAME


class SeoAndPublishFlowTests(TestCase):
    def test_landing_page_loads(self):
        response = self.client.get(reverse("anonymous_drawing_masbate_online"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anonymous Drawing in Masbate Online")

    def test_sitemap_lists_public_static_and_published_drawing_urls(self):
        drawing_session = AnonymousDrawingSession(browser_token="browser-token")
        drawing_session.set_pass_key("secret-pass-key")
        drawing_session.save()
        published_project = DrawingProject.objects.create(
            session=drawing_session,
            title="Masbate Rodeo Sunset",
            preview_image="data:image/png;base64,test",
            is_published=True,
        )
        private_project = DrawingProject.objects.create(
            session=drawing_session,
            title="Private Draft",
            preview_image="data:image/png;base64,test",
            is_published=False,
        )

        response = self.client.get(reverse("sitemap"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/xml")
        self.assertNotIn("X-Robots-Tag", response.headers)
        self.assertContains(response, "<loc>https://masdraw.masbate.top/</loc>", html=False)
        self.assertContains(response, reverse("showcase_detail", args=[published_project.public_id]))
        self.assertNotContains(response, reverse("showcase_detail", args=[private_project.public_id]))

    def test_robots_points_to_primary_domain_sitemap(self):
        response = self.client.get(reverse("robots_txt"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Sitemap: https://masdraw.masbate.top/sitemap.xml",
            html=False,
        )

    def test_favicon_is_served_from_stable_root_url(self):
        response = self.client.get(reverse("favicon"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/x-icon")
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x00\x00\x01\x00"))

    def test_publish_requires_non_empty_title(self):
        drawing_session = AnonymousDrawingSession(browser_token="browser-token")
        drawing_session.set_pass_key("secret-pass-key")
        drawing_session.save()
        project = DrawingProject.objects.create(
            session=drawing_session,
            title="   ",
            preview_image="data:image/png;base64,test",
        )

        response = self.client.post(reverse("publish_drawing", args=[project.public_id]))

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {"ok": False, "error": "Add a title before publishing your drawing."},
        )

    def test_publish_succeeds_with_title_and_preview(self):
        drawing_session = AnonymousDrawingSession(browser_token="browser-token")
        drawing_session.set_pass_key("secret-pass-key")
        drawing_session.save()
        project = DrawingProject.objects.create(
            session=drawing_session,
            title="Masbate Rodeo Sunset",
            preview_image="data:image/png;base64,test",
        )

        response = self.client.post(reverse("publish_drawing", args=[project.public_id]))

        project.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(project.is_published)


class AccountAuthFlowTests(TestCase):
    ajax_headers = {
        "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
        "HTTP_ACCEPT": "application/json",
    }

    def test_register_creates_user_logs_in_and_redirects_to_account(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "phase2user",
                "password1": "StrongPass-2026!",
                "password2": "StrongPass-2026!",
            },
        )

        self.assertRedirects(response, reverse("account_dashboard"))
        self.assertTrue(get_user_model().objects.filter(username="phase2user").exists())
        self.assertTrue(get_user(self.client).is_authenticated)

    def test_login_respects_next_parameter(self):
        get_user_model().objects.create_user(
            username="phase2user",
            password="StrongPass-2026!",
        )

        response = self.client.post(
            f"{reverse('login')}?next={reverse('account_dashboard')}",
            {
                "username": "phase2user",
                "password": "StrongPass-2026!",
            },
        )

        self.assertRedirects(response, reverse("account_dashboard"))
        self.assertTrue(get_user(self.client).is_authenticated)

    def test_account_dashboard_requires_login(self):
        response = self.client.get(reverse("account_dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('account_dashboard')}",
            fetch_redirect_response=False,
        )

    def test_logged_in_user_can_access_account_dashboard(self):
        user = get_user_model().objects.create_user(
            username="phase2user",
            password="StrongPass-2026!",
        )
        drawing_session = AnonymousDrawingSession(browser_token="dashboard-token")
        drawing_session.set_pass_key("dashboard-key")
        drawing_session.save()
        DrawingProject.objects.create(
            session=drawing_session,
            owner=user,
            title="Dashboard Published Drawing",
            is_published=True,
            published_at=timezone.now(),
            heart_count=4,
            comment_count=2,
        )
        DrawingProject.objects.create(
            session=drawing_session,
            owner=user,
            title="Dashboard Private Drawing",
            heart_count=1,
            comment_count=0,
        )
        self.client.login(username="phase2user", password="StrongPass-2026!")

        response = self.client.get(reverse("account_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome, phase2user.")
        self.assertContains(response, "Total claimed")
        self.assertContains(response, "Published")
        self.assertContains(response, "Private")
        self.assertContains(response, "Total hearts")
        self.assertContains(response, "Total comments")
        self.assertContains(response, "Dashboard Published Drawing")
        self.assertContains(response, "Dashboard Private Drawing")
        self.assertContains(response, "Open My Drawings")
        self.assertContains(response, "Claim With Key")
        self.assertContains(response, "Open Canvas")
        self.assertContains(response, "/account/drawings/")
        self.assertContains(response, "/account/drawings/claim/")

    def test_logout_logs_out_and_redirects_home(self):
        get_user_model().objects.create_user(
            username="phase2user",
            password="StrongPass-2026!",
        )
        self.client.login(username="phase2user", password="StrongPass-2026!")

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("home"))
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_login_popup_returns_form_html(self):
        response = self.client.get(reverse("login"), **self.ajax_headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["title"], "Login")
        self.assertIn('data-auth-form="login"', payload["html"])

    def test_register_popup_creates_user_without_redirect(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "popupuser",
                "password1": "StrongPass-2026!",
                "password2": "StrongPass-2026!",
            },
            **self.ajax_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["username"], "popupuser")
        self.assertEqual(payload["account_url"], reverse("account_dashboard"))
        self.assertTrue(get_user(self.client).is_authenticated)

    def test_invalid_login_popup_returns_form_errors_without_redirect(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "missing",
                "password": "wrong",
            },
            **self.ajax_headers,
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["title"], "Login")
        self.assertIn('data-auth-form="login"', payload["html"])

    def test_logout_popup_returns_json_without_redirect(self):
        get_user_model().objects.create_user(
            username="phase2user",
            password="StrongPass-2026!",
        )
        self.client.login(username="phase2user", password="StrongPass-2026!")

        response = self.client.post(reverse("logout"), **self.ajax_headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["authenticated"])
        self.assertEqual(payload["login_url"], reverse("login"))
        self.assertFalse(get_user(self.client).is_authenticated)


class ClaimDrawingFlowTests(TestCase):
    recovery_key = "phase-2-recovery-key"

    def setUp(self):
        cache.clear()

    def create_session(self, recovery_key=None):
        drawing_session = AnonymousDrawingSession(browser_token="claim-browser-token")
        drawing_session.set_pass_key(recovery_key or self.recovery_key)
        drawing_session.save()
        return drawing_session

    def create_user(self, username="claimuser"):
        return get_user_model().objects.create_user(
            username=username,
            password="StrongPass-2026!",
        )

    def test_claim_page_requires_login(self):
        response = self.client.get(reverse("claim_drawing"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('claim_drawing')}",
            fetch_redirect_response=False,
        )

    def test_logged_in_user_can_open_claim_page(self):
        user = self.create_user()
        self.client.force_login(user)

        response = self.client.get(reverse("claim_drawing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Claim Drawing")
        self.assertContains(response, 'name="recovery_key"')

    def test_valid_recovery_key_claims_unowned_drawing(self):
        user = self.create_user()
        drawing_session = self.create_session()
        project = DrawingProject.objects.create(session=drawing_session, title="Claim me")
        self.client.force_login(user)

        response = self.client.post(
            reverse("claim_drawing"),
            {"recovery_key": self.recovery_key},
        )

        project.refresh_from_db()
        self.assertRedirects(response, reverse("my_drawings"))
        self.assertEqual(project.owner, user)
        self.assertIsNotNone(project.claimed_at)
        self.assertNotEqual(drawing_session.pass_key_hash, self.recovery_key)

    def test_one_recovery_key_claims_all_unowned_drawings_in_session(self):
        user = self.create_user()
        drawing_session = self.create_session()
        first_project = DrawingProject.objects.create(session=drawing_session, title="First")
        second_project = DrawingProject.objects.create(session=drawing_session, title="Second")
        self.client.force_login(user)

        response = self.client.post(
            reverse("claim_drawing"),
            {"recovery_key": self.recovery_key},
        )

        first_project.refresh_from_db()
        second_project.refresh_from_db()
        self.assertRedirects(response, reverse("my_drawings"))
        self.assertEqual(first_project.owner, user)
        self.assertEqual(second_project.owner, user)
        self.assertIsNotNone(first_project.claimed_at)
        self.assertIsNotNone(second_project.claimed_at)

    def test_same_user_gets_friendly_already_claimed_message(self):
        user = self.create_user()
        drawing_session = self.create_session()
        DrawingProject.objects.create(
            session=drawing_session,
            title="Already mine",
            owner=user,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("claim_drawing"),
            {"recovery_key": self.recovery_key},
            follow=True,
        )

        self.assertRedirects(response, reverse("my_drawings"))
        self.assertContains(response, "This drawing is already claimed by your account.")

    def test_different_user_cannot_steal_claimed_drawing(self):
        owner = self.create_user(username="owner")
        attacker = self.create_user(username="attacker")
        drawing_session = self.create_session()
        project = DrawingProject.objects.create(
            session=drawing_session,
            title="Already owned",
            owner=owner,
        )
        self.client.force_login(attacker)

        response = self.client.post(
            reverse("claim_drawing"),
            {"recovery_key": self.recovery_key},
            follow=True,
        )

        project.refresh_from_db()
        self.assertRedirects(response, reverse("my_drawings"))
        self.assertEqual(project.owner, owner)
        self.assertContains(
            response,
            "Some drawings could not be claimed because they already belong to another account.",
        )

    def test_empty_recovery_key_shows_error(self):
        user = self.create_user()
        self.client.force_login(user)

        response = self.client.post(reverse("claim_drawing"), {"recovery_key": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recovery key is required.")

    def test_invalid_recovery_key_shows_error(self):
        user = self.create_user()
        self.create_session()
        self.client.force_login(user)

        response = self.client.post(
            reverse("claim_drawing"),
            {"recovery_key": "wrong-key"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid recovery key.")

    def test_valid_recovery_key_with_no_drawings_shows_error(self):
        user = self.create_user()
        self.create_session()
        self.client.force_login(user)

        response = self.client.post(
            reverse("claim_drawing"),
            {"recovery_key": self.recovery_key},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No drawings found for this recovery key.")


class MyDrawingsFlowTests(TestCase):
    def create_user(self, username="drawingsuser"):
        return get_user_model().objects.create_user(
            username=username,
            password="StrongPass-2026!",
        )

    def create_session(self, key="my-drawings-key"):
        drawing_session = AnonymousDrawingSession(browser_token=f"{key}-browser")
        drawing_session.set_pass_key(key)
        drawing_session.save()
        return drawing_session

    def test_my_drawings_requires_login(self):
        response = self.client.get(reverse("my_drawings"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('my_drawings')}",
            fetch_redirect_response=False,
        )

    def test_my_drawings_empty_state(self):
        user = self.create_user()
        self.client.force_login(user)

        response = self.client.get(reverse("my_drawings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You have no claimed drawings yet.")
        self.assertContains(response, reverse("claim_drawing"))

    def test_my_drawings_shows_only_current_user_drawings(self):
        user = self.create_user()
        other_user = self.create_user(username="otheruser")
        owned_session = self.create_session()
        other_session = self.create_session(key="other-key")
        anonymous_session = self.create_session(key="anonymous-key")
        DrawingProject.objects.create(
            session=owned_session,
            owner=user,
            title="User A Drawing",
        )
        DrawingProject.objects.create(
            session=other_session,
            owner=other_user,
            title="User B Drawing",
        )
        DrawingProject.objects.create(
            session=anonymous_session,
            title="Unclaimed Drawing",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("my_drawings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User A Drawing")
        self.assertNotContains(response, "User B Drawing")
        self.assertNotContains(response, "Unclaimed Drawing")

    def test_my_drawings_orders_latest_updated_first(self):
        user = self.create_user()
        drawing_session = self.create_session()
        older_project = DrawingProject.objects.create(
            session=drawing_session,
            owner=user,
            title="Older Drawing",
        )
        newer_project = DrawingProject.objects.create(
            session=drawing_session,
            owner=user,
            title="Newer Drawing",
        )
        now = timezone.now()
        DrawingProject.objects.filter(pk=older_project.pk).update(updated_at=now - timedelta(days=2))
        DrawingProject.objects.filter(pk=newer_project.pk).update(updated_at=now)
        self.client.force_login(user)

        response = self.client.get(reverse("my_drawings"))

        content = response.content.decode()
        self.assertLess(content.index("Newer Drawing"), content.index("Older Drawing"))

    def test_my_drawings_cards_show_statuses_and_correct_links(self):
        user = self.create_user()
        drawing_session = self.create_session()
        long_title = (
            "A very long MasDraw title that should stay readable inside the account "
            "drawing dashboard without breaking the card layout"
        )
        private_project = DrawingProject.objects.create(
            session=drawing_session,
            owner=user,
            title=long_title,
        )
        published_project = DrawingProject.objects.create(
            session=drawing_session,
            owner=user,
            title="Published Sketch",
            preview_image="data:image/png;base64,test",
            is_published=True,
            published_at=timezone.now(),
        )
        self.client.force_login(user)

        response = self.client.get(reverse("my_drawings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Private")
        self.assertContains(response, "Published")
        self.assertContains(response, 'data-drawing-search')
        self.assertContains(response, 'data-drawing-filter="published"')
        self.assertContains(response, f'title="{long_title}"')
        self.assertContains(response, reverse("drawing_detail", args=[private_project.public_id]))
        self.assertContains(response, reverse("drawing_detail", args=[published_project.public_id]))
        self.assertContains(response, reverse("showcase_detail", args=[published_project.public_id]))
        self.assertNotContains(response, reverse("showcase_detail", args=[private_project.public_id]))
        self.assertContains(response, "View Public Page", count=1)


class ProfilePictureFlowTests(TestCase):
    def create_user(self, username="profileuser"):
        return get_user_model().objects.create_user(
            username=username,
            password="StrongPass-2026!",
        )

    def create_session(self, key="profile-key"):
        drawing_session = AnonymousDrawingSession(browser_token=f"{key}-browser")
        drawing_session.set_pass_key(key)
        drawing_session.save()
        return drawing_session

    def create_owned_project(self, user, title="Avatar Sketch", preview=True):
        return DrawingProject.objects.create(
            session=self.create_session(key=f"{title.lower().replace(' ', '-')}-key"),
            owner=user,
            title=title,
            preview_image="data:image/png;base64,avatar" if preview else "",
        )

    def test_profile_picture_page_requires_login(self):
        response = self.client.get(reverse("account_profile_picture"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('account_profile_picture')}",
            fetch_redirect_response=False,
        )

    def test_profile_picture_page_lists_owned_drawings_with_previews_only(self):
        user = self.create_user()
        other_user = self.create_user(username="otherprofileuser")
        owned_project = self.create_owned_project(user, title="Usable Avatar")
        self.create_owned_project(user, title="No Preview Avatar", preview=False)
        self.create_owned_project(other_user, title="Other User Avatar")
        self.client.force_login(user)

        response = self.client.get(reverse("account_profile_picture"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Usable Avatar")
        self.assertContains(response, owned_project.preview_image)
        self.assertNotContains(response, "No Preview Avatar")
        self.assertNotContains(response, "Other User Avatar")

    def test_user_can_select_owned_sketch_as_profile_picture(self):
        user = self.create_user()
        project = self.create_owned_project(user)
        self.client.force_login(user)

        response = self.client.post(
            reverse("account_profile_picture"),
            {"profile_drawing": str(project.public_id)},
        )

        profile = UserProfile.objects.get(user=user)
        self.assertRedirects(response, reverse("account_profile_picture"))
        self.assertEqual(profile.profile_drawing, project)

    def test_user_cannot_select_other_user_or_previewless_drawing(self):
        user = self.create_user()
        other_user = self.create_user(username="otherprofileuser")
        other_project = self.create_owned_project(other_user, title="Other Avatar")
        previewless_project = self.create_owned_project(user, title="No Preview", preview=False)
        self.client.force_login(user)

        other_response = self.client.post(
            reverse("account_profile_picture"),
            {"profile_drawing": str(other_project.public_id)},
            follow=True,
        )
        previewless_response = self.client.post(
            reverse("account_profile_picture"),
            {"profile_drawing": str(previewless_project.public_id)},
            follow=True,
        )

        self.assertContains(other_response, "Choose one of your saved drawings with a preview.")
        self.assertContains(previewless_response, "Choose one of your saved drawings with a preview.")
        self.assertIsNone(UserProfile.objects.get(user=user).profile_drawing)

    def test_user_can_remove_profile_picture(self):
        user = self.create_user()
        project = self.create_owned_project(user)
        UserProfile.objects.create(user=user, profile_drawing=project)
        self.client.force_login(user)

        response = self.client.post(
            reverse("account_profile_picture"),
            {"action": "remove"},
        )

        profile = UserProfile.objects.get(user=user)
        self.assertRedirects(response, reverse("account_profile_picture"))
        self.assertIsNone(profile.profile_drawing)

    def test_my_drawings_can_set_profile_picture_and_preserve_page(self):
        user = self.create_user()
        project = self.create_owned_project(user)
        self.client.force_login(user)

        response = self.client.post(
            reverse("account_profile_picture"),
            {
                "profile_drawing": str(project.public_id),
                "next": reverse("my_drawings"),
            },
        )

        profile = UserProfile.objects.get(user=user)
        self.assertRedirects(response, reverse("my_drawings"))
        self.assertEqual(profile.profile_drawing, project)

    def test_dashboard_and_my_drawings_show_selected_profile_picture(self):
        user = self.create_user()
        project = self.create_owned_project(user)
        UserProfile.objects.create(user=user, profile_drawing=project)
        self.client.force_login(user)

        dashboard_response = self.client.get(reverse("account_dashboard"))
        drawings_response = self.client.get(reverse("my_drawings"))

        self.assertContains(dashboard_response, project.preview_image)
        self.assertContains(dashboard_response, reverse("account_profile_picture"))
        self.assertContains(drawings_response, "Current Profile Picture")


class PrivateDrawingAccessTests(TestCase):
    recovery_key = "private-access-key"

    def create_user(self, username="owneruser"):
        return get_user_model().objects.create_user(
            username=username,
            password="StrongPass-2026!",
        )

    def create_session(self, browser_token="private-browser-token", is_active=True):
        drawing_session = AnonymousDrawingSession(
            browser_token=browser_token,
            is_active=is_active,
        )
        drawing_session.set_pass_key(self.recovery_key)
        drawing_session.save()
        return drawing_session

    def test_owner_can_access_claimed_private_drawing(self):
        owner = self.create_user()
        drawing_session = self.create_session()
        project = DrawingProject.objects.create(
            session=drawing_session,
            owner=owner,
            title="Owner private drawing",
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("drawing_detail", args=[project.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "draw.html")

    def test_non_owner_cannot_access_claimed_private_drawing(self):
        owner = self.create_user()
        other_user = self.create_user(username="otheruser")
        drawing_session = self.create_session()
        project = DrawingProject.objects.create(
            session=drawing_session,
            owner=owner,
            title="Owner private drawing",
        )
        self.client.force_login(other_user)

        response = self.client.get(reverse("drawing_detail", args=[project.public_id]))

        self.assertRedirects(response, reverse("recover_drawing"))

    def test_anonymous_user_without_browser_token_cannot_access_private_drawing(self):
        drawing_session = self.create_session()
        project = DrawingProject.objects.create(
            session=drawing_session,
            title="Private drawing",
        )

        response = self.client.get(reverse("drawing_detail", args=[project.public_id]))

        self.assertRedirects(response, reverse("recover_drawing"))

    def test_anonymous_user_with_valid_browser_token_can_access_private_drawing(self):
        drawing_session = self.create_session(browser_token="valid-browser-token")
        project = DrawingProject.objects.create(
            session=drawing_session,
            title="Private drawing",
        )
        self.client.cookies[BROWSER_COOKIE_NAME] = "valid-browser-token"

        response = self.client.get(reverse("drawing_detail", args=[project.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "draw.html")

    def test_recovered_session_can_access_private_drawing(self):
        drawing_session = self.create_session()
        project = DrawingProject.objects.create(
            session=drawing_session,
            title="Recovered drawing",
        )

        recovery_response = self.client.post(
            reverse("recover_drawing"),
            {"pass_key": self.recovery_key},
        )
        detail_response = self.client.get(reverse("drawing_detail", args=[project.public_id]))

        self.assertRedirects(
            recovery_response,
            reverse("drawing_detail", args=[project.public_id]),
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertTemplateUsed(detail_response, "draw.html")

    def test_published_showcase_detail_remains_publicly_accessible(self):
        drawing_session = self.create_session()
        project = DrawingProject.objects.create(
            session=drawing_session,
            title="Public drawing",
            preview_image="data:image/png;base64,test",
            is_published=True,
            published_at=timezone.now(),
        )

        response = self.client.get(reverse("showcase_detail", args=[project.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "showcase_detail.html")

    def test_published_showcase_detail_has_image_viewer_controls(self):
        drawing_session = self.create_session()
        project = DrawingProject.objects.create(
            session=drawing_session,
            title="Public viewer drawing",
            preview_image="data:image/png;base64,test",
            is_published=True,
            published_at=timezone.now(),
        )

        response = self.client.get(reverse("showcase_detail", args=[project.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-sketch-viewer')
        self.assertContains(response, 'data-viewer-fullscreen')
        self.assertContains(response, 'data-viewer-zoom-out')
        self.assertContains(response, 'data-viewer-zoom-in')
        self.assertContains(response, 'data-viewer-reset')
        self.assertContains(response, 'data-viewer-download')
        self.assertContains(response, f'data-download-name="masdraw-{project.public_id}.png"')


class DrawingHeartFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    def create_user(self, username="heartuser"):
        return get_user_model().objects.create_user(
            username=username,
            password="StrongPass-2026!",
        )

    def create_session(self, key="heart-key"):
        drawing_session = AnonymousDrawingSession(browser_token=f"{key}-browser")
        drawing_session.set_pass_key(key)
        drawing_session.save()
        return drawing_session

    def create_project(self, is_published=True, title="Hearted Drawing"):
        return DrawingProject.objects.create(
            session=self.create_session(),
            title=title,
            preview_image="data:image/png;base64,test",
            is_published=is_published,
            published_at=timezone.now() if is_published else None,
        )

    def test_anonymous_user_cannot_heart_published_drawing(self):
        project = self.create_project()

        response = self.client.post(reverse("toggle_drawing_heart", args=[project.public_id]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertFalse(DrawingHeart.objects.exists())

    def test_logged_in_user_can_heart_and_unheart_published_drawing(self):
        user = self.create_user()
        project = self.create_project()
        self.client.force_login(user)

        heart_response = self.client.post(reverse("toggle_drawing_heart", args=[project.public_id]))
        project.refresh_from_db()

        self.assertEqual(heart_response.status_code, 200)
        self.assertJSONEqual(
            heart_response.content,
            {"success": True, "hearted": True, "heart_count": 1},
        )
        self.assertEqual(project.heart_count, 1)
        self.assertEqual(DrawingHeart.objects.filter(drawing=project, user=user).count(), 1)

        unheart_response = self.client.post(reverse("toggle_drawing_heart", args=[project.public_id]))
        project.refresh_from_db()

        self.assertEqual(unheart_response.status_code, 200)
        self.assertJSONEqual(
            unheart_response.content,
            {"success": True, "hearted": False, "heart_count": 0},
        )
        self.assertEqual(project.heart_count, 0)
        self.assertFalse(DrawingHeart.objects.filter(drawing=project, user=user).exists())

    def test_one_user_can_only_have_one_heart_per_drawing(self):
        user = self.create_user()
        project = self.create_project()
        DrawingHeart.objects.create(drawing=project, user=user)
        project.heart_count = 1
        project.save(update_fields=["heart_count"])
        self.client.force_login(user)

        response = self.client.post(reverse("toggle_drawing_heart", args=[project.public_id]))
        project.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(project.heart_count, 0)
        self.assertEqual(DrawingHeart.objects.filter(drawing=project, user=user).count(), 0)

    def test_private_drawing_cannot_be_hearted(self):
        user = self.create_user()
        project = self.create_project(is_published=False)
        self.client.force_login(user)

        response = self.client.post(reverse("toggle_drawing_heart", args=[project.public_id]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(DrawingHeart.objects.exists())

    def test_showcase_displays_heart_count_and_active_state(self):
        user = self.create_user()
        project = self.create_project(title="Public Hearted Drawing")
        DrawingHeart.objects.create(drawing=project, user=user)
        project.heart_count = 1
        project.save(update_fields=["heart_count"])
        self.client.force_login(user)

        response = self.client.get(reverse("showcase"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Public Hearted Drawing")
        self.assertContains(response, 'data-heart-button')
        self.assertContains(response, 'is-hearted')
        self.assertContains(response, ">1</span>", html=False)

    def test_showcase_displays_top_five_most_hearted_published_drawings(self):
        for heart_count in [3, 9, 5, 1, 7, 2]:
            project = self.create_project(title=f"Top Heart {heart_count}")
            project.heart_count = heart_count
            project.save(update_fields=["heart_count"])
        private_project = self.create_project(
            is_published=False,
            title="Private Top Heart",
        )
        private_project.heart_count = 99
        private_project.save(update_fields=["heart_count"])

        response = self.client.get(reverse("showcase"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Most Hearted Sketches")
        self.assertEqual(
            [project.title for project in response.context["top_hearted_projects"]],
            [
                "Top Heart 9",
                "Top Heart 7",
                "Top Heart 5",
                "Top Heart 3",
                "Top Heart 2",
            ],
        )
        self.assertNotIn(private_project, response.context["top_hearted_projects"])


class DrawingCommentFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    def create_user(self, username="commentuser"):
        return get_user_model().objects.create_user(
            username=username,
            password="StrongPass-2026!",
        )

    def create_session(self, key="comment-key"):
        drawing_session = AnonymousDrawingSession(browser_token=f"{key}-browser")
        drawing_session.set_pass_key(key)
        drawing_session.save()
        return drawing_session

    def create_project(self, is_published=True, title="Commented Drawing"):
        return DrawingProject.objects.create(
            session=self.create_session(),
            title=title,
            preview_image="data:image/png;base64,test",
            is_published=is_published,
            published_at=timezone.now() if is_published else None,
        )

    def test_showcase_displays_comment_count(self):
        project = self.create_project(title="Public Comment Count")
        project.comment_count = 3
        project.save(update_fields=["comment_count"])

        response = self.client.get(reverse("showcase"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Public Comment Count")
        self.assertContains(response, "3")
        self.assertContains(response, "Comments")

    def test_detail_displays_visible_hidden_and_deleted_comments(self):
        user = self.create_user()
        project = self.create_project()
        visible_comment = DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="This sketch has great movement.",
        )
        hidden_comment = DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="Hidden moderation body",
            is_hidden=True,
        )
        DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="",
            is_deleted_by_user=True,
        )
        project.comment_count = 1
        project.save(update_fields=["comment_count"])

        response = self.client.get(reverse("showcase_detail", args=[project.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, visible_comment.body)
        self.assertContains(response, "This comment was removed.", count=2)
        self.assertNotContains(response, hidden_comment.body)
        self.assertContains(response, "Login or create an account to comment on this drawing.")

    def test_detail_displays_owner_and_commenter_sketch_stats(self):
        owner = self.create_user(username="creatoruser")
        commenter = self.create_user(username="sketchcommenter")
        owner_session = self.create_session(key="creator-owner-key")
        project = DrawingProject.objects.create(
            session=owner_session,
            owner=owner,
            title="Creator Stats Drawing",
            preview_image="data:image/png;base64,test",
            is_published=True,
            published_at=timezone.now(),
            heart_count=2,
        )
        DrawingProject.objects.create(
            session=self.create_session(key="creator-extra-one"),
            owner=owner,
            title="Creator Extra One",
            heart_count=4,
        )
        DrawingProject.objects.create(
            session=self.create_session(key="creator-extra-two"),
            owner=owner,
            title="Creator Extra Two",
            heart_count=1,
        )
        commenter_avatar = DrawingProject.objects.create(
            session=self.create_session(key="commenter-one"),
            owner=commenter,
            title="Commenter One",
            preview_image="data:image/png;base64,commenter-avatar",
        )
        DrawingProject.objects.create(
            session=self.create_session(key="commenter-two"),
            owner=commenter,
            title="Commenter Two",
        )
        UserProfile.objects.create(user=owner, profile_drawing=project)
        UserProfile.objects.create(user=commenter, profile_drawing=commenter_avatar)
        DrawingComment.objects.create(
            drawing=project,
            user=commenter,
            body="Commenter profile stats should show.",
        )
        project.comment_count = 1
        project.save(update_fields=["comment_count"])

        response = self.client.get(reverse("showcase_detail", args=[project.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "creatoruser")
        self.assertContains(response, "Claimed sketches")
        self.assertContains(response, "Total hearts")
        self.assertContains(response, "<dd>3</dd>", html=False)
        self.assertContains(response, "7")
        self.assertContains(response, project.preview_image)
        self.assertContains(response, "sketchcommenter")
        self.assertContains(response, commenter_avatar.preview_image)
        self.assertContains(response, "2 claimed sketches")

    def test_anonymous_user_cannot_post_comment(self):
        project = self.create_project()

        response = self.client.post(
            reverse("create_drawing_comment", args=[project.public_id]),
            {"body": "Anonymous comment"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertFalse(DrawingComment.objects.exists())

    def test_logged_in_user_can_post_comment_on_published_drawing(self):
        user = self.create_user()
        project = self.create_project()
        self.client.force_login(user)

        response = self.client.post(
            reverse("create_drawing_comment", args=[project.public_id]),
            {"body": "A clean and expressive drawing."},
        )

        project.refresh_from_db()
        self.assertEqual(
            response["Location"],
            f"{reverse('showcase_detail', args=[project.public_id])}#comments",
        )
        self.assertEqual(project.comment_count, 1)
        self.assertTrue(
            DrawingComment.objects.filter(
                drawing=project,
                user=user,
                body="A clean and expressive drawing.",
            ).exists()
        )

    def test_empty_and_too_long_comments_are_rejected(self):
        user = self.create_user()
        project = self.create_project()
        self.client.force_login(user)

        empty_response = self.client.post(
            reverse("create_drawing_comment", args=[project.public_id]),
            {"body": "   "},
            follow=True,
        )
        long_response = self.client.post(
            reverse("create_drawing_comment", args=[project.public_id]),
            {"body": "x" * 501},
            follow=True,
        )

        project.refresh_from_db()
        self.assertContains(empty_response, "Comment cannot be empty.")
        self.assertContains(long_response, "Comment is too long.")
        self.assertEqual(project.comment_count, 0)
        self.assertFalse(DrawingComment.objects.exists())

    def test_private_drawing_cannot_receive_comments(self):
        user = self.create_user()
        project = self.create_project(is_published=False)
        self.client.force_login(user)

        response = self.client.post(
            reverse("create_drawing_comment", args=[project.public_id]),
            {"body": "Private comment"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(DrawingComment.objects.exists())

    def test_user_can_soft_delete_own_comment_and_count_decrements(self):
        user = self.create_user()
        project = self.create_project()
        comment = DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="Delete my own comment.",
        )
        project.comment_count = 1
        project.save(update_fields=["comment_count"])
        self.client.force_login(user)

        response = self.client.post(reverse("delete_drawing_comment", args=[comment.id]))

        comment.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(
            response["Location"],
            f"{reverse('showcase_detail', args=[project.public_id])}#comments",
        )
        self.assertTrue(comment.is_deleted_by_user)
        self.assertEqual(comment.body, "")
        self.assertEqual(project.comment_count, 0)

    def test_user_cannot_delete_another_users_comment(self):
        owner = self.create_user(username="commentowner")
        other_user = self.create_user(username="commentviewer")
        project = self.create_project()
        comment = DrawingComment.objects.create(
            drawing=project,
            user=owner,
            body="Do not delete this.",
        )
        project.comment_count = 1
        project.save(update_fields=["comment_count"])
        self.client.force_login(other_user)

        response = self.client.post(
            reverse("delete_drawing_comment", args=[comment.id]),
            follow=True,
        )

        comment.refresh_from_db()
        project.refresh_from_db()
        self.assertContains(response, "You can only delete your own comments.")
        self.assertFalse(comment.is_deleted_by_user)
        self.assertEqual(comment.body, "Do not delete this.")
        self.assertEqual(project.comment_count, 1)

    def test_hidden_comment_is_not_counted_publicly(self):
        user = self.create_user()
        project = self.create_project()
        DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="Hidden body",
            is_hidden=True,
        )
        project.comment_count = 0
        project.save(update_fields=["comment_count"])

        response = self.client.get(reverse("showcase_detail", args=[project.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0 comments")
        self.assertContains(response, "This comment was removed.")
        self.assertNotContains(response, "Hidden body")

    def test_showcase_detail_paginates_comments(self):
        user = self.create_user()
        project = self.create_project()
        base_time = timezone.now()
        for index in range(25):
            comment = DrawingComment.objects.create(
                drawing=project,
                user=user,
                body=f"Paged comment {index + 1}",
            )
            DrawingComment.objects.filter(pk=comment.pk).update(
                created_at=base_time + timedelta(minutes=index)
            )
        project.comment_count = 25
        project.save(update_fields=["comment_count"])

        first_page = self.client.get(reverse("showcase_detail", args=[project.public_id]))
        second_page = self.client.get(
            f"{reverse('showcase_detail', args=[project.public_id])}?comments_page=2"
        )

        self.assertEqual(first_page.status_code, 200)
        self.assertContains(first_page, "Paged comment 1")
        self.assertContains(first_page, "Paged comment 20")
        self.assertNotContains(first_page, "Paged comment 21")
        self.assertContains(first_page, "Page 1 of 2")
        self.assertContains(first_page, "?comments_page=2#comments")

        self.assertEqual(second_page.status_code, 200)
        self.assertContains(second_page, "Paged comment 21")
        self.assertContains(second_page, "Paged comment 25")
        self.assertNotContains(second_page, "Paged comment 1")
        self.assertContains(second_page, "Page 2 of 2")

    def test_comment_post_redirects_to_last_comment_page(self):
        user = self.create_user()
        project = self.create_project()
        for index in range(20):
            DrawingComment.objects.create(
                drawing=project,
                user=user,
                body=f"Existing comment {index + 1}",
            )
        project.comment_count = 20
        project.save(update_fields=["comment_count"])
        self.client.force_login(user)

        response = self.client.post(
            reverse("create_drawing_comment", args=[project.public_id]),
            {"body": "This should land on page two."},
        )

        project.refresh_from_db()
        self.assertEqual(project.comment_count, 21)
        self.assertEqual(
            response["Location"],
            f"{reverse('showcase_detail', args=[project.public_id])}?comments_page=2#comments",
        )

    def test_comment_delete_preserves_requested_comment_page(self):
        user = self.create_user()
        project = self.create_project()
        comment = DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="Delete from page two.",
        )
        project.comment_count = 1
        project.save(update_fields=["comment_count"])
        self.client.force_login(user)

        response = self.client.post(
            reverse("delete_drawing_comment", args=[comment.id]),
            {"comments_page": "2"},
        )

        self.assertEqual(
            response["Location"],
            f"{reverse('showcase_detail', args=[project.public_id])}?comments_page=2#comments",
        )

    def test_showcase_detail_displays_heart_count_and_active_state(self):
        user = self.create_user()
        project = self.create_project()
        DrawingHeart.objects.create(drawing=project, user=user)
        project.heart_count = 1
        project.save(update_fields=["heart_count"])
        self.client.force_login(user)

        response = self.client.get(reverse("showcase_detail", args=[project.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-heart-button')
        self.assertContains(response, 'is-hearted')
        self.assertContains(response, ">1</span>", html=False)


class AdminModerationTests(TestCase):
    def create_user(self, username="moderatoruser"):
        return get_user_model().objects.create_user(
            username=username,
            password="StrongPass-2026!",
        )

    def create_session(self, key="moderation-key"):
        drawing_session = AnonymousDrawingSession(browser_token=f"{key}-browser")
        drawing_session.set_pass_key(key)
        drawing_session.save()
        return drawing_session

    def create_project(self, **kwargs):
        defaults = {
            "session": self.create_session(),
            "title": "Moderated Drawing",
            "preview_image": "data:image/png;base64,test",
        }
        defaults.update(kwargs)
        return DrawingProject.objects.create(**defaults)

    def test_drawing_admin_publish_unpublish_and_feature_actions(self):
        project = self.create_project()

        publish_selected_drawings(
            None,
            None,
            DrawingProject.objects.filter(pk=project.pk),
        )
        project.refresh_from_db()
        self.assertTrue(project.is_published)
        self.assertIsNotNone(project.published_at)

        published_at = project.published_at
        unpublish_selected_drawings(
            None,
            None,
            DrawingProject.objects.filter(pk=project.pk),
        )
        project.refresh_from_db()
        self.assertFalse(project.is_published)
        self.assertEqual(project.published_at, published_at)
        self.assertEqual(
            self.client.get(reverse("showcase_detail", args=[project.public_id])).status_code,
            404,
        )

        feature_selected_drawings(
            None,
            None,
            DrawingProject.objects.filter(pk=project.pk),
        )
        project.refresh_from_db()
        self.assertTrue(project.is_featured)

        unfeature_selected_drawings(
            None,
            None,
            DrawingProject.objects.filter(pk=project.pk),
        )
        project.refresh_from_db()
        self.assertFalse(project.is_featured)

    def test_comment_admin_hide_unhide_actions_keep_visible_count_accurate(self):
        user = self.create_user()
        project = self.create_project(is_published=True, comment_count=1)
        visible_comment = DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="Visible before moderation.",
        )
        deleted_comment = DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="",
            is_hidden=True,
            is_deleted_by_user=True,
        )

        hide_selected_comments(
            None,
            None,
            DrawingComment.objects.filter(pk__in=[visible_comment.pk, deleted_comment.pk]),
        )
        project.refresh_from_db()
        visible_comment.refresh_from_db()
        deleted_comment.refresh_from_db()
        self.assertTrue(visible_comment.is_hidden)
        self.assertTrue(deleted_comment.is_hidden)
        self.assertEqual(project.comment_count, 0)

        hide_selected_comments(
            None,
            None,
            DrawingComment.objects.filter(pk=visible_comment.pk),
        )
        project.refresh_from_db()
        self.assertEqual(project.comment_count, 0)

        unhide_selected_comments(
            None,
            None,
            DrawingComment.objects.filter(pk__in=[visible_comment.pk, deleted_comment.pk]),
        )
        project.refresh_from_db()
        visible_comment.refresh_from_db()
        deleted_comment.refresh_from_db()
        self.assertFalse(visible_comment.is_hidden)
        self.assertFalse(deleted_comment.is_hidden)
        self.assertTrue(deleted_comment.is_deleted_by_user)
        self.assertEqual(project.comment_count, 1)


class AntiAbuseProtectionTests(TestCase):
    recovery_key = "anti-abuse-recovery-key"

    def setUp(self):
        cache.clear()

    def create_user(self, username="antiabuseuser"):
        return get_user_model().objects.create_user(
            username=username,
            password="StrongPass-2026!",
        )

    def create_session(self, key=None):
        drawing_session = AnonymousDrawingSession(browser_token=f"{key or self.recovery_key}-browser")
        drawing_session.set_pass_key(key or self.recovery_key)
        drawing_session.save()
        return drawing_session

    def create_project(self, is_published=True, **kwargs):
        defaults = {
            "session": self.create_session(),
            "title": "Protected Drawing",
            "preview_image": "data:image/png;base64,test",
            "is_published": is_published,
            "published_at": timezone.now() if is_published else None,
        }
        defaults.update(kwargs)
        return DrawingProject.objects.create(**defaults)

    def test_claim_attempts_are_rate_limited_and_oversized_key_is_invalid(self):
        user = self.create_user()
        self.create_session()
        self.client.force_login(user)

        oversized_response = self.client.post(
            reverse("claim_drawing"),
            {"recovery_key": "x" * 101},
        )
        self.assertContains(oversized_response, "Invalid recovery key.")

        cache.clear()
        for _ in range(5):
            response = self.client.post(
                reverse("claim_drawing"),
                {"recovery_key": "wrong-key"},
            )
            self.assertContains(response, "Invalid recovery key.")

        blocked_response = self.client.post(
            reverse("claim_drawing"),
            {"recovery_key": "wrong-key"},
        )
        self.assertContains(
            blocked_response,
            "Too many claim attempts. Please try again later.",
        )

    def test_comment_creation_is_rate_limited_after_five_valid_comments(self):
        user = self.create_user()
        project = self.create_project()
        self.client.force_login(user)

        for index in range(5):
            response = self.client.post(
                reverse("create_drawing_comment", args=[project.public_id]),
                {"body": f"Valid comment {index + 1}"},
            )
            self.assertEqual(response.status_code, 302)

        blocked_response = self.client.post(
            reverse("create_drawing_comment", args=[project.public_id]),
            {"body": "One comment too many."},
            follow=True,
        )
        project.refresh_from_db()

        self.assertContains(
            blocked_response,
            "You are commenting too quickly. Please try again later.",
        )
        self.assertEqual(project.comment_count, 5)
        self.assertEqual(DrawingComment.objects.filter(drawing=project).count(), 5)

    def test_heart_toggles_are_rate_limited_without_breaking_count(self):
        user = self.create_user()
        project = self.create_project()
        self.client.force_login(user)

        for _ in range(30):
            response = self.client.post(reverse("toggle_drawing_heart", args=[project.public_id]))
            self.assertEqual(response.status_code, 200)

        blocked_response = self.client.post(reverse("toggle_drawing_heart", args=[project.public_id]))
        project.refresh_from_db()

        self.assertEqual(blocked_response.status_code, 429)
        self.assertJSONEqual(
            blocked_response.content,
            {
                "success": False,
                "error": "Too many heart actions. Please try again later.",
            },
        )
        self.assertEqual(project.heart_count, 0)
        self.assertFalse(DrawingHeart.objects.filter(drawing=project, user=user).exists())

    def test_mutating_actions_keep_post_only_behavior(self):
        user = self.create_user()
        project = self.create_project()
        comment = DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="Delete over POST only.",
        )
        self.client.force_login(user)

        self.assertEqual(
            self.client.get(reverse("toggle_drawing_heart", args=[project.public_id])).status_code,
            405,
        )
        self.assertEqual(
            self.client.get(reverse("create_drawing_comment", args=[project.public_id])).status_code,
            405,
        )
        self.assertEqual(
            self.client.get(reverse("delete_drawing_comment", args=[comment.id])).status_code,
            405,
        )
        self.assertEqual(self.client.get(reverse("claim_drawing")).status_code, 200)

    def test_mutating_actions_require_csrf_token(self):
        user = self.create_user()
        project = self.create_project()
        comment = DrawingComment.objects.create(
            drawing=project,
            user=user,
            body="CSRF protected comment.",
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        self.assertEqual(
            csrf_client.post(reverse("claim_drawing"), {"recovery_key": self.recovery_key}).status_code,
            403,
        )
        self.assertEqual(
            csrf_client.post(reverse("toggle_drawing_heart", args=[project.public_id])).status_code,
            403,
        )
        self.assertEqual(
            csrf_client.post(
                reverse("create_drawing_comment", args=[project.public_id]),
                {"body": "CSRF should block this."},
            ).status_code,
            403,
        )
        self.assertEqual(
            csrf_client.post(reverse("delete_drawing_comment", args=[comment.id])).status_code,
            403,
        )
