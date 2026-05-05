from django.db import migrations, models


RURAL_BAIRROS_LEGADOS = {'Caiambé', 'Área Rural de Tefé'}


def popular_campos_endereco(apps, schema_editor):
    Endereco = apps.get_model('api', 'Endereco')

    for endereco in Endereco.objects.all().iterator():
        bairro = (endereco.bairro or '').strip()
        distrito = (getattr(endereco, 'distrito', None) or '').strip()
        comunidade_localidade = (
            getattr(endereco, 'comunidade_localidade', None) or ''
        ).strip()
        tipo_localizacao = (getattr(endereco, 'tipo_localizacao', None) or '').strip()

        is_rural = (
            tipo_localizacao == 'RURAL_DISTRITO'
            or bairro in RURAL_BAIRROS_LEGADOS
            or bool(distrito)
        )

        changed_fields = []

        if not tipo_localizacao:
            endereco.tipo_localizacao = 'RURAL_DISTRITO' if is_rural else 'URBANO'
            changed_fields.append('tipo_localizacao')

        if endereco.tipo_localizacao == 'RURAL_DISTRITO':
            if not distrito and bairro in RURAL_BAIRROS_LEGADOS:
                endereco.distrito = bairro
                changed_fields.append('distrito')
            if bairro:
                endereco.bairro = ''
                changed_fields.append('bairro')
            if not comunidade_localidade:
                endereco.comunidade_localidade = None
                changed_fields.append('comunidade_localidade')
        else:
            if distrito:
                endereco.distrito = None
                changed_fields.append('distrito')
            if comunidade_localidade:
                endereco.comunidade_localidade = None
                changed_fields.append('comunidade_localidade')

        if changed_fields:
            endereco.save(update_fields=changed_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_documentoanexo'),
    ]

    operations = [
        migrations.AddField(
            model_name='endereco',
            name='comunidade_localidade',
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AddField(
            model_name='endereco',
            name='distrito',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='endereco',
            name='tipo_localizacao',
            field=models.CharField(
                blank=True,
                choices=[('URBANO', 'Urbano'), ('RURAL_DISTRITO', 'Rural/Distrito')],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='bairro',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.RunPython(
            popular_campos_endereco,
            migrations.RunPython.noop,
        ),
    ]
