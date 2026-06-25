from django.db import migrations, models
import django.core.validators
import api.models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0029_touch_cidadao_status_atualizacao'),
    ]

    operations = [
        migrations.AlterField(
            model_name='documentoanexo',
            name='arquivo',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to=api.models.documento_anexo_upload_to,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        ['jpg', 'jpeg', 'png', 'pdf']
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name='documentoanexo',
            name='sem_documento_no_momento',
            field=models.BooleanField(default=False),
        ),
    ]
