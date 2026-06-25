from django.db import migrations
from django.db.models.functions import Coalesce


SYNCED_MODELS = (
    'Cidadao',
    'Documento',
    'DocumentoAnexo',
    'Endereco',
    'FamiliaMembro',
    'Escola',
    'LocalTefe',
    'Localidade',
    'Rua',
    'Socioeconomico',
    'TermoResponsabilidade',
    'Beneficio',
    'Beneficiario',
)


def forwards(apps, schema_editor):
    for model_name in SYNCED_MODELS:
        model = apps.get_model('api', model_name)
        model.objects.all().update(
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
            sincronizado_em=Coalesce('sincronizado_em', 'atualizado_em'),
        )


def backwards(apps, schema_editor):
    # Não há como reconstruir com segurança o estado local anterior.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0026_familiamembro_local_id'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
