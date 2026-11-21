"""Create Pandora's standard role groups and synchronize their app permissions."""

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


# Keep these codenames aligned with the approved matrix and the checks in
# services.py, views.py, and business_views.py. Transaction records are not
# deletable through these groups; completed history must remain immutable.
ROLE_PERMISSIONS = {
    "Admin": {
        "category": {"add", "change", "delete", "view"},
        "product": {"add", "change", "delete", "view"},
        "supplier": {"add", "change", "delete", "view"},
        "purchase": {"add", "change", "view"},
        "sale": {"add", "change", "view"},
        "expensecategory": {"add", "change", "view"},
        "operatingexpense": {"add", "change", "view"},
        "stockmovement": {"view"},
    },
    "Inventory Staff": {
        "category": {"add", "change", "delete", "view"},
        "product": {"add", "change", "delete", "view"},
        "supplier": {"add", "change", "delete", "view"},
        "purchase": {"add", "change", "view"},
        "stockmovement": {"view"},
    },
    "Cashier": {
        "category": {"view"},
        "product": {"view"},
        "sale": {"add", "change", "view"},
    },
}


def required_codenames():
    """Return app permission codenames, checking that expected models exist."""
    result = {}
    for role, models in ROLE_PERMISSIONS.items():
        codenames = set()
        for model_name, actions in models.items():
            try:
                model = apps.get_model("pandoraapp", model_name)
            except LookupError as exc:
                raise CommandError(
                    f"Expected pandoraapp model '{model_name}' is not installed."
                ) from exc
            codenames.update(f"{action}_{model._meta.model_name}" for action in actions)
        result[role] = codenames
    return result


class Command(BaseCommand):
    help = "Create/synchronize the Admin, Inventory Staff, and Cashier groups."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show the planned group permissions without changing the database.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        planned = required_codenames()
        all_codenames = set().union(*planned.values())
        permissions = {
            permission.codename: permission
            for permission in Permission.objects.filter(
                content_type__app_label="pandoraapp",
                codename__in=all_codenames,
            ).select_related("content_type")
        }
        missing = all_codenames - permissions.keys()
        if missing:
            raise CommandError(
                "Pandora permissions are missing. Apply migrations first; missing: "
                + ", ".join(sorted(missing))
            )

        for role, codenames in planned.items():
            names = sorted(codenames)
            if options["dry_run"]:
                self.stdout.write(f"{role}: {', '.join(names)}")
                continue
            group, created = Group.objects.get_or_create(name=role)
            group.permissions.set([permissions[codename] for codename in codenames])
            verb = "Created" if created else "Synchronized"
            self.stdout.write(self.style.SUCCESS(f"{verb} {role} ({len(codenames)} permissions)."))

        if options["dry_run"]:
            self.stdout.write("Dry run only; no groups or permissions were changed.")
