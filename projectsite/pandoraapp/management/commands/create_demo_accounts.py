"""Create one demo login per Pandora role and let the operator type each password.

Run configure_pandora_roles first. Passwords are typed at the prompt and are
never stored in code or printed.
"""

from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# username: (role group, can open Django admin for catalog/supplier management)
DEMO_ACCOUNTS = {
    "admin_demo": ("Admin", True),
    "inventory_demo": ("Inventory Staff", True),
    "cashier_demo": ("Cashier", False),
}


class Command(BaseCommand):
    help = "Create or update the admin_demo, inventory_demo and cashier_demo accounts."

    def ask_password(self, user):
        while True:
            first = getpass(f"Password for {user.username}: ")
            if first != getpass(f"Repeat password for {user.username}: "):
                self.stderr.write("Passwords did not match. Try again.")
                continue
            try:
                validate_password(first, user)
            except ValidationError as exc:
                self.stderr.write(" ".join(exc.messages))
                continue
            return first

    def handle(self, *args, **options):
        groups = {g.name: g for g in Group.objects.filter(
            name__in={role for role, _ in DEMO_ACCOUNTS.values()})}
        missing = {role for role, _ in DEMO_ACCOUNTS.values()} - groups.keys()
        if missing:
            raise CommandError("Run 'python manage.py configure_pandora_roles' first. Missing: "
                               + ", ".join(sorted(missing)))
        User = get_user_model()
        for username, (role, staff) in DEMO_ACCOUNTS.items():
            user, created = User.objects.get_or_create(username=username)
            password = self.ask_password(user)
            with transaction.atomic():
                user.is_active = True
                user.is_staff = staff
                user.is_superuser = False
                user.set_password(password)
                user.save()
                user.groups.set([groups[role]])
            verb = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{verb} {username} ({role})."))
