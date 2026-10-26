import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    """Roles are labels for what a person may do on the platform.

    No role grants access to another person's private data. Access to a
    survivor's information only ever comes from explicit permissions the
    survivor grants (apps.safety_circle) or explicit evidence shares.
    """

    SURVIVOR = "survivor", "Survivor / account owner"
    TRUSTED_CONTACT = "trusted_contact", "Trusted contact"
    COMMUNITY_RESPONDER = "community_responder", "Community responder"
    MODERATOR = "moderator", "Moderator"
    ADMIN = "admin", "Administrator"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=80)
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.SURVIVOR)
    phone = models.CharField(max_length=32, blank=True)

    # Preferences
    language = models.CharField(max_length=8, default="en")
    low_data_mode = models.BooleanField(default=False)
    neutral_notifications = models.BooleanField(
        default=True,
        help_text="Keep alerts to your contacts free of names and details. Recommended.",
    )

    # Incremented by "sign out everywhere"; sessions carrying an older value are ended.
    session_version = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    def __str__(self):
        return self.display_name or self.email


class UserConsent(models.Model):
    class Kind(models.TextChoices):
        TERMS_AND_DISCLAIMER = "terms_disclaimer", "Terms and safety disclaimer"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consents")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    version = models.CharField(max_length=32)
    accepted_at = models.DateTimeField(auto_now_add=True)


class DataDeletionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deletion_requests")
    requested_at = models.DateTimeField(auto_now_add=True)
    execute_after = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="pending"),
                name="one_pending_deletion_per_user",
            )
        ]
