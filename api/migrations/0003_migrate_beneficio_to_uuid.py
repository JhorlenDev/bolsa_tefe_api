import uuid

from django.db import migrations, models


FORWARD_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE api_beneficio
    ADD COLUMN IF NOT EXISTS uuid_id uuid,
    ADD COLUMN IF NOT EXISTS sincronizado boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS status_sincronizacao varchar(20) NOT NULL DEFAULT 'PENDENTE',
    ADD COLUMN IF NOT EXISTS sincronizado_em timestamp with time zone NULL,
    ADD COLUMN IF NOT EXISTS criado_em timestamp with time zone NULL,
    ADD COLUMN IF NOT EXISTS atualizado_em timestamp with time zone NULL;

UPDATE api_beneficio
SET
    uuid_id = COALESCE(uuid_id, gen_random_uuid()),
    criado_em = COALESCE(criado_em, NOW()),
    atualizado_em = COALESCE(atualizado_em, NOW());

ALTER TABLE api_beneficio
    ALTER COLUMN uuid_id SET NOT NULL,
    ALTER COLUMN criado_em SET NOT NULL,
    ALTER COLUMN atualizado_em SET NOT NULL;

ALTER TABLE api_beneficiario
    ADD COLUMN IF NOT EXISTS beneficio_uuid_id uuid;

UPDATE api_beneficiario b
SET beneficio_uuid_id = bf.uuid_id
FROM api_beneficio bf
WHERE b.beneficio_id = bf.id
  AND b.beneficio_uuid_id IS NULL;

ALTER TABLE api_beneficiario
    ALTER COLUMN beneficio_uuid_id SET NOT NULL;

DO $$
DECLARE
    constraint_name text;
BEGIN
    FOR constraint_name IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'api_beneficiario'
          AND pg_get_constraintdef(con.oid) ILIKE '%beneficio_id%'
    LOOP
        EXECUTE format(
            'ALTER TABLE api_beneficiario DROP CONSTRAINT IF EXISTS %I',
            constraint_name
        );
    END LOOP;
END $$;

DO $$
DECLARE
    index_name text;
BEGIN
    FOR index_name IN
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = current_schema()
          AND tablename = 'api_beneficiario'
          AND indexdef ILIKE '%beneficio_id%'
    LOOP
        EXECUTE format('DROP INDEX IF EXISTS %I', index_name);
    END LOOP;
END $$;

ALTER TABLE api_beneficiario DROP COLUMN beneficio_id;
ALTER TABLE api_beneficiario RENAME COLUMN beneficio_uuid_id TO beneficio_id;

DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT con.conname
    INTO constraint_name
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = 'api_beneficio'
      AND con.contype = 'p';

    IF constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE api_beneficio DROP CONSTRAINT IF EXISTS %I',
            constraint_name
        );
    END IF;
END $$;

ALTER TABLE api_beneficio DROP COLUMN id;
ALTER TABLE api_beneficio RENAME COLUMN uuid_id TO id;
ALTER TABLE api_beneficio ADD PRIMARY KEY (id);

ALTER TABLE api_beneficiario
    ADD CONSTRAINT api_beneficiario_beneficio_id_fk
    FOREIGN KEY (beneficio_id)
    REFERENCES api_beneficio(id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE api_beneficiario
    ADD CONSTRAINT api_beneficiario_cidadao_beneficio_uniq
    UNIQUE (cidadao_id, beneficio_id);

CREATE INDEX IF NOT EXISTS api_benefic_benefic_286881_idx
    ON api_beneficiario (beneficio_id, status);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_alter_beneficiario_status_alter_cidadao_nome_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(FORWARD_SQL, reverse_sql=migrations.RunSQL.noop),
            ],
            state_operations=[
                migrations.AlterModelOptions(
                    name='beneficio',
                    options={'verbose_name': 'Benefício'},
                ),
                migrations.AddField(
                    model_name='beneficio',
                    name='atualizado_em',
                    field=models.DateTimeField(auto_now=True),
                ),
                migrations.AddField(
                    model_name='beneficio',
                    name='criado_em',
                    field=models.DateTimeField(auto_now_add=True, default=None),
                    preserve_default=False,
                ),
                migrations.AddField(
                    model_name='beneficio',
                    name='sincronizado',
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name='beneficio',
                    name='sincronizado_em',
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name='beneficio',
                    name='status_sincronizacao',
                    field=models.CharField(
                        choices=[
                            ('PENDENTE', 'Pendente'),
                            ('SINCRONIZADO', 'Sincronizado'),
                            ('ERRO', 'Erro'),
                        ],
                        default='PENDENTE',
                        max_length=20,
                    ),
                ),
                migrations.AlterField(
                    model_name='beneficio',
                    name='id',
                    field=models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                migrations.AlterModelTable(
                    name='beneficio',
                    table='api_beneficio',
                ),
            ],
        ),
    ]
