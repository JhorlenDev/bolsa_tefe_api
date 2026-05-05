from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0023_cidadao_documento_pdf_nome_arquivo'),
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
                    ('certidao_nascimento', 'Certidão de Nascimento'),
                    ('certidao_casamento', 'Certidão de Casamento'),
                    ('quitacao_eleitoral', 'Quitação Eleitoral'),
                    ('comprovante_residencia', 'Comprovante de residência'),
                    ('foto_residencia', 'Foto da residência'),
                    ('foto_ato_atualizacao', 'Foto do ato da atualização'),
                ],
                max_length=50,
            ),
        ),
    ]
