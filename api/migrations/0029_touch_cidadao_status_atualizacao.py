from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    Cidadao = apps.get_model('api', 'Cidadao')
    Cidadao.objects.update(atualizado_em=timezone.now())


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0028_cidadao_status_atualizacao'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
