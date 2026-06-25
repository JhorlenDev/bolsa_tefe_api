from django.db import migrations, models


def normalize_pessoas_com_rendimento(apps, schema_editor):
    from api.services.status_atualizacao_service import salvar_status_atualizacao_cidadao

    Socioeconomico = apps.get_model('api', 'Socioeconomico')
    Cidadao = apps.get_model('api', 'Cidadao')
    socioeconomicos = Socioeconomico.objects.filter(pessoas_com_rendimento__lte=0)
    cidadao_ids = list(socioeconomicos.values_list('cidadao_id', flat=True))

    socioeconomicos.update(pessoas_com_rendimento=1)

    for cidadao in Cidadao.objects.filter(id__in=cidadao_ids).iterator():
        salvar_status_atualizacao_cidadao(cidadao)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0031_normalize_qtd_comodos_default'),
    ]

    operations = [
        migrations.AlterField(
            model_name='socioeconomico',
            name='pessoas_com_rendimento',
            field=models.IntegerField(default=1),
        ),
        migrations.RunPython(
            normalize_pessoas_com_rendimento,
            migrations.RunPython.noop,
        ),
    ]
