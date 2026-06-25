from django.db import migrations, models


def recalcular_status(apps, schema_editor):
    from api.services.status_atualizacao_service import salvar_status_atualizacao_cidadao

    Cidadao = apps.get_model('api', 'Cidadao')
    for cidadao in (
        Cidadao.objects.select_related(
            'documentos',
            'endereco',
            'socioeconomico',
            'termo_responsabilidade',
        )
        .prefetch_related('documentos_anexados')
        .iterator(chunk_size=500)
    ):
        salvar_status_atualizacao_cidadao(cidadao)


def voltar_pendentes(apps, schema_editor):
    Cidadao = apps.get_model('api', 'Cidadao')
    Cidadao.objects.filter(status_atualizacao='DESATUALIZADO').update(
        status_atualizacao='PENDENTE'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0032_normalize_pessoas_com_rendimento_default'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cidadao',
            name='estado_civil',
            field=models.CharField(
                blank=True,
                choices=[
                    ('SOLTEIRO', 'Solteiro'),
                    ('CASADO', 'Casado'),
                    ('DIVORCIADO', 'Divorciado'),
                    ('VIUVO', 'Viúvo'),
                    ('UNIAO_ESTAVEL', 'União estável'),
                    ('NAO_INFORMADO', 'Não informado'),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='cidadao',
            name='status_atualizacao',
            field=models.CharField(
                choices=[
                    ('PENDENTE', 'Pendente'),
                    ('ATUALIZADO', 'Atualizado'),
                    ('DESATUALIZADO', 'Desatualizado'),
                ],
                db_index=True,
                default='PENDENTE',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='abastecimento_agua',
            field=models.CharField(
                blank=True,
                choices=[
                    ('REDE_PUBLICA', 'Rede pública'),
                    ('POCO', 'Poço'),
                    ('NASCENTE', 'Nascente'),
                    ('CISTERNA', 'Cisterna'),
                    ('CACIMBA', 'Cacimba'),
                    ('OUTRO', 'Outro'),
                    ('NAO_INFORMADO', 'Não informado'),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='situacao_imovel',
            field=models.CharField(
                blank=True,
                choices=[
                    ('PROPRIA', 'Própria'),
                    ('ALUGADA', 'Alugada'),
                    ('CEDIDA', 'Cedida'),
                    ('TEMPORARIA', 'Temporária'),
                    ('NAO_INFORMADO', 'Não informado'),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.RunPython(recalcular_status, voltar_pendentes),
    ]
