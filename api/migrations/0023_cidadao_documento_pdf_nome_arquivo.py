from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0022_cidadao_documento_pdf'),
    ]

    operations = [
        migrations.AddField(
            model_name='cidadao',
            name='documento_pdf_nome_arquivo',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
