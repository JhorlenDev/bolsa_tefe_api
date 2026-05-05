# Bolsa Tefe API

API Django/DRF para cadastro e gestao social do Bolsa Tefe.

## Requisitos

- Python 3.12+
- PostgreSQL 15+ ou Docker

## Configuracao

1. Crie e ative um ambiente virtual:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Instale as dependencias:

```bash
pip install -r requirements.txt
```

3. Crie o arquivo de ambiente:

```bash
cp .env.example .env
```

4. Ajuste as variaveis no `.env`, principalmente `SECRET_KEY`, `DB_*` e credenciais `TEFE_*`.

## Banco de dados local

Para subir o PostgreSQL com Docker:

```bash
docker compose up -d
```

Depois rode:

```bash
python manage.py migrate
python manage.py runserver
```

## Verificacao

```bash
python manage.py check
python manage.py test
```
# bolsa_tefe_api
