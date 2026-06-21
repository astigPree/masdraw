import json
from hashlib import sha256
from xml.sax.saxutils import escape

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Sum
from django.middleware.csrf import get_token
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_http_methods, require_POST

from .models import AnonymousDrawingSession, DrawingComment, DrawingHeart, DrawingProject, UserProfile


BROWSER_COOKIE_NAME = "masdraw_browser_token"
RECOVERED_SESSION_IDS_KEY = "recovered_session_ids"
RECOVERED_PROJECT_IDS_KEY = "recovered_project_ids"
COMMENT_PAGE_SIZE = 20
CLAIM_RECOVERY_KEY_MAX_LENGTH = 100
COMMENT_BODY_MAX_LENGTH = 500
CLAIM_RATE_LIMIT = {"limit": 5, "window_seconds": 10 * 60}
COMMENT_RATE_LIMIT = {"limit": 5, "window_seconds": 60}
HEART_RATE_LIMIT = {"limit": 30, "window_seconds": 60}
DRAWING_CREATION_LIMITS = (
    {"limit": 5, "window": 10 * 60, "label": "10 minutes"},
    {"limit": 30, "window": 24 * 60 * 60, "label": "24 hours"},
)


def sitemap_field(sitemap, field_name, item):
    value = getattr(sitemap, field_name, None)
    if callable(value):
        return value(item)
    return value


def clean_sitemap(request, sitemaps=None, *args, **kwargs):
    base_url = settings.PRIMARY_SITE_URL.rstrip("/")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for sitemap_class in (sitemaps or {}).values():
        sitemap = sitemap_class() if isinstance(sitemap_class, type) else sitemap_class
        for item in sitemap.items():
            lines.append("  <url>")
            lines.append(f"    <loc>{escape(base_url + sitemap.location(item))}</loc>")

            lastmod = sitemap_field(sitemap, "lastmod", item)
            if lastmod:
                lines.append(f"    <lastmod>{escape(lastmod.isoformat())}</lastmod>")

            changefreq = sitemap_field(sitemap, "changefreq", item)
            if changefreq:
                lines.append(f"    <changefreq>{escape(str(changefreq))}</changefreq>")

            priority = sitemap_field(sitemap, "priority", item)
            if priority is not None:
                lines.append(f"    <priority>{escape(str(priority))}</priority>")

            lines.append("  </url>")

    lines.append("</urlset>")
    return HttpResponse("\n".join(lines), content_type="application/xml")


@cache_control(public=True, max_age=60 * 60 * 24)
def favicon(request):
    favicon_path = settings.BASE_DIR / "static" / "favicon.ico"
    if not favicon_path.exists():
        raise Http404("Favicon not found.")

    return FileResponse(favicon_path.open("rb"), content_type="image/x-icon")


def get_featured_projects(limit=8):
    return DrawingProject.objects.filter(
        is_published=True,
        is_featured=True,
    ).order_by("featured_order", "-published_at")[:limit]


def get_hearted_drawing_ids(request, projects):
    if not request.user.is_authenticated:
        return set()

    project_ids = [project.id for project in projects]
    if not project_ids:
        return set()

    return set(
        DrawingHeart.objects.filter(
            user=request.user,
            drawing_id__in=project_ids,
        ).values_list("drawing_id", flat=True)
    )


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def get_rate_limit_actor(request):
    if request.user.is_authenticated:
        return f"user:{request.user.id}"

    ip_hash = sha256(get_client_ip(request).encode("utf-8")).hexdigest()[:24]
    return f"ip:{ip_hash}"


def get_rate_limit_key(namespace, request):
    return f"masdraw:{namespace}:{get_rate_limit_actor(request)}"


def is_rate_limited(key, limit, window_seconds):
    current = cache.get(key)
    if current is None:
        cache.set(key, 1, window_seconds)
        return False

    if current >= limit:
        return True

    try:
        cache.incr(key)
    except (ValueError, NotImplementedError):
        cache.set(key, current + 1, window_seconds)

    return False


def rate_limit_drawing_creation(request):
    ip_hash = sha256(get_client_ip(request).encode("utf-8")).hexdigest()[:24]
    cache_keys = []

    for rule in DRAWING_CREATION_LIMITS:
        key = f"draw_create:{rule['window']}:{ip_hash}"
        current_count = cache.get(key, 0)
        if current_count >= rule["limit"]:
            return False, rule
        cache_keys.append((key, rule["window"]))

    for key, window in cache_keys:
        if cache.add(key, 1, timeout=window):
            continue
        cache.incr(key)

    return True, None


