from django.db import migrations, models


def normalize_qtd_comodos(apps, schema_editor):
    from api.services.status_atualizacao_service import salvar_status_atualizacao_cidadao

    Endereco = apps.get_model('api', 'Endereco')
    Cidadao = apps.get_model('api', 'Cidadao')
    enderecos = Endereco.objects.filter(qtd_comodos__isnull=True) | Endereco.objects.filter(
        qtd_comodos__lte=0
    )
    cidadao_ids = list(enderecos.values_list('cidadao_id', flat=True))

    enderecos.update(qtd_comodos=1)

    for cidadao in Cidadao.objects.filter(id__in=cidadao_ids).iterator():
        salvar_status_atualizacao_cidadao(cidadao)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0030_documentoanexo_sem_documento_no_momento'),
    ]

    operations = [
        migrations.AlterField(
            model_name='endereco',
            name='qtd_comodos',
            field=models.IntegerField(blank=True, default=1, null=True),
        ),
        migrations.RunPython(normalize_qtd_comodos, migrations.RunPython.noop),
    ]
