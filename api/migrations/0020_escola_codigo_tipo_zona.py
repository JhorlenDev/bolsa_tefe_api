from django.db import migrations, models


def seed_escola_flora_agricola(apps, schema_editor):
    Escola = apps.get_model('api', 'Escola')
    Escola.objects.update_or_create(
        codigo='13013114',
        defaults={
            'nome': 'ESCOLA MUN RURAL FLORA AGRICOLA',
            'tipo': 'MUNICIPAL',
            'zona': 'RURAL',
            'sincronizado': True,
            'status_sincronizacao': 'SINCRONIZADO',
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0019_backfill_endereco_rural_localidade'),
    ]

    operations = [
        migrations.AddField(
            model_name='escola',
            name='codigo',
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='escola',
            name='tipo',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='escola',
            name='zona',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.RunPython(seed_escola_flora_agricola, migrations.RunPython.noop),
    ]
