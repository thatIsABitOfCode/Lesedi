import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
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
        user = self.model(email=self.normalize_email(email).lower(), **extra)
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
    """Account holder. A role never grants access to anyone else's private data on its own."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=80)
    phone = models.CharField(max_length=32, blank=True)
    preferred_language = models.CharField(max_length=8, default="en")
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.SURVIVOR)
    # Notifications to others always use neutral wording; this keeps the preference explicit and reviewable.
    neutral_notifications = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    def __str__(self):
        return self.email

    def get_short_name(self):
        return self.display_name

    @property
    def is_survivor(self):
        return self.role == Role.SURVIVOR