def home(request):
    browser_token = request.COOKIES.get(BROWSER_COOKIE_NAME)
    recent_project = None
    featured_projects = get_featured_projects()

    if browser_token:
        recent_project = (
            DrawingProject.objects.filter(
                session__browser_token=browser_token,
                session__is_active=True,
            )
            .select_related("session")
            .first()
        )

    return render(
        request,
        "home.html",
        {
            "recent_project": recent_project,
            "featured_projects": featured_projects,
        },
    )


def anonymous_drawing_masbate_online(request):
    return render(
        request,
        "anonymous_drawing_masbate_online.html",
        {
            "featured_projects": get_featured_projects(limit=6),
        },
    )


def is_ajax_auth_request(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def render_auth_form_html(request, template_name, context):
    return render_to_string(
        template_name,
        {
            **context,
            "is_modal": True,
        },
        request=request,
    )


def authenticated_payload(request, user, message):
    return {
        "ok": True,
        "authenticated": True,
        "username": user.get_username(),
        "message": message,
        "my_drawings_url": reverse("my_drawings"),
        "account_url": reverse("account_dashboard"),
        "logout_url": reverse("logout"),
        "csrf_token": get_token(request),
    }


def anonymous_payload(request, message):
    return {
        "ok": True,
        "authenticated": False,
        "message": message,
        "login_url": reverse("login"),
        "register_url": reverse("register"),
        "csrf_token": get_token(request),
    }


def user_can_access_drawing(request, project):
    if request.user.is_authenticated and project.owner_id == request.user.id:
        return True

    browser_token = request.COOKIES.get(BROWSER_COOKIE_NAME)
    if browser_token and project.session.browser_token == browser_token:
        return True

    recovered_sessions = request.session.get(RECOVERED_SESSION_IDS_KEY, [])
    if str(project.session.public_id) in recovered_sessions:
        return True

    recovered_projects = request.session.get(RECOVERED_PROJECT_IDS_KEY, [])
    if str(project.public_id) in recovered_projects:
        return True

    return False


def remember_recovered_drawing_access(request, drawing_session, project):
    recovered_sessions = set(request.session.get(RECOVERED_SESSION_IDS_KEY, []))
    recovered_projects = set(request.session.get(RECOVERED_PROJECT_IDS_KEY, []))
    recovered_sessions.add(str(drawing_session.public_id))
    recovered_projects.add(str(project.public_id))
    request.session[RECOVERED_SESSION_IDS_KEY] = list(recovered_sessions)
    request.session[RECOVERED_PROJECT_IDS_KEY] = list(recovered_projects)


def comment_page_url(public_id, page_number=None):
    base_url = reverse("showcase_detail", kwargs={"public_id": public_id})
    try:
        page_number = int(page_number or 1)
    except (TypeError, ValueError):
        page_number = 1

    if page_number > 1:
        return f"{base_url}?comments_page={page_number}#comments"
    return f"{base_url}#comments"


def get_last_comment_page_number(comment_count):
    if comment_count <= 0:
        return 1
    return ((comment_count - 1) // COMMENT_PAGE_SIZE) + 1


def safe_redirect_from_request(request, fallback_url_name):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(fallback_url_name)


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        if is_ajax_auth_request(request):
            return JsonResponse(
                authenticated_payload(request, request.user, "You are already logged in.")
            )
        return redirect("account_dashboard")

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            if is_ajax_auth_request(request):
                return JsonResponse(
                    authenticated_payload(request, user, "Your account is ready.")
                )
            messages.success(request, "Your account is ready.")
            return redirect("account_dashboard")
        if is_ajax_auth_request(request):
            return JsonResponse(
                {
                    "ok": False,
                    "title": "Create account",
                    "message": "Check the form and try again.",
                    "html": render_auth_form_html(
                        request,
                        "account/_register_form.html",
                        {"form": form},
                    ),
                },
                status=400,
            )
    else:
        form = UserCreationForm()

    if is_ajax_auth_request(request):
        return JsonResponse(
            {
                "ok": True,
                "title": "Create account",
                "html": render_auth_form_html(
                    request,
                    "account/_register_form.html",
                    {"form": form},
                ),
            }
        )

    return render(request, "account/register.html", {"form": form})


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        if is_ajax_auth_request(request):
            return JsonResponse(
                authenticated_payload(request, request.user, "You are already logged in.")
            )
        return redirect("account_dashboard")

    next_url = request.POST.get("next") or request.GET.get("next")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            auth_login(request, form.get_user())
            if is_ajax_auth_request(request):
                return JsonResponse(
                    authenticated_payload(request, form.get_user(), "You are logged in.")
                )
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect("account_dashboard")
        if is_ajax_auth_request(request):
            return JsonResponse(
                {
                    "ok": False,
                    "title": "Login",
                    "message": "Check your username and password.",
                    "html": render_auth_form_html(
                        request,
                        "account/_login_form.html",
                        {"form": form, "next": next_url},
                    ),
                },
                status=400,
            )
    else:
        form = AuthenticationForm(request)

    if is_ajax_auth_request(request):
        return JsonResponse(
            {
                "ok": True,
                "title": "Login",
                "html": render_auth_form_html(
                    request,
                    "account/_login_form.html",
                    {"form": form, "next": next_url},
                ),
            }
        )

    return render(request, "account/login.html", {"form": form, "next": next_url})


@require_POST
def logout_view(request):
    auth_logout(request)
    if is_ajax_auth_request(request):
        return JsonResponse(anonymous_payload(request, "You have been logged out."))
    messages.success(request, "You have been logged out.")
    return redirect("home")


@login_required(login_url="login")
def account_dashboard(request):
    profile = (
        UserProfile.objects.select_related("profile_drawing")
        .filter(user=request.user)
        .first()
    )
    drawings = DrawingProject.objects.filter(owner=request.user)
    total_count = drawings.count()
    published_count = drawings.filter(is_published=True).count()
    private_count = total_count - published_count
    interaction_totals = drawings.aggregate(
        total_hearts=Sum("heart_count"),
        total_comments=Sum("comment_count"),
    )
    recent_drawings = list(drawings.order_by("-updated_at")[:3])
    return render(
        request,
        "account/dashboard.html",
        {
            "profile": profile,
            "total_count": total_count,
            "published_count": published_count,
            "private_count": private_count,
            "total_hearts": interaction_totals["total_hearts"] or 0,
            "total_comments": interaction_totals["total_comments"] or 0,
            "recent_drawings": recent_drawings,
        },
    )


@login_required(login_url="login")
def my_drawings_view(request):
    drawings = DrawingProject.objects.filter(owner=request.user).order_by("-updated_at")
    profile = (
        UserProfile.objects.select_related("profile_drawing")
        .filter(user=request.user)
        .first()
    )
    total_count = drawings.count()
    published_count = drawings.filter(is_published=True).count()
    private_count = total_count - published_count
    return render(
        request,
        "account/my_drawings.html",
        {
            "drawings": drawings,
            "total_count": total_count,
            "published_count": published_count,
            "private_count": private_count,
            "profile": profile,
        },
    )


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def account_profile_picture_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    drawings = DrawingProject.objects.filter(
        owner=request.user,
    ).exclude(
        preview_image="",
    ).order_by("-updated_at")

    if request.method == "POST":
        if request.POST.get("action") == "remove":
            profile.profile_drawing = None
            profile.save(update_fields=["profile_drawing", "updated_at"])
            messages.success(request, "Your profile picture was removed.")
            return safe_redirect_from_request(request, "account_profile_picture")

        profile_drawing_id = request.POST.get("profile_drawing", "").strip()
        selected_drawing = drawings.filter(public_id=profile_drawing_id).first()

        if not selected_drawing:
            messages.error(request, "Choose one of your saved drawings with a preview.")
            return safe_redirect_from_request(request, "account_profile_picture")

        profile.profile_drawing = selected_drawing
        profile.save(update_fields=["profile_drawing", "updated_at"])
        messages.success(request, "Your profile picture was updated.")
        return safe_redirect_from_request(request, "account_profile_picture")

    profile = UserProfile.objects.select_related("profile_drawing").get(pk=profile.pk)
    return render(
        request,
        "account/profile_picture.html",
        {
            "profile": profile,
            "drawings": drawings,
        },
    )


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def claim_drawing_view(request):
    if request.method == "POST":
        if is_rate_limited(get_rate_limit_key("claim", request), **CLAIM_RATE_LIMIT):
            messages.error(request, "Too many claim attempts. Please try again later.")
            return render(request, "account/claim_drawing.html")

        recovery_key = request.POST.get("recovery_key", "").strip()
        if not recovery_key:
            messages.error(request, "Recovery key is required.")
            return render(request, "account/claim_drawing.html")

        if len(recovery_key) > CLAIM_RECOVERY_KEY_MAX_LENGTH:
            messages.error(request, "Invalid recovery key.")
            return render(request, "account/claim_drawing.html")

        matching_session = None
        for drawing_session in AnonymousDrawingSession.objects.filter(is_active=True):
            if drawing_session.verify_pass_key(recovery_key):
                matching_session = drawing_session
                break

        if not matching_session:
            messages.error(request, "Invalid recovery key.")
            return render(request, "account/claim_drawing.html")

        projects = list(matching_session.projects.select_related("owner"))
        if not projects:
            messages.error(request, "No drawings found for this recovery key.")
            return render(request, "account/claim_drawing.html")

        claimed_count = 0
        already_claimed_count = 0
        blocked_count = 0
        claimed_at = timezone.now()

        for project in projects:
            if project.owner_id is None:
                project.owner = request.user
                project.claimed_at = claimed_at
                project.save(update_fields=["owner", "claimed_at", "updated_at"])
                claimed_count += 1
            elif project.owner_id == request.user.id:
                already_claimed_count += 1
            else:
                blocked_count += 1

        if claimed_count == 1:
            messages.success(request, "Your drawing has been claimed successfully.")
        elif claimed_count > 1:
            messages.success(request, "Your drawings have been claimed successfully.")

        if already_claimed_count == 1 and claimed_count == 0:
            messages.info(request, "This drawing is already claimed by your account.")
        elif already_claimed_count > 1 and claimed_count == 0:
            messages.info(request, "These drawings are already claimed by your account.")

        if blocked_count:
            messages.error(
                request,
                "Some drawings could not be claimed because they already belong to another account.",
            )

        return redirect("my_drawings")

    return render(request, "account/claim_drawing.html")


@require_POST
def start_drawing(request):
    is_allowed, blocked_rule = rate_limit_drawing_creation(request)
    if not is_allowed:
        messages.error(
            request,
            (
                "Too many new drawings from this network. "
                f"Please try again after the {blocked_rule['label']} limit resets."
            ),
        )
        return redirect("home")

    pass_key = AnonymousDrawingSession.generate_pass_key()
    browser_token = request.COOKIES.get(
        BROWSER_COOKIE_NAME,
        AnonymousDrawingSession.generate_browser_token(),
    )

    drawing_session = AnonymousDrawingSession(browser_token=browser_token)
    drawing_session.set_pass_key(pass_key)
    drawing_session.save()

    project = DrawingProject.objects.create(session=drawing_session)

    response = render(
        request,
        "draw.html",
        {
            "project": project,
            "pass_key": pass_key,
            "is_new_project": True,
        },
    )
    response.set_cookie(
        BROWSER_COOKIE_NAME,
        browser_token,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="Lax",
    )
    return response


def drawing_detail(request, public_id):
    project = get_object_or_404(
        DrawingProject.objects.select_related("session"),
        public_id=public_id,
        session__is_active=True,
    )

    if not user_can_access_drawing(request, project):
        messages.error(request, "Please recover this drawing or login to the owner account.")
        return redirect("recover_drawing")

    project.session.mark_seen()

    return render(
        request,
        "draw.html",
        {
            "project": project,
            "pass_key": None,
            "is_new_project": False,
        },
    )


@require_POST
def save_drawing(request, public_id):
    project = get_object_or_404(
        DrawingProject.objects.select_related("session"),
        public_id=public_id,
        session__is_active=True,
    )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid drawing data."}, status=400)

    project.title = str(payload.get("title", project.title)).strip()[:120]
    project.drawing_data_json = payload.get("drawing_data_json", {})
    project.preview_image = payload.get("preview_image", "")
    project.save(update_fields=["title", "drawing_data_json", "preview_image", "updated_at"])
    project.session.mark_seen()

    return JsonResponse({"ok": True, "updated_at": project.updated_at.isoformat()})


@require_POST
def publish_drawing(request, public_id):
    project = get_object_or_404(
        DrawingProject.objects.select_related("session"),
        public_id=public_id,
        session__is_active=True,
    )

    if not project.preview_image:
        return JsonResponse(
            {"ok": False, "error": "Save your drawing before publishing."},
            status=400,
        )

    if not project.title.strip():
        return JsonResponse(
            {"ok": False, "error": "Add a title before publishing your drawing."},
            status=400,
        )

    project.publish()
    return JsonResponse(
        {
            "ok": True,
            "detail_url": request.build_absolute_uri(
                redirect("showcase_detail", public_id=project.public_id).url
            ),
        }
    )


@login_required(login_url="login")
@require_POST
def toggle_drawing_heart(request, public_id):
    if is_rate_limited(get_rate_limit_key("heart", request), **HEART_RATE_LIMIT):
        return JsonResponse(
            {
                "success": False,
                "error": "Too many heart actions. Please try again later.",
            },
            status=429,
        )

    with transaction.atomic():
        drawing = get_object_or_404(
            DrawingProject.objects.select_for_update(),
            public_id=public_id,
            is_published=True,
        )
        heart = DrawingHeart.objects.filter(drawing=drawing, user=request.user).first()

        if heart:
            heart.delete()
            DrawingProject.objects.filter(pk=drawing.pk, heart_count__gt=0).update(
                heart_count=F("heart_count") - 1
            )
            hearted = False
        else:
            DrawingHeart.objects.create(drawing=drawing, user=request.user)
            DrawingProject.objects.filter(pk=drawing.pk).update(
                heart_count=F("heart_count") + 1
            )
            hearted = True

        drawing.refresh_from_db(fields=["heart_count"])

    return JsonResponse(
        {
            "success": True,
            "hearted": hearted,
            "heart_count": drawing.heart_count,
        }
    )


@login_required(login_url="login")
@require_POST
def create_drawing_comment(request, public_id):
    project = get_object_or_404(
        DrawingProject,
        public_id=public_id,
        is_published=True,
    )
    body = request.POST.get("body", "").strip()

    if not body:
        messages.error(request, "Comment cannot be empty.")
        return redirect(comment_page_url(project.public_id, request.POST.get("comments_page")))

    if len(body) > COMMENT_BODY_MAX_LENGTH:
        messages.error(request, "Comment is too long.")
        return redirect(comment_page_url(project.public_id, request.POST.get("comments_page")))

    if is_rate_limited(get_rate_limit_key("comment", request), **COMMENT_RATE_LIMIT):
        messages.error(request, "You are commenting too quickly. Please try again later.")
        return redirect(comment_page_url(project.public_id, request.POST.get("comments_page")))

    with transaction.atomic():
        DrawingComment.objects.create(
            drawing=project,
            user=request.user,
            body=body,
        )
        DrawingProject.objects.filter(pk=project.pk).update(
            comment_count=F("comment_count") + 1
        )
        project.refresh_from_db(fields=["comment_count"])

    messages.success(request, "Your comment was posted.")
    return redirect(
        comment_page_url(
            project.public_id,
            get_last_comment_page_number(project.comment_count),
        )
    )


@login_required(login_url="login")
@require_POST
def delete_drawing_comment(request, comment_id):
    redirect_public_id = None
    requested_page = request.POST.get("comments_page")
    with transaction.atomic():
        comment = get_object_or_404(
            DrawingComment.objects.select_for_update().select_related("drawing", "user"),
            pk=comment_id,
            drawing__is_published=True,
        )
        redirect_public_id = comment.drawing.public_id

        if comment.user_id != request.user.id:
            messages.error(request, "You can only delete your own comments.")
            return redirect(comment_page_url(redirect_public_id, requested_page))

        was_countable = comment.is_countable
        if not comment.is_deleted_by_user:
            comment.body = ""
            comment.is_deleted_by_user = True
            comment.save(update_fields=["body", "is_deleted_by_user", "updated_at"])
            if was_countable:
                DrawingProject.objects.filter(
                    pk=comment.drawing_id,
                    comment_count__gt=0,
                ).update(comment_count=F("comment_count") - 1)
            messages.success(request, "Your comment was deleted.")
        else:
            messages.info(request, "This comment was already deleted.")

    return redirect(comment_page_url(redirect_public_id, requested_page))


@require_http_methods(["GET", "POST"])
def recover_drawing(request):
    if request.method == "POST":
        raw_pass_key = request.POST.get("pass_key", "").strip()

        if raw_pass_key:
            for drawing_session in AnonymousDrawingSession.objects.filter(is_active=True):
                if drawing_session.verify_pass_key(raw_pass_key):
                    project = drawing_session.projects.first()
                    if project:
                        remember_recovered_drawing_access(request, drawing_session, project)
                        drawing_session.mark_seen()
                        return redirect("drawing_detail", public_id=project.public_id)

        messages.error(request, "Invalid recovery key. Check the key and try again.")

    return render(request, "recover.html")


def showcase(request):
    featured_projects = list(DrawingProject.objects.filter(
        is_published=True,
        is_featured=True,
    ).order_by("featured_order", "-updated_at", "-published_at"))
    top_hearted_projects = list(DrawingProject.objects.filter(
        is_published=True,
        heart_count__gt=0,
    ).order_by("-heart_count", "-updated_at", "-published_at")[:5])
    latest_projects = DrawingProject.objects.filter(
        is_published=True,
        is_featured=False,
    ).order_by("-updated_at", "-published_at")
    paginator = Paginator(latest_projects, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    latest_page_projects = list(page_obj.object_list)
    hearted_drawing_ids = get_hearted_drawing_ids(
        request,
        [*featured_projects, *top_hearted_projects, *latest_page_projects],
    )

    return render(
        request,
        "showcase.html",
        {
            "featured_projects": featured_projects,
            "top_hearted_projects": top_hearted_projects,
            "latest_projects": latest_page_projects,
            "hearted_drawing_ids": hearted_drawing_ids,
            "page_obj": page_obj,
            "paginator": paginator,
        },
    )


def showcase_detail(request, public_id):
    project = get_object_or_404(
        DrawingProject.objects.select_related(
            "owner",
            "owner__masdraw_profile",
            "owner__masdraw_profile__profile_drawing",
        ),
        public_id=public_id,
        is_published=True,
    )
    comments_queryset = (
        project.comments.select_related(
            "user",
            "user__masdraw_profile",
            "user__masdraw_profile__profile_drawing",
        )
        .annotate(commenter_claimed_sketch_count=Count("user__masdraw_drawings", distinct=True))
        .order_by("created_at")
    )
    comments_paginator = Paginator(comments_queryset, COMMENT_PAGE_SIZE)
    comments_page_obj = comments_paginator.get_page(request.GET.get("comments_page"))
    owner_sketch_count = 0
    owner_total_hearts = 0
    if project.owner_id:
        owner_stats = DrawingProject.objects.filter(owner=project.owner).aggregate(
            sketch_count=Count("id"),
            total_hearts=Sum("heart_count"),
        )
        owner_sketch_count = owner_stats["sketch_count"] or 0
        owner_total_hearts = owner_stats["total_hearts"] or 0
    try:
        owner_profile = project.owner.masdraw_profile if project.owner_id else None
    except UserProfile.DoesNotExist:
        owner_profile = None

    user_has_hearted = (
        request.user.is_authenticated
        and DrawingHeart.objects.filter(drawing=project, user=request.user).exists()
    )
    return render(
        request,
        "showcase_detail.html",
        {
            "project": project,
            "comments": comments_page_obj.object_list,
            "comments_page_obj": comments_page_obj,
            "comments_paginator": comments_paginator,
            "owner_profile": owner_profile,
            "owner_sketch_count": owner_sketch_count,
            "owner_total_hearts": owner_total_hearts,
            "user_has_hearted": user_has_hearted,
        },
    )


def robots_txt(request):
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /draw/",
            "Disallow: /recover/",
            "Disallow: /3/admin/",
            "",
            f"Sitemap: {settings.PRIMARY_SITE_URL}/sitemap.xml",
            "",
            "User-agent: Amazonbot",
            "Disallow: /",
            "",
            "User-agent: Applebot-Extended",
            "Disallow: /",
            "",
            "User-agent: Bytespider",
            "Disallow: /",
            "",
            "User-agent: CCBot",
            "Disallow: /",
            "",
            "User-agent: ClaudeBot",
            "Disallow: /",
            "",
            "User-agent: Google-Extended",
            "Disallow: /",
            "",
            "User-agent: GPTBot",
            "Disallow: /",
            "",
            "User-agent: meta-externalagent",
            "Disallow: /",
            "",
        ]
    )
    return HttpResponse(content, content_type="text/plain")


def about(request):
    return render(request, "about.html")


def faq(request):
    return render(request, "faq.html")


def privacy_policy(request):
    return render(request, "privacy_policy.html")


def terms(request):
    return render(request, "terms.html")
