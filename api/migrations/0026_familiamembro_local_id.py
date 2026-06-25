from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0025_add_sync_updated_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='familiamembro',
            name='local_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
