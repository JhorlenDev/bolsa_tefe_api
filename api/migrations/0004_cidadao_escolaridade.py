from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_migrate_beneficio_to_uuid'),
    ]

    operations = [
        migrations.AddField(
            model_name='cidadao',
            name='escolaridade',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
