from django.core.management.base import BaseCommand
from transactions.models import Category, DEFAULT_CATEGORIES


class Command(BaseCommand):
    help = 'Seeds or re-seeds system default categories for income and expenses.'

    def handle(self, *args, **options):
        self.stdout.write("Seeding default categories...")
        created_count = 0
        existing_count = 0

        for name, cat_type in DEFAULT_CATEGORIES:
            cat, created = Category.objects.get_or_create(
                user=None,
                name=name,
                category_type=cat_type,
                defaults={'is_default': True}
            )
            if not cat.is_default:
                cat.is_default = True
                cat.save(update_fields=['is_default'])

            if created:
                created_count += 1
            else:
                existing_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded default categories: {created_count} created, {existing_count} already existed."
            )
        )
