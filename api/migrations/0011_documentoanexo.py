from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import uuid
import api.models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_familiamembro_nao_possui_cpf'),
    ]

    operations = [
        migrations.CreateModel(
            name='DocumentoAnexo',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sincronizado', models.BooleanField(default=False)),
                ('status_sincronizacao', models.CharField(choices=[('PENDENTE', 'Pendente'), ('SINCRONIZADO', 'Sincronizado'), ('ERRO', 'Erro')], default='PENDENTE', max_length=20)),
                ('sincronizado_em', models.DateTimeField(blank=True, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('tipo_documento', models.CharField(choices=[('rg', 'RG'), ('cpf', 'CPF'), ('comprovante_residencia', 'Comprovante de residência'), ('foto_residencia', 'Foto da residência'), ('foto_ato_atualizacao', 'Foto do ato da atualização')], max_length=50)),
                ('arquivo', models.FileField(upload_to=api.models.documento_anexo_upload_to, validators=[django.core.validators.FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])])),
                ('nome_arquivo', models.CharField(max_length=255)),
                ('extensao', models.CharField(max_length=10)),
                ('tamanho_bytes', models.PositiveBigIntegerField(default=0)),
                ('data_envio', models.DateTimeField(auto_now_add=True)),
                ('status', models.CharField(default='ENVIADO', max_length=30)),
                ('cidadao', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documentos_anexados', to='api.cidadao')),
            ],
            options={
                'db_table': 'api_documentos_anexos',
            },
        ),
        migrations.AddConstraint(
            model_name='documentoanexo',
            constraint=models.UniqueConstraint(fields=('cidadao', 'tipo_documento'), name='uq_documento_anexo_cidadao_tipo'),
        ),
    ]
