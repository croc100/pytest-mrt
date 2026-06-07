# Reference migration: matches the pattern that `mrt fix` generates for RemoveField.
# Used by test_django_fixer_e2e.py to verify that the generated code pattern
# actually executes correctly against a real database.
from django.db import migrations

_MRT_TABLE = "_mrt_backups"
_MRT_CHUNK = 500


def __mrt_enc(v):
    import base64
    from datetime import date, datetime, time
    from decimal import Decimal
    from uuid import UUID

    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v
    if isinstance(v, Decimal):
        return "D:" + str(v)
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            return "DTs:" + str(v.timestamp())
        return "DT:" + v.isoformat()
    if isinstance(v, date):
        return "d:" + v.isoformat()
    if isinstance(v, time):
        return "t:" + v.isoformat()
    if isinstance(v, UUID):
        return "U:" + str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "B:" + base64.b64encode(bytes(v)).decode()
    s = str(v)
    for prefix in ("D:", "DT:", "DTs:", "d:", "t:", "U:", "B:", "S:"):
        if s.startswith(prefix):
            return "S:" + s
    return s


def __mrt_dec(v):
    import base64
    from datetime import date, datetime, time
    from decimal import Decimal
    from uuid import UUID

    if not isinstance(v, str):
        return v
    if v.startswith("D:"):
        return Decimal(v[2:])
    if v.startswith("DTs:"):
        return datetime.fromtimestamp(float(v[4:]))
    if v.startswith("DT:"):
        return datetime.fromisoformat(v[3:])
    if v.startswith("d:"):
        return date.fromisoformat(v[2:])
    if v.startswith("t:"):
        return time.fromisoformat(v[2:])
    if v.startswith("U:"):
        return UUID(v[2:])
    if v.startswith("B:"):
        return base64.b64decode(v[2:])
    if v.startswith("S:"):
        return v[2:]
    return v


_MRT_LABEL_contact_phone = "0002_remove_phone__contact_phone"


def _backup_contact_phone(apps, schema_editor):
    import json

    from django.db import connection

    Contact = apps.get_model("django_fixer_app", "Contact")
    with connection.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS " + _MRT_TABLE + " "
            "(migration_label TEXT NOT NULL, object_id TEXT NOT NULL, payload TEXT)"
        )
        cur.execute(
            "DELETE FROM " + _MRT_TABLE + " WHERE migration_label = %s",
            [_MRT_LABEL_contact_phone],
        )
    last_pk = None
    while True:
        qs = Contact.objects.order_by("pk")
        if last_pk is not None:
            qs = qs.filter(pk__gt=last_pk)
        batch = list(qs.values_list("pk", "phone")[:_MRT_CHUNK])
        if not batch:
            break
        with connection.cursor() as cur:
            for pk, val in batch:
                cur.execute(
                    "INSERT INTO " + _MRT_TABLE + " VALUES (%s, %s, %s)",
                    [
                        _MRT_LABEL_contact_phone,
                        json.dumps(__mrt_enc(pk)),
                        json.dumps(__mrt_enc(val)),
                    ],
                )
        last_pk = batch[-1][0]


def _restore_contact_phone(apps, schema_editor):
    import json

    from django.db import connection

    Contact = apps.get_model("django_fixer_app", "Contact")
    with connection.cursor() as cur:
        cur.execute(
            "SELECT object_id, payload FROM " + _MRT_TABLE + " WHERE migration_label = %s",
            [_MRT_LABEL_contact_phone],
        )
        rows = cur.fetchall()
    for pk_raw, val_raw in rows:
        pk = __mrt_dec(json.loads(pk_raw))
        val = __mrt_dec(json.loads(val_raw))
        Contact.objects.filter(pk=pk).update(phone=val)
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM " + _MRT_TABLE + " WHERE migration_label = %s",
            [_MRT_LABEL_contact_phone],
        )


class Migration(migrations.Migration):
    dependencies = [("django_fixer_app", "0001_initial")]

    operations = [
        migrations.RunPython(_backup_contact_phone, _restore_contact_phone),
        migrations.RemoveField(model_name="Contact", name="phone"),
    ]
