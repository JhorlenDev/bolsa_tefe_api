from django.db import migrations, models


def migrar_rg_para_rg_frente(apps, schema_editor):
    DocumentoAnexo = apps.get_model('api', 'DocumentoAnexo')
    DocumentoAnexo.objects.filter(tipo_documento='rg').update(tipo_documento='rg_frente')


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0013_familiamembro_escola_escola_model'),
    ]

    operations = [
        migrations.AlterField(
            model_name='documentoanexo',
            name='tipo_documento',
            field=models.CharField(
                choices=[
                    ('rg_frente', 'RG - Frente'),
                    ('rg_verso', 'RG - Verso'),
                    ('cpf', 'CPF'),
                    ('comprovante_residencia', 'Comprovante de residência'),
                    ('foto_residencia', 'Foto da residência'),
                    ('foto_ato_atualizacao', 'Foto do ato da atualização'),
                ],
                max_length=50,
            ),
        ),
        migrations.RunPython(migrar_rg_para_rg_frente, migrations.RunPython.noop),
    ]
