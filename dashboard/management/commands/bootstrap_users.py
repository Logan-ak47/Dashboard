import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create or update the production admin and viewer accounts."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        admin_password = os.environ.get(
            "OPSBOARD_ADMIN_PASSWORD"
        )
        viewer_password = os.environ.get(
            "OPSBOARD_VIEWER_PASSWORD"
        )

        if not admin_password:
            raise CommandError(
                "OPSBOARD_ADMIN_PASSWORD must be set."
            )

        if not viewer_password:
            raise CommandError(
                "OPSBOARD_VIEWER_PASSWORD must be set."
            )
        User = get_user_model()

        admin_username = os.environ.get(
            "OPSBOARD_ADMIN_USERNAME",
            "opsboard-admin",
        )

        admin_user, admin_created = User.objects.update_or_create(
            username=admin_username,
            defaults={
                "is_active": True,
                "is_staff": True,
                "is_superuser": True,
            },
        )

        admin_user.set_password(admin_password)
        admin_user.save(update_fields=["password"])

        admin_action = (
            "Created" if admin_created else "Updated"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{admin_action} administrator: "
                f"{admin_user.username}"
            )
        )

        viewer_group, _ = Group.objects.get_or_create(
            name="Viewer"
        )

        viewer_permissions = Permission.objects.filter(
            content_type__app_label="dashboard",
            codename__in=[
                "view_transaction",
                "view_dailymetric",
            ],
        )

        if viewer_permissions.count() != 2:
            raise CommandError(
                "Expected dashboard view permissions were not found."
            )

        viewer_group.permissions.set(viewer_permissions)

        viewer_username = os.environ.get(
            "OPSBOARD_VIEWER_USERNAME",
            "opsboard-viewer",
        )

        viewer_user, viewer_created = User.objects.update_or_create(
            username=viewer_username,
            defaults={
                "is_active": True,
                "is_staff": True,
                "is_superuser": False,
            },
        )

        viewer_user.set_password(viewer_password)
        viewer_user.save(update_fields=["password"])

        viewer_user.groups.set([viewer_group])
        viewer_user.user_permissions.clear()

        viewer_action = (
            "Created" if viewer_created else "Updated"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{viewer_action} viewer: "
                f"{viewer_user.username}"
            )
        )

