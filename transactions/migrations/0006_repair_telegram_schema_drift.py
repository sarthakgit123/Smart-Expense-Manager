"""
Repair databases that applied an early draft of 0005_telegram_models.

The draft created:
  * TelegramLinkCode.code as varchar(12)   (current code generates 16 chars)
  * TelegramMessage.update_id UNIQUE        (current model: message_id, unique
                                             per telegram_user_id)

Django will not re-run an applied migration, so those databases kept the old
shape and fail with "value too long for type character varying(12)".

This migration inspects the live PostgreSQL schema and only changes what is
still in the draft shape. It is a no-op on SQLite and on databases created from
the final 0005, and it does not change Django's migration state (0005 already
describes the correct models).
"""
from django.db import migrations

LINKCODE = 'transactions_telegramlinkcode'
MESSAGE = 'transactions_telegrammessage'
UNIQUE_NAME = 'unique_telegram_message_per_user'


def _columns(cursor, table):
    cursor.execute(
        """
        SELECT column_name, character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        """,
        [table],
    )
    return dict(cursor.fetchall())


def _constraint_exists(cursor, table, name):
    cursor.execute(
        """
        SELECT 1 FROM pg_constraint
        WHERE conrelid = %s::regclass AND conname = %s
        """,
        [table, name],
    )
    return cursor.fetchone() is not None


def repair(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    with schema_editor.connection.cursor() as cursor:
        # 1. Link code column must hold 16-character codes.
        code_len = _columns(cursor, LINKCODE).get('code')
        if code_len is not None and code_len < 16:
            cursor.execute(f'ALTER TABLE {LINKCODE} ALTER COLUMN code TYPE varchar(16)')

        # 2. TelegramMessage: update_id (globally unique) -> message_id (unique per user).
        cols = _columns(cursor, MESSAGE)
        if 'update_id' in cols and 'message_id' not in cols:
            # Drop every single-column UNIQUE constraint on update_id (name may vary).
            cursor.execute(
                """
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                WHERE c.conrelid = %s::regclass
                  AND c.contype = 'u'
                  AND array_length(c.conkey, 1) = 1
                  AND a.attname = 'update_id'
                """,
                [MESSAGE],
            )
            for (conname,) in cursor.fetchall():
                cursor.execute(f'ALTER TABLE {MESSAGE} DROP CONSTRAINT "{conname}"')
            cursor.execute(f'ALTER TABLE {MESSAGE} RENAME COLUMN update_id TO message_id')

        if 'message_id' in _columns(cursor, MESSAGE) and not _constraint_exists(cursor, MESSAGE, UNIQUE_NAME):
            cursor.execute(
                f'ALTER TABLE {MESSAGE} ADD CONSTRAINT {UNIQUE_NAME} '
                f'UNIQUE (telegram_user_id, message_id)'
            )


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0005_telegram_models'),
    ]

    operations = [
        migrations.RunPython(repair, migrations.RunPython.noop),
    ]
