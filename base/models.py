import secrets
import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class AnonymousDrawingSession(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    pass_key_hash = models.CharField(max_length=255)
    browser_token = models.CharField(max_length=64, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Anonymous session {self.public_id}"

    @staticmethod
    def generate_pass_key():
        return secrets.token_urlsafe(12)

    @staticmethod
    def generate_browser_token():
        return secrets.token_urlsafe(32)

    def set_pass_key(self, raw_pass_key):
        self.pass_key_hash = make_password(raw_pass_key)

    def verify_pass_key(self, raw_pass_key):
        return check_password(raw_pass_key, self.pass_key_hash)

    def mark_seen(self):
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at", "updated_at"])


class DrawingProject(models.Model):
    session = models.ForeignKey(
        AnonymousDrawingSession,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="masdraw_drawings",
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=120, blank=True)
    drawing_data_json = models.JSONField(default=dict, blank=True)
    preview_image = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    heart_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    featured_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["is_published", "-published_at"]),
            models.Index(fields=["is_published", "is_featured", "featured_order", "-published_at"]),
        ]

    def __str__(self):
        return self.title or f"Anonymous drawing {self.public_id}"

    def publish(self):
        if not self.is_published:
            self.is_published = True
            self.published_at = timezone.now()
            self.save(update_fields=["is_published", "published_at", "updated_at"])


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="masdraw_profile",
    )
    profile_drawing = models.ForeignKey(
        DrawingProject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profile_picture_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def profile_image(self):
        if self.profile_drawing and self.profile_drawing.preview_image:
            return self.profile_drawing.preview_image
        return ""

    def __str__(self):
        return f"MasDraw profile for {self.user}"


class DrawingHeart(models.Model):
    drawing = models.ForeignKey(
        DrawingProject,
        on_delete=models.CASCADE,
        related_name="hearts",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="drawing_hearts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("drawing", "user")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} hearted {self.drawing}"


class DrawingComment(models.Model):
    drawing = models.ForeignKey(
        DrawingProject,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="drawing_comments",
    )
    body = models.TextField(max_length=500)
    is_hidden = models.BooleanField(default=False)
    is_deleted_by_user = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    @property
    def is_countable(self):
        return not self.is_hidden and not self.is_deleted_by_user

    def __str__(self):
        return f"Comment by {self.user} on {self.drawing}"
