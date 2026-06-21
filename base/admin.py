from django.contrib import admin
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from base.models import (
    AnonymousDrawingSession,
    DrawingComment,
    DrawingHeart,
    DrawingProject,
    UserProfile,
)


def refresh_comment_counts(drawing_ids):
    drawing_ids = {drawing_id for drawing_id in drawing_ids if drawing_id}
    if not drawing_ids:
        return

    visible_counts = {
        row["drawing_id"]: row["total"]
        for row in DrawingComment.objects.filter(
            drawing_id__in=drawing_ids,
            is_hidden=False,
            is_deleted_by_user=False,
        )
        .values("drawing_id")
        .annotate(total=Count("id"))
    }

    for drawing_id in drawing_ids:
        DrawingProject.objects.filter(pk=drawing_id).update(
            comment_count=visible_counts.get(drawing_id, 0)
        )


@admin.action(description="Hide selected comments")
def hide_selected_comments(modeladmin, request, queryset):
    with transaction.atomic():
        comments = queryset.select_for_update().only(
            "id",
            "drawing_id",
            "is_hidden",
            "is_deleted_by_user",
        )
        for comment in comments:
            if comment.is_hidden:
                continue
            if not comment.is_deleted_by_user:
                DrawingProject.objects.filter(
                    pk=comment.drawing_id,
                    comment_count__gt=0,
                ).update(comment_count=F("comment_count") - 1)
            comment.is_hidden = True
            comment.save(update_fields=["is_hidden", "updated_at"])


@admin.action(description="Unhide selected comments")
def unhide_selected_comments(modeladmin, request, queryset):
    with transaction.atomic():
        comments = queryset.select_for_update().only(
            "id",
            "drawing_id",
            "is_hidden",
            "is_deleted_by_user",
        )
        for comment in comments:
            if not comment.is_hidden:
                continue
            if not comment.is_deleted_by_user:
                DrawingProject.objects.filter(pk=comment.drawing_id).update(
                    comment_count=F("comment_count") + 1
                )
            comment.is_hidden = False
            comment.save(update_fields=["is_hidden", "updated_at"])


@admin.action(description="Publish selected drawings")
def publish_selected_drawings(modeladmin, request, queryset):
    now = timezone.now()
    with transaction.atomic():
        queryset.filter(published_at__isnull=True).update(
            is_published=True,
            published_at=now,
        )
        queryset.filter(published_at__isnull=False).update(is_published=True)


@admin.action(description="Unpublish selected drawings")
def unpublish_selected_drawings(modeladmin, request, queryset):
    queryset.update(is_published=False)


@admin.action(description="Feature selected drawings")
def feature_selected_drawings(modeladmin, request, queryset):
    queryset.update(is_featured=True)


@admin.action(description="Unfeature selected drawings")
def unfeature_selected_drawings(modeladmin, request, queryset):
    queryset.update(is_featured=False)


@admin.register(AnonymousDrawingSession)
class AnonymousDrawingSessionAdmin(admin.ModelAdmin):
    list_display = ("public_id", "is_active", "last_seen_at", "created_at")
    list_filter = ("is_active", "created_at", "updated_at")
    search_fields = ("public_id", "browser_token")
    readonly_fields = ("public_id", "created_at", "updated_at", "last_seen_at")


@admin.register(DrawingProject)
class DrawingProjectAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "public_id",
        "owner",
        "is_published",
        "is_featured",
        "heart_count",
        "comment_count",
        "published_at",
        "updated_at",
    )
    list_filter = ("is_published", "is_featured", "owner", "created_at", "published_at")
    search_fields = ("public_id", "title", "owner__username")
    readonly_fields = (
        "public_id",
        "heart_count",
        "comment_count",
        "created_at",
        "updated_at",
        "published_at",
        "claimed_at",
    )
    ordering = ("-updated_at",)
    actions = (
        publish_selected_drawings,
        unpublish_selected_drawings,
        feature_selected_drawings,
        unfeature_selected_drawings,
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "profile_drawing", "updated_at")
    search_fields = ("user__username", "profile_drawing__title", "profile_drawing__public_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DrawingHeart)
class DrawingHeartAdmin(admin.ModelAdmin):
    list_display = ("drawing", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("drawing__title", "drawing__public_id", "user__username")
    readonly_fields = ("created_at",)


@admin.register(DrawingComment)
class DrawingCommentAdmin(admin.ModelAdmin):
    list_display = (
        "drawing",
        "user",
        "short_body",
        "is_hidden",
        "is_deleted_by_user",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_hidden", "is_deleted_by_user", "created_at", "updated_at")
    search_fields = ("body", "drawing__title", "drawing__public_id", "user__username")
    readonly_fields = ("created_at", "updated_at")
    actions = (hide_selected_comments, unhide_selected_comments)

    def short_body(self, obj):
        return obj.body[:60] if obj.body else "Removed"

    def save_model(self, request, obj, form, change):
        drawing_ids = {obj.drawing_id}
        if change:
            old_comment = DrawingComment.objects.only("drawing_id").get(pk=obj.pk)
            drawing_ids.add(old_comment.drawing_id)

        super().save_model(request, obj, form, change)
        refresh_comment_counts(drawing_ids)
