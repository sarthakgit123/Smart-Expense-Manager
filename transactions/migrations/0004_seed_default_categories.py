from django.db import migrations

DEFAULT_CATEGORIES = [
    # Income Categories
    ('Salary', 'IN'),
    ('Freelance & Consulting', 'IN'),
    ('Investments & Dividends', 'IN'),
    ('Business Revenue', 'IN'),
    ('Gifts & Grants', 'IN'),
    ('Other Income', 'IN'),
    # Expense Categories
    ('Food & Dining', 'EX'),
    ('Groceries', 'EX'),
    ('Housing & Rent', 'EX'),
    ('Utilities & Bills', 'EX'),
    ('Transportation & Fuel', 'EX'),
    ('Healthcare & Fitness', 'EX'),
    ('Entertainment & Leisure', 'EX'),
    ('Shopping & Personal', 'EX'),
    ('Education & Learning', 'EX'),
    ('Travel & Vacations', 'EX'),
    ('Savings & Investments', 'EX'),
    ('Miscellaneous', 'EX'),
]

def seed_default_categories(apps, schema_editor):
    Category = apps.get_model('transactions', 'Category')
    for name, cat_type in DEFAULT_CATEGORIES:
        Category.objects.get_or_create(
            user=None,
            name=name,
            category_type=cat_type,
            defaults={'is_default': True}
        )

def unseed_default_categories(apps, schema_editor):
    Category = apps.get_model('transactions', 'Category')
    for name, cat_type in DEFAULT_CATEGORIES:
        Category.objects.filter(user=None, name=name, category_type=cat_type, is_default=True).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0003_category_is_default_alter_category_user'),
    ]

    operations = [
        migrations.RunPython(seed_default_categories, unseed_default_categories),
    ]
