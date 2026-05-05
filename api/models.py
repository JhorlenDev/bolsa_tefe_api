import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator

User = get_user_model()


def documento_anexo_upload_to(instance, filename):
    extensao = filename.split('.')[-1].lower() if '.' in filename else 'bin'
    nome_base = instance.tipo_documento
    return (
        f'cidadaos/{instance.cidadao_id}/documentos/'
        f'{nome_base}_{uuid.uuid4().hex}.{extensao}'
    )


def documento_pdf_upload_to(instance, filename):
    extensao = filename.split('.')[-1].lower() if '.' in filename else 'pdf'
    return (
        f'cidadaos/{instance.id}/documentos_pdf/'
        f'documento_{uuid.uuid4().hex}.{extensao}'
    )

# --- CLASSE BASE PARA SINCRONISMO ---
class BaseSincronizacao(models.Model):
    """Herança para garantir UUID e controle de sincronismo em todas as tabelas"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Controle de Sincronismo
    sincronizado = models.BooleanField(default=False)
    status_sincronizacao = models.CharField(
        max_length=20,
        choices=[
            ('PENDENTE', 'Pendente'),
            ('SINCRONIZADO', 'Sincronizado'),
            ('ERRO', 'Erro'),
        ],
        default='PENDENTE'
    )
    sincronizado_em = models.DateTimeField(null=True, blank=True)
    
    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# --- MODELOS DO SISTEMA ---

class KeycloakUserData(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='keycloak_data')
    keycloak_username = models.CharField(max_length=150, blank=True)
    roles = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.keycloak_username or self.user.username


class Cidadao(BaseSincronizacao):
    ESTADO_CIVIL_CHOICES = [
        ('SOLTEIRO', 'Solteiro'),
        ('CASADO', 'Casado'),
        ('DIVORCIADO', 'Divorciado'),
        ('VIUVO', 'Viúvo'),
        ('UNIAO_ESTAVEL', 'União estável'),
    ]

    nome = models.CharField(max_length=200, db_index=True)
    nis = models.CharField(max_length=20, unique=True, blank=True, null=True)
    data_nascimento = models.DateField(null=True, blank=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(unique=True, blank=True, null=True)
    
    naturalidade = models.CharField(max_length=100, blank=True, null=True)
    escolaridade = models.CharField(max_length=100, blank=True, null=True)
    identidade_genero = models.CharField(max_length=50, blank=True, null=True)
    cor = models.CharField(max_length=50, blank=True, null=True)
    possui_deficiencia = models.BooleanField(default=False)
    estado_civil = models.CharField(max_length=20, choices=ESTADO_CIVIL_CHOICES, blank=True, null=True)
    autorizacao_uso_imagem = models.BooleanField(default=False)
    autorizacao_uso_imagem_aceite_em = models.DateTimeField(null=True, blank=True)
    autorizacao_uso_imagem_responsavel = models.CharField(max_length=200, blank=True, null=True)
    documento_pdf = models.FileField(
        upload_to=documento_pdf_upload_to,
        validators=[FileExtensionValidator(['pdf'])],
        blank=True,
        null=True,
    )
    documento_pdf_nome_arquivo = models.CharField(
        max_length=255,
        blank=True,
        default='',
    )
    atualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cidadaos_atualizados',
    )

    class Meta:
        db_table = 'api_cidadao'
        verbose_name = 'Cidadão'

    def __str__(self):
        return self.nome


class Documento(BaseSincronizacao):
    cidadao = models.OneToOneField(Cidadao, on_delete=models.CASCADE, related_name='documentos')
    cpf = models.CharField(max_length=14, unique=True, blank=True, null=True)
    rg = models.CharField(max_length=20, blank=True, null=True)
    rg_orgao = models.CharField(max_length=20, blank=True, null=True)
    rg_uf = models.CharField(max_length=2, blank=True, null=True)
    carteira_trabalho = models.CharField(max_length=50, blank=True, null=True)
    inscricao_eleitoral = models.CharField(max_length=30, blank=True, null=True)
    zona = models.CharField(max_length=10, blank=True, null=True)
    secao = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        db_table = 'api_documentos'


class DocumentoAnexo(BaseSincronizacao):
    TIPO_RG = 'rg'
    TIPO_RG_FRENTE = 'rg_frente'
    TIPO_RG_VERSO = 'rg_verso'
    TIPO_CPF = 'cpf'
    TIPO_CERTIDAO_NASCIMENTO = 'certidao_nascimento'
    TIPO_CERTIDAO_CASAMENTO = 'certidao_casamento'
    TIPO_QUITACAO_ELEITORAL = 'quitacao_eleitoral'
    TIPO_COMPROVANTE_RESIDENCIA = 'comprovante_residencia'
    TIPO_FOTO_RESIDENCIA = 'foto_residencia'
    TIPO_FOTO_ATO_ATUALIZACAO = 'foto_ato_atualizacao'

    TIPOS_CHOICES = [
        (TIPO_RG_FRENTE, 'RG - Frente'),
        (TIPO_RG_VERSO, 'RG - Verso'),
        (TIPO_CPF, 'CPF'),
        (TIPO_CERTIDAO_NASCIMENTO, 'Certidão de Nascimento'),
        (TIPO_CERTIDAO_CASAMENTO, 'Certidão de Casamento'),
        (TIPO_QUITACAO_ELEITORAL, 'Quitação Eleitoral'),
        (TIPO_COMPROVANTE_RESIDENCIA, 'Comprovante de residência'),
        (TIPO_FOTO_RESIDENCIA, 'Foto da residência'),
        (TIPO_FOTO_ATO_ATUALIZACAO, 'Foto do ato da atualização'),
    ]

    cidadao = models.ForeignKey(
        Cidadao,
        on_delete=models.CASCADE,
        related_name='documentos_anexados',
    )
    tipo_documento = models.CharField(max_length=50, choices=TIPOS_CHOICES)
    arquivo = models.FileField(
        upload_to=documento_anexo_upload_to,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
    )
    nome_arquivo = models.CharField(max_length=255)
    extensao = models.CharField(max_length=10)
    tamanho_bytes = models.PositiveBigIntegerField(default=0)
    data_envio = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=30, default='ENVIADO')

    class Meta:
        db_table = 'api_documentos_anexos'
        constraints = [
            models.UniqueConstraint(
                fields=['cidadao', 'tipo_documento'],
                name='uq_documento_anexo_cidadao_tipo',
            ),
        ]

    def __str__(self):
        return f'{self.cidadao} - {self.tipo_documento}'

    def delete(self, using=None, keep_parents=False):
        storage = self.arquivo.storage if self.arquivo else None
        arquivo_nome = self.arquivo.name if self.arquivo else ''
        super().delete(using=using, keep_parents=keep_parents)
        if storage and arquivo_nome:
            try:
                storage.delete(arquivo_nome)
            except Exception:
                pass


class Endereco(BaseSincronizacao):
    TIPO_LOCALIZACAO_CHOICES = [
        ('URBANO', 'Urbano'),
        ('RURAL_DISTRITO', 'Rural/Distrito'),
    ]
    SITUACAO_CHOICES = [
        ('PROPRIA', 'Própria'),
        ('ALUGADA', 'Alugada'),
        ('CEDIDA', 'Cedida'),
        ('TEMPORARIA', 'Temporária'),
    ]
    ABASTECIMENTO_AGUA_CHOICES = [
        ('REDE_PUBLICA', 'Rede pública'),
        ('POCO', 'Poço'),
        ('NASCENTE', 'Nascente'),
        ('CISTERNA', 'Cisterna'),
        ('CACIMBA', 'Cacimba'),
        ('OUTRO', 'Outro'),
    ]

    cidadao = models.OneToOneField(Cidadao, on_delete=models.CASCADE, related_name='endereco')
    logradouro = models.CharField(max_length=200)
    tipo_localizacao = models.CharField(
        max_length=20,
        choices=TIPO_LOCALIZACAO_CHOICES,
        blank=True,
        null=True,
    )
    bairro = models.CharField(max_length=100, blank=True, default='')
    distrito = models.CharField(max_length=100, blank=True, null=True)
    comunidade_localidade = models.CharField(max_length=150, blank=True, null=True)
    numero = models.CharField(max_length=20, blank=True, null=True)
    cep = models.CharField(max_length=10, blank=True, null=True)
    complemento = models.CharField(max_length=100, blank=True, null=True)
    
    situacao_imovel = models.CharField(max_length=20, choices=SITUACAO_CHOICES, blank=True, null=True)
    valor_aluguel = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    material_parede = models.CharField(max_length=50, blank=True, null=True)
    qtd_comodos = models.IntegerField(null=True, blank=True)
    
    possui_luz = models.BooleanField(null=True, blank=True)
    possui_asfalto = models.BooleanField(null=True, blank=True)
    possui_lixo = models.BooleanField(null=True, blank=True)
    abastecimento_agua = models.CharField(
        max_length=20,
        choices=ABASTECIMENTO_AGUA_CHOICES,
        blank=True,
        null=True,
    )
    abastecimento_agua_outro = models.CharField(max_length=100, blank=True, null=True)
    possui_saneamento = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = 'api_habitacao'


class FamiliaMembro(BaseSincronizacao):
    cidadao_titular = models.ForeignKey(Cidadao, on_delete=models.CASCADE, related_name='membros_familia')
    nome_membro = models.CharField(max_length=200)
    parentesco = models.CharField(max_length=50)
    cpf_membro = models.CharField(max_length=14, blank=True, null=True)
    nao_possui_cpf = models.BooleanField(default=False)
    data_nascimento = models.DateField(null=True, blank=True)
    sexo = models.CharField(max_length=20, blank=True, null=True)
    escolaridade = models.CharField(max_length=100, blank=True, null=True)
    ocupacao = models.CharField(max_length=100, blank=True, null=True)
    escola_em_que_estuda = models.CharField(max_length=200, blank=True, null=True)
    gestante = models.BooleanField(default=False)
    possui_deficiencia = models.BooleanField(default=False)
    qual_deficiencia = models.CharField(max_length=200, blank=True, null=True)
    
    # Saúde e Social Individualizado (como discutido)
    possui_cartao_sus = models.BooleanField(default=True)
    possui_doenca_grave = models.BooleanField(default=False)
    descricao_doenca = models.TextField(blank=True, null=True)
    uso_substancia_ilicita = models.BooleanField(default=False)
    descricao_substancia = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'api_familia_membros'


class Escola(BaseSincronizacao):
    codigo = models.CharField(max_length=20, unique=True, blank=True, null=True)
    nome = models.CharField(max_length=200, unique=True)
    tipo = models.CharField(max_length=50, blank=True, null=True)
    zona = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        db_table = 'api_escola'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class LocalTefe(BaseSincronizacao):
    TIPO_BAIRRO = 'BAIRRO'
    TIPO_DISTRITO = 'DISTRITO'
    TIPO_COMUNIDADE = 'COMUNIDADE'

    TIPO_CHOICES = [
        (TIPO_BAIRRO, 'Bairro'),
        (TIPO_DISTRITO, 'Distrito'),
        (TIPO_COMUNIDADE, 'Comunidade'),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    nome = models.CharField(max_length=200)
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)

    class Meta:
        db_table = 'api_locais_tefe'
        ordering = ['ordem', 'nome']
        constraints = [
            models.UniqueConstraint(
                fields=['tipo', 'nome'],
                name='uq_local_tefe_tipo_nome',
            ),
        ]

    def __str__(self):
        return f'{self.tipo} - {self.nome}'


class Localidade(BaseSincronizacao):
    TIPO_BAIRRO = 'BAIRRO'
    TIPO_COMUNIDADE = 'COMUNIDADE'
    TIPO_DISTRITO = 'DISTRITO'

    TIPO_CHOICES = [
        (TIPO_BAIRRO, 'Bairro'),
        (TIPO_COMUNIDADE, 'Comunidade'),
        (TIPO_DISTRITO, 'Distrito'),
    ]

    nome = models.CharField(max_length=200, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    criada_automaticamente = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_localidades'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Rua(BaseSincronizacao):
    nome = models.CharField(max_length=200)
    localidade = models.ForeignKey(
        Localidade,
        on_delete=models.CASCADE,
        related_name='ruas',
    )
    criada_automaticamente = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_ruas'
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(
                fields=['localidade', 'nome'],
                name='uq_rua_localidade_nome',
            ),
        ]

    def __str__(self):
        return f'{self.nome} - {self.localidade.nome}'


class Socioeconomico(BaseSincronizacao):
    cidadao = models.OneToOneField(Cidadao, on_delete=models.CASCADE, related_name='socioeconomico')
    renda_total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    precedencia_rendimento = models.TextField(blank=True)
    pessoas_com_rendimento = models.IntegerField(default=0)
    recebe_beneficio = models.BooleanField(default=False)
    beneficio_nome = models.CharField(max_length=150, blank=True, null=True)
    beneficio_tipo = models.CharField(max_length=100, blank=True, null=True)
    beneficio_valor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    beneficios_recebidos = models.JSONField(default=list, blank=True)
    quantidade_pessoas_residencia = models.IntegerField(default=0)
    quantidade_pessoas_estudando = models.IntegerField(default=0)
    quantidade_criancas = models.IntegerField(default=0)
    quantidade_adolescentes = models.IntegerField(default=0)
    quantidade_adultos = models.IntegerField(default=0)
    quantidade_idosos = models.IntegerField(default=0)
    ha_gestante = models.BooleanField(default=False)
    ha_pessoa_com_deficiencia = models.BooleanField(default=False)
    qual_deficiencia = models.CharField(max_length=200, blank=True, null=True)
    utiliza_servico_social = models.BooleanField(default=False)
    servicos_sociais = models.JSONField(default=list, blank=True)
    pretende_voltar_estudar = models.BooleanField(default=False)
    possui_medida_protetiva = models.BooleanField(default=False)
    violencia_domestica = models.BooleanField(default=False)
    eh_ribeirinho = models.BooleanField(default=False)
    cidadao_estava_em_casa = models.BooleanField(default=False)
    ja_foi_visitado = models.BooleanField(default=False)
    mais_de_um_nucleo = models.BooleanField(default=False)
    documentacao_completa_grupo = models.BooleanField(default=True)
    observacoes_gerais = models.TextField(blank=True)

    class Meta:
        db_table = 'api_socioeconomico'


class TermoResponsabilidade(BaseSincronizacao):
    cidadao = models.OneToOneField(
        Cidadao,
        on_delete=models.CASCADE,
        related_name='termo_responsabilidade',
    )
    nome_responsavel = models.CharField(max_length=200, blank=True, null=True)
    local_termo = models.CharField(max_length=200, blank=True, null=True)
    data_termo = models.CharField(max_length=20, blank=True, null=True)
    hora_termo = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        db_table = 'api_termo_responsabilidade'


class Beneficio(BaseSincronizacao):
    nome = models.CharField(max_length=150, unique=True)
    descricao = models.TextField(blank=True, default='')
    ativo = models.BooleanField(default=True)
    atualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='beneficios_atualizados',
    )

    class Meta:
        db_table = 'api_beneficio'
        verbose_name = 'Benefício'

    def __str__(self):
        return self.nome


class Beneficiario(BaseSincronizacao):
    STATUS_CHOICES = [
        ('EM_ANALISE', 'Em análise'),
        ('APROVADO', 'Aprovado'),
        ('REPROVADO', 'Reprovado'),
    ]

    cidadao = models.ForeignKey(Cidadao, on_delete=models.CASCADE, related_name='beneficios_recebidos')
    beneficio = models.ForeignKey(Beneficio, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='EM_ANALISE',
        db_index=True,
    )
    valor_recebido = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    data_solicitacao = models.DateField(auto_now_add=True)
    atualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='beneficiarios_atualizados',
    )

    class Meta:
        unique_together = ('cidadao', 'beneficio')
        indexes = [
            models.Index(fields=['beneficio', 'status']),
            models.Index(fields=['cidadao', 'status']),
        ]
