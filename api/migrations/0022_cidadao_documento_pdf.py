from django.db import migrations, models
import django.core.validators
import api.models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0021_alter_keycloakuserdata_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='cidadao',
            name='documento_pdf',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to=api.models.documento_pdf_upload_to,
                validators=[django.core.validators.FileExtensionValidator(['pdf'])],
            ),
        ),
    ]
