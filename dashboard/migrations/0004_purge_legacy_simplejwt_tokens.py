from django.db import migrations


def purge_legacy_simplejwt_tokens(apps, schema_editor):
    """Remove complete refresh JWTs stored by the old auth flow."""

    OutstandingToken = apps.get_model(
        "token_blacklist",
        "OutstandingToken",
    )
    OutstandingToken.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        (
            "dashboard",
            "0003_refreshtokenfamily_hashedrefreshtoken",
        ),
        (
            "token_blacklist",
            "0013_alter_blacklistedtoken_options_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            purge_legacy_simplejwt_tokens,
            migrations.RunPython.noop,
        ),
    ]
