from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('pandoraapp', '0003_database_safeguards')]
    operations = [migrations.AddField(model_name='operatingexpense', name='request_id',
        field=models.UUIDField(null=True, blank=True, unique=True, editable=False))]
