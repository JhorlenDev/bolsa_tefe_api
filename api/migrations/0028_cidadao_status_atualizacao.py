from django.db import migrations, models


def forwards(apps, schema_editor):
    Cidadao = apps.get_model('api', 'Cidadao')
    from api.services.status_atualizacao_service import salvar_status_atualizacao_cidadao

    queryset = (
        Cidadao.objects.select_related(
            'documentos',
            'endereco',
            'socioeconomico',
            'termo_responsabilidade',
        ).prefetch_related('documentos_anexados')
    )

    for cidadao in queryset.iterator(chunk_size=200):
        salvar_status_atualizacao_cidadao(cidadao)


def backwards(apps, schema_editor):
    Cidadao = apps.get_model('api', 'Cidadao')
    Cidadao.objects.update(status_atualizacao='PENDENTE')


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0027_normalize_sync_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='cidadao',
            name='status_atualizacao',
            field=models.CharField(
                choices=[('PENDENTE', 'Pendente'), ('ATUALIZADO', 'Atualizado')],
                default='PENDENTE',
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
