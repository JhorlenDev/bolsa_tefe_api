import os
import shutil
import tempfile
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import exceptions
from rest_framework.test import APIClient, APIRequestFactory

from .authentication import KeycloakJWTAuthentication
from .models import (
    Beneficiario,
    Beneficio,
    Cidadao,
    Documento,
    DocumentoAnexo,
    Endereco,
    Escola,
    KeycloakUserData,
    Localidade,
    LocalTefe,
    Rua,
    Socioeconomico,
    TermoResponsabilidade,
)
from .permissions import HasRequiredRole
from .services.importacao_cidadao_service import (
    LinhaImportacaoCidadao,
    importar_linhas_cidadaos,
)


class KeycloakUserSyncTests(TestCase):
    def setUp(self):
        self.authentication = KeycloakJWTAuthentication()
        self.UserModel = get_user_model()

    def test_sync_user_creates_local_user_using_ksub(self):
        payload = {
            'ksub': '0f4d2f0b-2a2d-46db-a3a7-111111111111',
            'sub': 'legacy-sub',
            'preferred_username': 'maria.silva',
            'email': 'maria@example.com',
            'given_name': 'Maria',
            'family_name': 'Silva',
        }

        user = self.authentication._sync_user(payload, ['USER-BOLSA-TEFE'])

        saved_user = self.UserModel.objects.get(username=payload['ksub'])
        self.assertEqual(user.pk, saved_user.pk)
        self.assertEqual(saved_user.email, 'maria@example.com')
        self.assertEqual(saved_user.first_name, 'Maria')
        self.assertEqual(saved_user.last_name, 'Silva')
        self.assertFalse(saved_user.has_usable_password())
        self.assertEqual(user.keycloak_data.keycloak_username, 'maria.silva')
        self.assertEqual(user.keycloak_data.roles, ['USER-BOLSA-TEFE'])
        self.assertEqual(user.jwt_roles, ['USER-BOLSA-TEFE'])

    def test_sync_user_updates_local_data_on_new_login(self):
        user = self.UserModel.objects.create_user(
            username='0f4d2f0b-2a2d-46db-a3a7-222222222222',
            email='antigo@example.com',
            first_name='Nome Antigo',
            last_name='Sobrenome Antigo',
            password='senha-temporaria',
        )

        payload = {
            'ksub': user.username,
            'preferred_username': 'joao.souza',
            'email': 'novo@example.com',
            'given_name': 'Joao',
            'family_name': 'Souza',
        }

        self.authentication._sync_user(payload, ['USER-BOLSA-TEFE'])

        user.refresh_from_db()
        user.keycloak_data.refresh_from_db()
        self.assertEqual(user.email, 'novo@example.com')
        self.assertEqual(user.first_name, 'Joao')
        self.assertEqual(user.last_name, 'Souza')
        self.assertEqual(user.keycloak_data.keycloak_username, 'joao.souza')
        self.assertEqual(user.keycloak_data.roles, ['USER-BOLSA-TEFE'])

    def test_sync_user_requires_ksub_or_sub(self):
        with self.assertRaises(exceptions.AuthenticationFailed):
            self.authentication._sync_user({'email': 'sem-id@example.com'}, [])


class HasRequiredRoleTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = HasRequiredRole()
        self.user = get_user_model().objects.create_user(
            username='role-user',
            password='senha',
        )
        self.view = type('View', (), {'required_role': 'USER-BOLSA-TEFE'})()

    def test_permission_uses_persisted_roles(self):
        KeycloakUserData.objects.create(
            user=self.user,
            keycloak_username='role.user',
            roles=['USER-BOLSA-TEFE'],
        )
        request = self.factory.get('/cidadaos/')
        request.user = self.user
        request.jwt_roles = []

        self.assertTrue(self.permission.has_permission(request, self.view))

    def test_permission_falls_back_to_request_roles(self):
        request = self.factory.get('/cidadaos/')
        request.user = self.user
        request.jwt_roles = ['USER-BOLSA-TEFE']

        self.assertTrue(self.permission.has_permission(request, self.view))


class BaseApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='api-user',
            password='senha',
        )
        KeycloakUserData.objects.create(
            user=self.user,
            keycloak_username='api.user',
            roles=['USER-BOLSA-TEFE'],
        )
        self.client.force_authenticate(user=self.user)

    def set_roles(self, roles):
        self.user.keycloak_data.roles = roles
        self.user.keycloak_data.save(update_fields=['roles'])
        self.user.jwt_roles = roles


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='bolsa_tefe_test_media_')


class CidadaoApiTests(BaseApiTestCase):
    def test_cria_cidadao_com_novos_campos_sociais_familiares_e_termo(self):
        payload = {
            'nome': 'Fulano',
            'nis': '12345678901',
            'telefone': '92999999999',
            'email': 'fulano@email.com',
            'data_nascimento': '1990-01-10',
            'naturalidade': 'Tefe',
            'escolaridade': 'MEDIO_COMPLETO',
            'identidade_genero': 'HOMEM_CIS',
            'cor': 'PARDA',
            'possui_deficiencia': False,
            'estado_civil': 'CASADO',
            'autorizacao_uso_imagem': True,
            'autorizacao_uso_imagem_aceite_em': '2026-04-08T12:30:00Z',
            'autorizacao_uso_imagem_responsavel': 'Fulano de Tal',
            'documentos': {
                'cpf': '00011122233',
                'rg': '1234567',
                'rg_orgao': 'SSP',
                'rg_uf': 'AM',
                'inscricao_eleitoral': '123412341234',
                'zona': '12',
                'secao': '34',
            },
            'endereco': {
                'tipo_localizacao': 'URBANO',
                'cep': '69470000',
                'logradouro': 'Rua X',
                'bairro': 'Centro',
                'numero': '10',
                'complemento': '',
                'situacao_imovel': 'PROPRIA',
                'material_parede': 'ALVENARIA',
                'qtd_comodos': 4,
                'possui_luz': True,
                'possui_asfalto': True,
                'possui_lixo': True,
                'abastecimento_agua': 'OUTRO',
                'abastecimento_agua_outro': 'Carro pipa',
                'possui_saneamento': True,
            },
            'socioeconomico': {
                'renda_total': '1200.00',
                'precedencia_rendimento': 'BENEFICIO_SOCIAL',
                'pessoas_com_rendimento': 1,
                'recebe_beneficio': True,
                'beneficio_nome': 'Bolsa Familia',
                'beneficio_tipo': 'BOLSA_FAMILIA',
                'beneficio_valor': '600.00',
                'quantidade_pessoas_residencia': 5,
                'quantidade_pessoas_estudando': 2,
                'quantidade_criancas': 1,
                'quantidade_adolescentes': 1,
                'quantidade_adultos': 2,
                'quantidade_idosos': 1,
                'ha_gestante': False,
                'ha_pessoa_com_deficiencia': True,
                'qual_deficiencia': 'Deficiencia visual',
                'utiliza_servico_social': True,
                'servicos_sociais': ['PAIF', 'SCFV'],
                'mais_de_um_nucleo': False,
                'documentacao_completa_grupo': True,
                'observacoes_gerais': '...',
            },
            'membros_familia': [
                {
                    'nome_membro': 'Maria',
                    'parentesco': 'Conjuge',
                    'cpf_membro': '99988877766',
                    'data_nascimento': '1992-02-01',
                    'sexo': 'FEMININO',
                    'escolaridade': 'MEDIO_COMPLETO',
                    'ocupacao': 'Autonoma',
                    'escola_em_que_estuda': '',
                    'gestante': False,
                    'possui_cartao_sus': True,
                    'possui_deficiencia': True,
                    'qual_deficiencia': 'Auditiva',
                    'possui_doenca_grave': False,
                    'descricao_doenca': '',
                    'uso_substancia_ilicita': False,
                    'descricao_substancia': '',
                }
            ],
            'termo_responsabilidade': {
                'nome_responsavel': 'Fulano de Tal',
                'local_termo': 'Tefe/AM',
                'data_termo': '08/04/2026',
                'hora_termo': '14:30',
            },
        }

        response = self.client.post('/api/cidadaos/', payload, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['autorizacao_uso_imagem'])
        self.assertEqual(
            response.data['autorizacao_uso_imagem_responsavel'],
            'Fulano de Tal',
        )
        self.assertEqual(
            response.data['endereco']['abastecimento_agua_outro'],
            'Carro pipa',
        )
        self.assertEqual(response.data['endereco']['tipo_localizacao'], 'URBANO')
        self.assertEqual(response.data['endereco']['distrito'], None)
        self.assertEqual(response.data['endereco']['comunidade_localidade'], None)
        self.assertTrue(response.data['socioeconomico']['recebe_beneficio'])
        self.assertEqual(
            response.data['socioeconomico']['servicos_sociais'],
            ['PAIF', 'SCFV'],
        )
        self.assertEqual(response.data['membros_familia'][0]['sexo'], 'FEMININO')
        self.assertTrue(response.data['membros_familia'][0]['possui_deficiencia'])
        self.assertIn('escola_em_que_estuda', response.data['membros_familia'][0])
        self.assertEqual(
            response.data['termo_responsabilidade']['nome_responsavel'],
            'Fulano de Tal',
        )
        self.assertEqual(response.data['nome_responsavel'], 'Fulano de Tal')
        self.assertEqual(response.data['documentos_anexados'], [])

    def test_aceita_payload_legado_flat_para_termo_e_servico_social(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Fulano Legado',
                'telefone': '92999990001',
                'documentos': {'cpf': '11122233344'},
                'nome_responsavel': 'Responsavel Legado',
                'local_termo': 'Tefe',
                'data_termo': '08/04/2026',
                'hora_termo': '15:00',
                'socioeconomico': {
                    'utiliza_servico_social': 'PAIF',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['socioeconomico']['utiliza_servico_social'])
        self.assertEqual(response.data['socioeconomico']['servicos_sociais'], ['PAIF'])
        self.assertEqual(response.data['termo_responsabilidade']['local_termo'], 'Tefe')
        self.assertEqual(response.data['nome_responsavel'], 'Responsavel Legado')

    def test_aceita_status_cadastrado_no_payload_sem_quebrar_criacao(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Fulano Offline',
                'status': 'Cadastrado',
                'telefone': '92999990011',
                'documentos': {'cpf': '55566677788'},
                'termo_responsabilidade': {
                    'nome_responsavel': 'Operador Local',
                    'local_termo': 'Tefé',
                    'data_termo': '09/04/2026',
                    'hora_termo': '05:00',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['nome'], 'Fulano Offline')
        self.assertEqual(
            response.data['termo_responsabilidade']['nome_responsavel'],
            'Operador Local',
        )

    def test_aceita_payload_offline_antigo_com_pending_minusculo_e_campos_locais(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Ieda Offline',
                'status': 'Cadastrado',
                'telefone': '91929292626',
                'email': 'iesa@gmail.com',
                'nis': '83504350435',
                'data_nascimento': '2000-12-12',
                'documentos': {
                    'cpf': '99494646464',
                    'sincronizado': False,
                    'status_sincronizacao': 'pending',
                },
                'termo_responsabilidade': {
                    'nome_responsavel': 'Jhorlen Bianor',
                    'local_termo': 'Tefé',
                    'data_termo': '09/04/2026',
                    'hora_termo': '01:01',
                    'status_sincronizacao': 'pending',
                },
                'sincronizado': False,
                'status_sincronizacao': 'pending',
                'local_id': '461a5813-7d17-4d2c-be13-a902d94e5620',
                'created_at': 1775711033107,
                'updated_at': 1775711033107,
                'deleted': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data['sincronizado'])
        self.assertEqual(response.data['status_sincronizacao'], 'PENDENTE')

    def test_atualiza_cidadao_devolvendo_campos_novos_no_detalhe(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Cicrana',
                'telefone': '92999990007',
                'documentos': {'cpf': '32165498700'},
            },
            format='json',
        )
        cidadao_id = response.data['id']

        patch_response = self.client.patch(
            f'/api/cidadaos/{cidadao_id}/',
            {
                'autorizacao_uso_imagem': True,
                'autorizacao_uso_imagem_responsavel': 'Mae da Cicrana',
                'socioeconomico': {
                    'recebe_beneficio': False,
                    'utiliza_servico_social': True,
                    'servicos_sociais': ['SCFV'],
                    'ha_pessoa_com_deficiencia': False,
                },
                'termo_responsabilidade': {
                    'nome_responsavel': 'Mae da Cicrana',
                    'local_termo': 'Tefe/AM',
                    'data_termo': '08/04/2026',
                    'hora_termo': '16:00',
                },
                'membros_familia': [
                    {
                        'nome_membro': 'Filho',
                        'parentesco': 'Filho',
                        'sexo': 'MASCULINO',
                        'gestante': False,
                        'possui_cartao_sus': True,
                        'possui_deficiencia': False,
                        'possui_doenca_grave': False,
                        'uso_substancia_ilicita': False,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(patch_response.status_code, 200)

        detail_response = self.client.get(f'/api/cidadaos/{cidadao_id}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.data['autorizacao_uso_imagem_responsavel'],
            'Mae da Cicrana',
        )
        self.assertEqual(
            detail_response.data['socioeconomico']['servicos_sociais'],
            ['SCFV'],
        )
        self.assertEqual(
            detail_response.data['termo_responsabilidade']['hora_termo'],
            '16:00',
        )
        self.assertIn('gestante', detail_response.data['membros_familia'][0])
        self.assertEqual(detail_response.data['membros_familia'][0]['sexo'], 'MASCULINO')
        self.assertIn('updated_at', detail_response.data)
        self.assertIn('created_at', detail_response.data)
        self.assertIn('situacaoBeneficiario', detail_response.data)

    def test_patch_cidadao_invalido_registra_logs_e_retorna_erros(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Cidadao para log',
                'telefone': '92999990017',
                'documentos': {'cpf': '12121212121'},
            },
            format='json',
        )
        cidadao_id = response.data['id']

        with self.assertLogs('api.views', level='WARNING') as captured:
            patch_response = self.client.patch(
                f'/api/cidadaos/{cidadao_id}/',
                {
                    'membros_familia': [
                        {
                            'nome_membro': 'Filho sem sexo',
                            'parentesco': 'Filho',
                            'gestante': False,
                            'possui_cartao_sus': True,
                            'possui_deficiencia': False,
                            'possui_doenca_grave': False,
                            'uso_substancia_ilicita': False,
                        }
                    ],
                },
                format='json',
            )

        self.assertEqual(patch_response.status_code, 400)
        self.assertEqual(
            patch_response.data['detail'],
            'Dados inválidos para atualizar cidadão.',
        )
        self.assertIn('membros_familia', patch_response.data['errors'])
        logs_text = '\n'.join(captured.output)
        self.assertIn('payload inválido', logs_text)
        self.assertIn('serializer.errors', logs_text)

    def test_cria_cidadao_com_novos_campos_sociais_flat_e_bairro_flat(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Cidadao Flutter',
                'telefone': '92999990019',
                'bairro': 'Jerusalem',
                'pretende_voltar_estudar': True,
                'possui_medida_protetiva': False,
                'violencia_domestica': True,
                'eh_ribeirinho': True,
                'cidadao_estava_em_casa': True,
                'ja_foi_visitado': False,
                'documentos': {'cpf': '98765432100'},
                'endereco': {
                    'cep': '69470000',
                    'logradouro': 'Rua Nova',
                    'numero': '45',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['endereco']['bairro'], 'Jerusalem')
        self.assertEqual(response.data['endereco']['tipo_localizacao'], 'URBANO')
        self.assertTrue(response.data['socioeconomico']['pretende_voltar_estudar'])
        self.assertFalse(response.data['socioeconomico']['possui_medida_protetiva'])
        self.assertTrue(response.data['socioeconomico']['violencia_domestica'])
        self.assertTrue(response.data['socioeconomico']['eh_ribeirinho'])
        self.assertTrue(response.data['socioeconomico']['cidadao_estava_em_casa'])
        self.assertFalse(response.data['socioeconomico']['ja_foi_visitado'])

    def test_patch_e_get_cidadao_devolvem_novos_campos_sociais(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Atualizar Flutter',
                'telefone': '92999990020',
                'documentos': {'cpf': '12312312399'},
            },
            format='json',
        )
        cidadao_id = response.data['id']

        patch_response = self.client.patch(
            f'/api/cidadaos/{cidadao_id}/',
            {
                'socioeconomico': {
                    'pretende_voltar_estudar': True,
                    'possui_medida_protetiva': True,
                    'violencia_domestica': False,
                    'eh_ribeirinho': True,
                    'cidadao_estava_em_casa': False,
                    'ja_foi_visitado': True,
                    'observacoes_gerais': 'Manter compatibilidade',
                    'mais_de_um_nucleo': True,
                    'documentacao_completa_grupo': False,
                },
            },
            format='json',
        )

        self.assertEqual(patch_response.status_code, 200)
        self.assertTrue(patch_response.data['socioeconomico']['pretende_voltar_estudar'])
        self.assertTrue(patch_response.data['socioeconomico']['possui_medida_protetiva'])
        self.assertFalse(patch_response.data['socioeconomico']['violencia_domestica'])
        self.assertTrue(patch_response.data['socioeconomico']['eh_ribeirinho'])
        self.assertFalse(patch_response.data['socioeconomico']['cidadao_estava_em_casa'])
        self.assertTrue(patch_response.data['socioeconomico']['ja_foi_visitado'])
        self.assertEqual(
            patch_response.data['socioeconomico']['observacoes_gerais'],
            'Manter compatibilidade',
        )
        self.assertTrue(patch_response.data['socioeconomico']['mais_de_um_nucleo'])
        self.assertFalse(
            patch_response.data['socioeconomico']['documentacao_completa_grupo']
        )

        detail_response = self.client.get(f'/api/cidadaos/{cidadao_id}/')

        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(detail_response.data['socioeconomico']['pretende_voltar_estudar'])
        self.assertTrue(detail_response.data['socioeconomico']['possui_medida_protetiva'])
        self.assertFalse(detail_response.data['socioeconomico']['violencia_domestica'])
        self.assertTrue(detail_response.data['socioeconomico']['eh_ribeirinho'])
        self.assertFalse(detail_response.data['socioeconomico']['cidadao_estava_em_casa'])
        self.assertTrue(detail_response.data['socioeconomico']['ja_foi_visitado'])

    def test_cria_membro_familia_com_cpf_e_retorna_nao_possui_cpf_false(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Familia CPF',
                'telefone': '92999990024',
                'documentos': {'cpf': '10101010101'},
                'membros_familia': [
                    {
                        'nome_membro': 'Filho Com CPF',
                        'parentesco': 'Filho',
                        'cpf_membro': '99988877766',
                        'nao_possui_cpf': False,
                        'sexo': 'MASCULINO',
                        'gestante': False,
                        'possui_cartao_sus': True,
                        'possui_deficiencia': False,
                        'possui_doenca_grave': False,
                        'uso_substancia_ilicita': False,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['membros_familia'][0]['cpf_membro'], '99988877766')
        self.assertFalse(response.data['membros_familia'][0]['nao_possui_cpf'])

    def test_cria_membro_familia_sem_cpf_quando_nao_possui_cpf_true(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Familia Sem CPF',
                'telefone': '92999990025',
                'documentos': {'cpf': '20202020202'},
                'membros_familia': [
                    {
                        'nome_membro': 'Filho Sem CPF',
                        'parentesco': 'Filho',
                        'cpf_membro': '12312312312',
                        'nao_possui_cpf': True,
                        'sexo': 'MASCULINO',
                        'gestante': False,
                        'possui_cartao_sus': True,
                        'possui_deficiencia': False,
                        'possui_doenca_grave': False,
                        'uso_substancia_ilicita': False,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['membros_familia'][0]['cpf_membro'], '')
        self.assertTrue(response.data['membros_familia'][0]['nao_possui_cpf'])

    def test_cria_membro_estudante_com_escola_em_que_estuda(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Familia Estudante',
                'telefone': '92999990027',
                'documentos': {'cpf': '40404040404'},
                'membros_familia': [
                    {
                        'nome_membro': 'Aluno',
                        'parentesco': 'Filho',
                        'nao_possui_cpf': True,
                        'sexo': 'MASCULINO',
                        'ocupacao': 'ESTUDANTE',
                        'escola_em_que_estuda': 'Escola Municipal Walter Cabral',
                        'gestante': False,
                        'possui_cartao_sus': True,
                        'possui_deficiencia': False,
                        'possui_doenca_grave': False,
                        'uso_substancia_ilicita': False,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data['membros_familia'][0]['escola_em_que_estuda'],
            'Escola Municipal Walter Cabral',
        )

    def test_aceita_alias_legados_escola_e_sem_cpf_no_membro_familia(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Familia Legado Escola',
                'telefone': '92999990028',
                'documentos': {'cpf': '50505050505'},
                'membros_familia': [
                    {
                        'nome_membro': 'Aluno Legado',
                        'parentesco': 'Filho',
                        'sem_cpf': True,
                        'sexo': 'FEMININO',
                        'ocupacao': 'ESTUDANTE',
                        'escola': 'Escola Municipal Santa Teresa',
                        'gestante': False,
                        'possui_cartao_sus': True,
                        'possui_deficiencia': False,
                        'possui_doenca_grave': False,
                        'uso_substancia_ilicita': False,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['membros_familia'][0]['nao_possui_cpf'])
        self.assertTrue(response.data['membros_familia'][0]['sem_cpf'])
        self.assertEqual(
            response.data['membros_familia'][0]['escola_em_que_estuda'],
            'Escola Municipal Santa Teresa',
        )

    def test_rejeita_membro_estudante_sem_escola(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Familia Estudante Invalido',
                'telefone': '92999990029',
                'documentos': {'cpf': '60606060606'},
                'membros_familia': [
                    {
                        'nome_membro': 'Aluno Sem Escola',
                        'parentesco': 'Filho',
                        'nao_possui_cpf': True,
                        'sexo': 'MASCULINO',
                        'ocupacao': 'ESTUDANTE',
                        'gestante': False,
                        'possui_cartao_sus': True,
                        'possui_deficiencia': False,
                        'possui_doenca_grave': False,
                        'uso_substancia_ilicita': False,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('membros_familia', response.data['errors'])

    def test_payload_antigo_de_membro_familia_sem_nao_possui_cpf_permanece_compativel(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Familia Legado',
                'telefone': '92999990026',
                'documentos': {'cpf': '30303030303'},
                'membros_familia': [
                    {
                        'nome_membro': 'Dependente Legado',
                        'parentesco': 'Filho',
                        'cpf_membro': '11122233344',
                        'sexo': 'FEMININO',
                        'gestante': False,
                        'possui_cartao_sus': True,
                        'possui_deficiencia': False,
                        'possui_doenca_grave': False,
                        'uso_substancia_ilicita': False,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['membros_familia'][0]['cpf_membro'], '11122233344')
        self.assertFalse(response.data['membros_familia'][0]['nao_possui_cpf'])

    def test_patch_cidadao_aceita_manter_mesmo_cpf_do_proprio_documento(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Ana Flavia',
                'telefone': '92999990018',
                'email': 'ana@example.com',
                'documentos': {
                    'cpf': '02238946217',
                    'rg': '252558668',
                },
            },
            format='json',
        )

        cidadao_id = response.data['id']

        patch_response = self.client.patch(
            f'/api/cidadaos/{cidadao_id}/',
            {
                'nome': 'Ana Flavia da Silva',
                'documentos': {
                    'cpf': '02238946217',
                    'rg': '25.255.866-8',
                    'rg_orgao': 'SSP',
                    'rg_uf': 'AM',
                },
            },
            format='json',
        )

        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.data['documentos']['cpf'], '02238946217')

    def test_aceita_beneficio_sem_nome_quando_tipo_e_valor_presentes(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Beneficio sem nome',
                'telefone': '92999990009',
                'documentos': {'cpf': '22233344455'},
                'socioeconomico': {
                    'recebe_beneficio': True,
                    'beneficio_tipo': 'BOLSA_FAMILIA',
                    'beneficio_valor': '450.00',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['socioeconomico']['beneficio_nome'])
        self.assertEqual(len(response.data['socioeconomico']['beneficios_recebidos']), 1)
        self.assertEqual(
            response.data['socioeconomico']['beneficios_recebidos'][0]['tipo'],
            'BOLSA_FAMILIA',
        )

    def test_aceita_multiplos_beneficios_no_novo_formato(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Cidadao Multi Beneficio',
                'telefone': '92999990021',
                'documentos': {'cpf': '77788899900'},
                'socioeconomico': {
                    'beneficios_recebidos': [
                        {
                            'nome': 'Bolsa Familia',
                            'tipo': 'BOLSA_FAMILIA',
                            'valor': '600.00',
                        },
                        {
                            'beneficio_nome': 'Auxilio Gas',
                            'beneficio_tipo': 'AUXILIO_GAS',
                            'beneficio_valor': '120.50',
                        },
                    ],
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['socioeconomico']['recebe_beneficio'])
        self.assertEqual(response.data['socioeconomico']['beneficio_nome'], 'Bolsa Familia')
        self.assertEqual(response.data['socioeconomico']['beneficio_tipo'], 'BOLSA_FAMILIA')
        self.assertEqual(str(response.data['socioeconomico']['beneficio_valor']), '600.00')
        self.assertEqual(len(response.data['socioeconomico']['beneficios_recebidos']), 2)
        self.assertEqual(
            response.data['socioeconomico']['beneficios_recebidos'][1]['tipo'],
            'AUXILIO_GAS',
        )
        self.assertEqual(
            response.data['socioeconomico']['beneficios_recebidos'][1]['valor'],
            '120.50',
        )

    def test_patch_e_get_mantem_beneficios_recebidos(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Editar Beneficios',
                'telefone': '92999990022',
                'documentos': {'cpf': '33322211100'},
            },
            format='json',
        )
        cidadao_id = response.data['id']

        patch_response = self.client.patch(
            f'/api/cidadaos/{cidadao_id}/',
            {
                'socioeconomico': {
                    'beneficios_recebidos': [
                        {
                            'nome': 'Beneficio Principal',
                            'tipo': 'BENEFICIO_PRINCIPAL',
                            'valor': '900.00',
                        },
                        {
                            'nome': 'Beneficio Extra',
                            'tipo': 'BENEFICIO_EXTRA',
                            'valor': '80.00',
                        },
                    ],
                    'observacoes_gerais': 'Fluxo novo do app',
                },
            },
            format='json',
        )

        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(len(patch_response.data['socioeconomico']['beneficios_recebidos']), 2)
        self.assertEqual(
            patch_response.data['socioeconomico']['beneficio_tipo'],
            'BENEFICIO_PRINCIPAL',
        )
        self.assertEqual(
            patch_response.data['socioeconomico']['beneficios_recebidos'][0]['valor'],
            '900.00',
        )

        detail_response = self.client.get(f'/api/cidadaos/{cidadao_id}/')

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(len(detail_response.data['socioeconomico']['beneficios_recebidos']), 2)
        self.assertEqual(
            detail_response.data['socioeconomico']['beneficios_recebidos'][1]['nome'],
            'Beneficio Extra',
        )
        self.assertEqual(
            detail_response.data['socioeconomico']['observacoes_gerais'],
            'Fluxo novo do app',
        )

    def test_rejeita_beneficio_incompleto_no_novo_formato(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Beneficio Incompleto',
                'telefone': '92999990023',
                'documentos': {'cpf': '11199988877'},
                'socioeconomico': {
                    'beneficios_recebidos': [
                        {
                            'nome': 'Auxilio',
                            'tipo': 'AUXILIO_GERAL',
                        }
                    ],
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], 'Dados inválidos para criar cidadão.')
        self.assertIn('socioeconomico', response.data['errors'])
        self.assertIn('beneficios_recebidos', response.data['errors']['socioeconomico'])

    def test_valida_regras_dos_novos_campos(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Invalido',
                'telefone': '92999990008',
                'documentos': {'cpf': '44455566677'},
                'endereco': {
                    'cep': '69470000',
                    'logradouro': 'Rua X',
                    'bairro': 'Centro',
                    'numero': '10',
                    'abastecimento_agua': 'OUTRO',
                },
                'socioeconomico': {
                    'recebe_beneficio': True,
                    'utiliza_servico_social': True,
                    'ha_pessoa_com_deficiencia': True,
                    'servicos_sociais': ['PAIF'],
                },
                'membros_familia': [
                    {
                        'nome_membro': 'Pessoa',
                        'parentesco': 'Irmao',
                        'sexo': '',
                        'possui_cartao_sus': True,
                        'possui_deficiencia': True,
                        'possui_doenca_grave': False,
                        'uso_substancia_ilicita': False,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], 'Dados inválidos para criar cidadão.')
        self.assertIn('errors', response.data)
        self.assertIn('endereco', response.data['errors'])
        self.assertIn('socioeconomico', response.data['errors'])
        self.assertIn('membros_familia', response.data['errors'])

    def test_cria_endereco_rural_validando_distrito_e_comunidade(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Morador Rural',
                'telefone': '92999990100',
                'documentos': {'cpf': '55544433322'},
                'endereco': {
                    'tipo_localizacao': 'RURAL_DISTRITO',
                    'logradouro': 'Ramal do Lago',
                    'distrito': 'Caiambé',
                    'comunidade_localidade': 'Comunidade Sao Francisco',
                    'numero': 'S/N',
                    'cep': '69470000',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['endereco']['tipo_localizacao'], 'RURAL_DISTRITO')
        self.assertEqual(response.data['endereco']['bairro'], '')
        self.assertEqual(response.data['endereco']['distrito'], 'Caiambé')
        self.assertEqual(
            response.data['endereco']['comunidade_localidade'],
            'Comunidade Sao Francisco',
        )

    def test_rejeita_endereco_rural_sem_distrito_e_comunidade(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Rural Invalido',
                'telefone': '92999990101',
                'documentos': {'cpf': '55544433321'},
                'endereco': {
                    'tipo_localizacao': 'RURAL_DISTRITO',
                    'logradouro': 'Ramal',
                    'numero': 'S/N',
                    'cep': '69470000',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('endereco', response.data['errors'])
        self.assertIn('distrito', response.data['errors']['endereco'])

    def test_inferir_endereco_rural_legado_a_partir_de_bairro_especial(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Legado Rural',
                'telefone': '92999990102',
                'documentos': {'cpf': '55544433320'},
                'endereco': {
                    'logradouro': 'Beira Rio',
                    'bairro': 'Caiambé',
                    'comunidade_localidade': 'Comunidade Esperanca',
                    'numero': 'S/N',
                    'cep': '69470000',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['endereco']['tipo_localizacao'], 'RURAL_DISTRITO')
        self.assertEqual(response.data['endereco']['bairro'], '')
        self.assertEqual(response.data['endereco']['distrito'], 'Caiambé')

    def test_get_normaliza_endereco_legado_salvo_apenas_com_bairro(self):
        cidadao = Cidadao.objects.create(
            nome='Registro Antigo',
            telefone='92999990103',
        )
        Documento.objects.create(cidadao=cidadao, cpf='55544433319')
        Endereco.objects.create(
            cidadao=cidadao,
            logradouro='Ramal Antigo',
            bairro='Área Rural de Tefé',
            numero='S/N',
            cep='69470000',
        )

        response = self.client.get(f'/api/cidadaos/{cidadao.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['endereco']['tipo_localizacao'], 'RURAL_DISTRITO')
        self.assertEqual(response.data['endereco']['bairro'], '')
        self.assertEqual(response.data['endereco']['distrito'], 'Área Rural de Tefé')

    def test_get_normaliza_endereco_rural_legado_usando_catalogo_comunidade(self):
        Localidade.objects.create(nome='BETEL', tipo='COMUNIDADE')
        cidadao = Cidadao.objects.create(
            nome='Registro Betel',
            telefone='92999990104',
        )
        Documento.objects.create(cidadao=cidadao, cpf='55544433318')
        Endereco.objects.create(
            cidadao=cidadao,
            logradouro='Ramal Betel',
            bairro='BETEL',
            numero='S/N',
            cep='69470000',
        )

        response = self.client.get(f'/api/cidadaos/{cidadao.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['endereco']['tipo_localizacao'], 'RURAL_DISTRITO')
        self.assertEqual(response.data['endereco']['bairro'], '')
        self.assertEqual(response.data['endereco']['comunidade_localidade'], 'BETEL')

    def test_lista_cidadaos_devolve_endereco_rural_completo(self):
        Localidade.objects.create(nome='PORTO PRAIA', tipo='COMUNIDADE')
        cidadao = Cidadao.objects.create(
            nome='Morador Porto Praia',
            telefone='92999990105',
        )
        Documento.objects.create(cidadao=cidadao, cpf='55544433317')
        Endereco.objects.create(
            cidadao=cidadao,
            logradouro='Beira Rio',
            tipo_localizacao='RURAL',
            bairro='PORTO PRAIA',
            numero='S/N',
            cep='69470000',
        )

        response = self.client.get('/api/cidadaos/')

        self.assertEqual(response.status_code, 200)
        item = next(row for row in response.data if row['id'] == str(cidadao.id))
        self.assertEqual(item['endereco']['tipo_localizacao'], 'RURAL_DISTRITO')
        self.assertEqual(item['endereco']['bairro'], '')
        self.assertEqual(item['endereco']['comunidade_localidade'], 'PORTO PRAIA')

    def test_cria_cidadao_pendente_quando_payload_indica_nao_sincronizado(self):
        response = self.client.post(
            '/api/cidadaos/',
            {
                'nome': 'Maria Offline',
                'telefone': '92999990001',
                'sincronizado': False,
                'documentos': {
                    'cpf': '11122233344',
                    'sincronizado': False,
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data['sincronizado'])
        self.assertEqual(response.data['status_sincronizacao'], 'PENDENTE')
        self.assertTrue(response.data['pendente_sincronizacao'])
        self.assertTrue(response.data['nao_sincronizado'])
        self.assertIsNone(response.data['sincronizado_em'])
        self.assertEqual(response.data['documentos']['cpf'], '11122233344')

    def test_lista_cidadaos_exibe_sincronizados_e_pendentes(self):
        sincronizado = Cidadao.objects.create(
            nome='Ana Online',
            telefone='92999990002',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Documento.objects.create(
            cidadao=sincronizado,
            cpf='55566677788',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        pendente = Cidadao.objects.create(
            nome='Bruno Offline',
            telefone='92999990003',
            sincronizado=False,
            status_sincronizacao='PENDENTE',
        )
        Documento.objects.create(
            cidadao=pendente,
            cpf='99988877766',
            sincronizado=False,
            status_sincronizacao='PENDENTE',
        )

        response = self.client.get('/api/cidadaos/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

        cidadaos_por_nome = {item['nome']: item for item in response.data}

        self.assertIn(sincronizado.nome, cidadaos_por_nome)
        self.assertIn(pendente.nome, cidadaos_por_nome)
        self.assertTrue(cidadaos_por_nome['Ana Online']['sincronizado'])
        self.assertEqual(
            cidadaos_por_nome['Ana Online']['status_sincronizacao'],
            'SINCRONIZADO',
        )
        self.assertFalse(cidadaos_por_nome['Bruno Offline']['sincronizado'])
        self.assertEqual(
            cidadaos_por_nome['Bruno Offline']['status_sincronizacao'],
            'PENDENTE',
        )

    def test_excluir_cidadao_exige_role_admin(self):
        cidadao = Cidadao.objects.create(
            nome='Maria Restrita',
            telefone='92999990004',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        response = self.client.delete(f'/api/cidadaos/{cidadao.id}/')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data['detail'],
            'Você não tem permissão para excluir cidadão.',
        )
        self.assertTrue(Cidadao.objects.filter(id=cidadao.id).exists())

    def test_excluir_cidadao_com_role_admin(self):
        cidadao = Cidadao.objects.create(
            nome='Maria Admin',
            telefone='92999990005',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])

        response = self.client.delete(f'/api/cidadaos/{cidadao.id}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Cidadao.objects.filter(id=cidadao.id).exists())

    def test_lista_escolas_ordenada_por_nome(self):
        Escola.objects.all().delete()
        Escola.objects.create(nome='Z Escola', codigo='999', tipo='MUNICIPAL', zona='URBANA')
        Escola.objects.create(nome='A Escola', codigo='998', tipo='ESTADUAL', zona='RURAL')

        response = self.client.get('/api/escolas/')

        self.assertEqual(response.status_code, 200)
        nomes = [item['nome'] for item in response.data]
        self.assertEqual(nomes, sorted(nomes))
        self.assertIn('id', response.data[0])
        self.assertIn('nome', response.data[0])
        self.assertIn('codigo', response.data[0])
        self.assertIn('tipo', response.data[0])
        self.assertIn('zona', response.data[0])


class BeneficiarioApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.cidadao = Cidadao.objects.create(
            nome='Ana Souza',
            telefone='92999990000',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Documento.objects.create(
            cidadao=self.cidadao,
            cpf='12345678900',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        self.beneficio = Beneficio.objects.create(
            nome='Auxilio Municipal',
            descricao='Beneficio de apoio financeiro.',
            ativo=True,
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

    def test_cria_beneficiario_associando_cidadao_e_beneficio(self):
        response = self.client.post(
            '/api/beneficiarios/',
            {
                'cidadao': str(self.cidadao.id),
                'beneficio': str(self.beneficio.id),
                'status': 'EM_ANALISE',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Beneficiario.objects.count(), 1)
        self.assertEqual(response.data['id'], response.data['vinculo_id'])
        self.assertEqual(response.data['cidadao_id'], str(self.cidadao.id))
        self.assertEqual(response.data['beneficio'], self.beneficio.id)
        self.assertEqual(response.data['beneficio_id'], str(self.beneficio.id))
        self.assertEqual(response.data['cidadao_nome'], 'Ana Souza')
        self.assertEqual(response.data['beneficio_nome'], 'Auxilio Municipal')
        self.assertEqual(response.data['nome'], 'Auxilio Municipal')
        self.assertEqual(response.data['beneficioNome'], 'Auxilio Municipal')
        self.assertTrue(response.data['ativo'])
        self.assertTrue(response.data['beneficio_ativo'])
        self.assertEqual(response.data['status'], 'EM_ANALISE')
        self.assertEqual(response.data['beneficio_status'], 'EM_ANALISE')


    def test_nao_permite_vinculo_duplicado_para_mesmo_beneficio(self):
        Beneficiario.objects.create(
            cidadao=self.cidadao,
            beneficio=self.beneficio,
            status='EM_ANALISE',
        )

        response = self.client.post(
            '/api/beneficiarios/',
            {
                'cidadao': str(self.cidadao.id),
                'beneficio': str(self.beneficio.id),
                'status': 'EM_ANALISE',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('non_field_errors', response.data)
        self.assertEqual(
            response.data['non_field_errors'][0],
            'Este cidadão já está vinculado a este benefício.',
        )

    def test_lista_vinculos_por_rota_aninhada_do_cidadao(self):
        vinculo = Beneficiario.objects.create(
            cidadao=self.cidadao,
            beneficio=self.beneficio,
            status='EM_ANALISE',
        )

        response = self.client.get(f'/api/cidadaos/{self.cidadao.id}/beneficios/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(vinculo.id))
        self.assertEqual(response.data[0]['vinculo_id'], str(vinculo.id))
        self.assertEqual(response.data[0]['beneficio'], self.beneficio.id)
        self.assertEqual(response.data[0]['beneficio_id'], str(self.beneficio.id))
        self.assertEqual(response.data[0]['beneficio_nome'], 'Auxilio Municipal')
        self.assertTrue(response.data[0]['ativo'])
        self.assertEqual(response.data[0]['status'], 'EM_ANALISE')

    def test_cria_vinculo_por_rota_aninhada_do_cidadao(self):
        response = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/beneficios/',
            {
                'beneficio': str(self.beneficio.id),
                'status': 'EM_ANALISE',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Beneficiario.objects.count(), 1)
        self.assertEqual(response.data['cidadao'], self.cidadao.id)
        self.assertEqual(response.data['cidadao_id'], str(self.cidadao.id))
        self.assertEqual(response.data['beneficio'], self.beneficio.id)
        self.assertEqual(response.data['beneficio_id'], str(self.beneficio.id))
        self.assertEqual(response.data['beneficio_nome'], 'Auxilio Municipal')
        self.assertEqual(response.data['beneficio_status'], 'EM_ANALISE')

    def test_cria_vinculo_por_rota_aninhada_aceitando_beneficio_id_do_front(self):
        response = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/beneficios/',
            {
                'beneficioId': str(self.beneficio.id),
                'status': 'EM_ANALISE',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Beneficiario.objects.count(), 1)
        self.assertEqual(response.data['beneficio'], self.beneficio.id)
        self.assertEqual(response.data['beneficio_id'], str(self.beneficio.id))

    def test_remove_vinculo_por_rota_aninhada_do_cidadao(self):
        Beneficiario.objects.create(
            cidadao=self.cidadao,
            beneficio=self.beneficio,
            status='EM_ANALISE',
        )

        response = self.client.delete(
            f'/api/cidadaos/{self.cidadao.id}/beneficios/{self.beneficio.id}/'
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            Beneficiario.objects.filter(
                cidadao=self.cidadao,
                beneficio=self.beneficio,
            ).exists()
        )

    def test_atualiza_status_do_vinculo_por_rota_aninhada(self):
        Beneficiario.objects.create(
            cidadao=self.cidadao,
            beneficio=self.beneficio,
            status='EM_ANALISE',
        )

        response = self.client.patch(
            f'/api/cidadaos/{self.cidadao.id}/beneficios/{self.beneficio.id}/',
            {'status': 'APROVADO'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'APROVADO')

    def test_lista_cidadaos_vinculados_ao_beneficio(self):
        outro_cidadao = Cidadao.objects.create(
            nome='Bruno Lima',
            telefone='92999991111',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Documento.objects.create(
            cidadao=outro_cidadao,
            cpf='98765432100',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Beneficiario.objects.create(
            cidadao=self.cidadao,
            beneficio=self.beneficio,
            status='EM_ANALISE',
        )
        Beneficiario.objects.create(
            cidadao=outro_cidadao,
            beneficio=self.beneficio,
            status='EM_ANALISE',
        )

        response = self.client.get(f'/api/beneficios/{self.beneficio.id}/cidadaos/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]['id'], str(self.cidadao.id))
        self.assertEqual(response.data[0]['cidadao_id'], str(self.cidadao.id))
        self.assertIn('vinculo_id', response.data[0])
        self.assertEqual(response.data[0]['nome'], 'Ana Souza')
        self.assertIsNone(response.data[0]['email'])
        self.assertEqual(response.data[0]['cpf'], '12345678900')
        self.assertEqual(response.data[1]['nome'], 'Bruno Lima')
        self.assertEqual(response.data[0]['status'], 'EM_ANALISE')

    def test_excluir_beneficio_remove_vinculos_antes_de_apagar(self):
        outro_cidadao = Cidadao.objects.create(
            nome='Carlos Mendes',
            telefone='92999992222',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Documento.objects.create(
            cidadao=outro_cidadao,
            cpf='11133355577',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Beneficiario.objects.create(
            cidadao=self.cidadao,
            beneficio=self.beneficio,
            status='APROVADO',
        )
        Beneficiario.objects.create(
            cidadao=outro_cidadao,
            beneficio=self.beneficio,
            status='EM_ANALISE',
        )
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])

        response = self.client.delete(f'/api/beneficios/{self.beneficio.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['vinculos_removidos'], 2)
        self.assertFalse(Beneficio.objects.filter(id=self.beneficio.id).exists())
        self.assertFalse(
            Beneficiario.objects.filter(beneficio_id=self.beneficio.id).exists()
        )


class LocalTefeApiTests(BaseApiTestCase):
    def test_lista_locais_tefe_retorna_apenas_ativos_por_padrao_ordenados(self):
        LocalTefe.objects.all().delete()
        LocalTefe.objects.create(tipo='BAIRRO', nome='Zeta', ativo=True, ordem=2)
        LocalTefe.objects.create(tipo='BAIRRO', nome='Alfa', ativo=True, ordem=1)
        LocalTefe.objects.create(tipo='COMUNIDADE', nome='Oculta', ativo=False, ordem=0)

        response = self.client.get('/api/locais-tefe/')

        self.assertEqual(response.status_code, 200)
        nomes = [item['nome'] for item in response.data]
        self.assertEqual(nomes, ['Alfa', 'Zeta'])
        self.assertIn('created_at', response.data[0])
        self.assertIn('updated_at', response.data[0])

    def test_lista_locais_tefe_aceita_filtros_por_tipo_e_ativo(self):
        LocalTefe.objects.all().delete()
        LocalTefe.objects.create(tipo='BAIRRO', nome='Centro Novo', ativo=True, ordem=1)
        LocalTefe.objects.create(tipo='DISTRITO', nome='Distrito Novo', ativo=True, ordem=1)
        LocalTefe.objects.create(tipo='COMUNIDADE', nome='Comunidade X', ativo=False, ordem=1)

        response_tipo = self.client.get('/api/locais-tefe/?tipo=DISTRITO')
        self.assertEqual(response_tipo.status_code, 200)
        self.assertEqual(len(response_tipo.data), 1)
        self.assertEqual(response_tipo.data[0]['tipo'], 'DISTRITO')

        response_inativos = self.client.get('/api/locais-tefe/?ativo=false')
        self.assertEqual(response_inativos.status_code, 200)
        self.assertEqual(len(response_inativos.data), 1)
        self.assertFalse(response_inativos.data[0]['ativo'])

    def test_lista_locais_tefe_vazia_retorna_array_vazio(self):
        LocalTefe.objects.all().delete()
        response = self.client.get('/api/locais-tefe/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_admin_pode_criar_editar_e_excluir_local_tefe(self):
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])

        create_response = self.client.post(
            '/api/locais-tefe/',
            {
                'tipo': 'COMUNIDADE',
                'nome': 'Comunidade Nova',
                'ativo': True,
                'ordem': 15,
            },
            format='json',
        )

        self.assertEqual(create_response.status_code, 201)
        local_id = create_response.data['id']

        patch_response = self.client.patch(
            f'/api/locais-tefe/{local_id}/',
            {
                'nome': 'Comunidade Atualizada',
                'ativo': False,
            },
            format='json',
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.data['nome'], 'Comunidade Atualizada')
        self.assertFalse(patch_response.data['ativo'])

        delete_response = self.client.delete(f'/api/locais-tefe/{local_id}/')
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(LocalTefe.objects.filter(id=local_id).exists())

    def test_usuario_sem_role_admin_nao_pode_mutar_local_tefe(self):
        response = self.client.post(
            '/api/locais-tefe/',
            {
                'tipo': 'BAIRRO',
                'nome': 'Novo Bairro',
                'ativo': True,
                'ordem': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data['detail'],
            'Você não tem permissão para criar local de Tefé.',
        )


class LocalidadeRuaApiTests(BaseApiTestCase):
    def test_lista_localidades_retorna_array_vazio_sem_dados(self):
        Localidade.objects.all().delete()

        response = self.client.get('/api/localidades/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_admin_cria_localidade_normalizando_nome(self):
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])

        response = self.client.post(
            '/api/localidades/',
            {
                'nome': '  Jardim   Perimetral  ',
                'tipo': 'BAIRRO',
                'criada_automaticamente': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['nome'], 'JARDIM PERIMETRAL')
        self.assertEqual(response.data['tipo'], 'BAIRRO')

    def test_localidade_rejeita_valor_invalido(self):
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])

        response = self.client.post(
            '/api/localidades/',
            {'nome': 'não informado', 'tipo': 'BAIRRO'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('nome', response.data)

    def test_lista_ruas_filtra_por_localidade(self):
        localidade_a = Localidade.objects.create(nome='CENTRO TESTE', tipo='BAIRRO')
        localidade_b = Localidade.objects.create(nome='CAIAMBE TESTE', tipo='DISTRITO')
        Rua.objects.create(nome='RUA A', localidade=localidade_a)
        Rua.objects.create(nome='RUA B', localidade=localidade_b)

        response = self.client.get(f'/api/ruas/?localidade_id={localidade_a.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['nome'], 'RUA A')

    def test_admin_cria_rua_normalizando_abreviacao(self):
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])
        localidade = Localidade.objects.create(nome='SANTA LUZIA TESTE', tipo='BAIRRO')

        response = self.client.post(
            '/api/ruas/',
            {
                'nome': '  av.  principal ',
                'localidade': str(localidade.id),
                'criada_automaticamente': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['nome'], 'AVENIDA PRINCIPAL')
        self.assertEqual(response.data['localidade_id'], str(localidade.id))

    def test_rua_rejeita_duplicidade_na_mesma_localidade(self):
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])
        localidade = Localidade.objects.create(nome='MUTIRAO TESTE', tipo='BAIRRO')
        Rua.objects.create(nome='TRAVESSA SAO JOSE', localidade=localidade)

        response = self.client.post(
            '/api/ruas/',
            {
                'nome': 'trav. sao jose',
                'localidade': str(localidade.id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('nome', response.data)

    def test_usuario_sem_role_admin_nao_pode_mutar_localidade_ou_rua(self):
        localidade = Localidade.objects.create(nome='ABIAL TESTE', tipo='BAIRRO')

        response_localidade = self.client.post(
            '/api/localidades/',
            {'nome': 'NOVA LOCALIDADE', 'tipo': 'COMUNIDADE'},
            format='json',
        )
        response_rua = self.client.post(
            '/api/ruas/',
            {'nome': 'RUA NOVA', 'localidade': str(localidade.id)},
            format='json',
        )

        self.assertEqual(response_localidade.status_code, 403)
        self.assertEqual(response_rua.status_code, 403)


class ImportacaoCidadaoServiceTests(TestCase):
    def test_importacao_usa_staging_uuid_e_nao_relaciona_por_nome(self):
        linhas = [
            LinhaImportacaoCidadao(
                staging_uuid='11111111-1111-1111-1111-111111111111',
                nome='MARIA DA SILVA',
                cpf='12345678900',
                bairro='Centro',
                logradouro='Av. Principal',
            ),
            LinhaImportacaoCidadao(
                staging_uuid='22222222-2222-2222-2222-222222222222',
                nome='MARIA DA SILVA',
                cpf='98765432100',
                bairro='Centro',
                logradouro='Av. Principal',
            ),
        ]

        resultado = importar_linhas_cidadaos(linhas)

        self.assertEqual(len(resultado), 2)
        self.assertEqual(Cidadao.objects.filter(nome='MARIA DA SILVA').count(), 2)
        self.assertEqual(Documento.objects.filter(cpf='12345678900').count(), 1)
        self.assertEqual(Documento.objects.filter(cpf='98765432100').count(), 1)

    def test_importacao_permte_endereco_minimo_com_campos_nulos(self):
        resultado = importar_linhas_cidadaos(
            [
                LinhaImportacaoCidadao(
                    staging_uuid='33333333-3333-3333-3333-333333333333',
                    nome='JOAO TESTE',
                    cpf='11122233344',
                    bairro='Jerusalem',
                    logradouro='Rua sem numero',
                    numero=None,
                    cep=None,
                )
            ]
        )

        cidadao = Cidadao.objects.get(id=resultado[0]['cidadao_id'])
        self.assertIsNone(cidadao.endereco.numero)
        self.assertIsNone(cidadao.endereco.cep)
        self.assertIsNone(cidadao.endereco.possui_luz)
        self.assertFalse(cidadao.possui_deficiencia)
        self.assertFalse(cidadao.autorizacao_uso_imagem)

    def test_importacao_cria_localidade_e_rua_normalizadas(self):
        importar_linhas_cidadaos(
            [
                LinhaImportacaoCidadao(
                    staging_uuid='44444444-4444-4444-4444-444444444444',
                    nome='ANA TESTE',
                    cpf='44455566677',
                    bairro='  centro  ',
                    logradouro=' trav. santa rita ',
                )
            ]
        )

        self.assertTrue(Localidade.objects.filter(nome='CENTRO').exists())
        self.assertTrue(Rua.objects.filter(nome='TRAVESSA SANTA RITA').exists())

    def test_importacao_ignora_data_nascimento_invalida(self):
        resultado = importar_linhas_cidadaos(
            [
                LinhaImportacaoCidadao(
                    staging_uuid='55555555-5555-5555-5555-555555555555',
                    nome='CARLA TESTE',
                    cpf='99988877766',
                    data_nascimento='19999-11-11',
                    bairro='Centro',
                    logradouro='Rua A',
                )
            ]
        )

        cidadao = Cidadao.objects.get(id=resultado[0]['cidadao_id'])
        self.assertIsNone(cidadao.data_nascimento)


class BeneficioAdminApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.beneficio = Beneficio.objects.create(
            nome='Auxilio Municipal',
            descricao='Beneficio de apoio financeiro.',
            ativo=True,
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

    def test_listar_beneficios_nao_faz_n_plus_um_em_atualizado_por(self):
        Beneficio.objects.create(
            nome='Beneficio A',
            descricao='A',
            ativo=True,
            atualizado_por=self.user,
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Beneficio.objects.create(
            nome='Beneficio B',
            descricao='B',
            ativo=False,
            atualizado_por=self.user,
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Beneficio.objects.create(
            nome='Beneficio C',
            descricao='C',
            ativo=True,
            atualizado_por=self.user,
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        with self.assertNumQueries(1):
            response = self.client.get('/api/beneficios/')

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 3)

    def test_editar_beneficio_exige_role_admin(self):
        response = self.client.patch(
            f'/api/beneficios/{self.beneficio.id}/',
            {'nome': 'Novo nome'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data['detail'],
            'Você não tem permissão para editar benefício.',
        )
        self.beneficio.refresh_from_db()
        self.assertEqual(self.beneficio.nome, 'Auxilio Municipal')

    def test_editar_beneficio_com_role_admin(self):
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])

        response = self.client.patch(
            f'/api/beneficios/{self.beneficio.id}/',
            {'nome': 'Novo nome'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.beneficio.refresh_from_db()
        self.assertEqual(self.beneficio.nome, 'Novo nome')

    def test_excluir_beneficio_exige_role_admin(self):
        response = self.client.delete(f'/api/beneficios/{self.beneficio.id}/')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data['detail'],
            'Você não tem permissão para excluir benefício.',
        )
        self.assertTrue(Beneficio.objects.filter(id=self.beneficio.id).exists())

    def test_excluir_beneficio_com_role_admin(self):
        self.set_roles(['USER-BOLSA-TEFE', 'USER-BOLSA-TEFE-ADMIN'])

        response = self.client.delete(f'/api/beneficios/{self.beneficio.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Beneficio.objects.filter(id=self.beneficio.id).exists())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, MEDIA_URL='/media/')
class DocumentoAnexoApiTests(BaseApiTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.cidadao = Cidadao.objects.create(
            nome='Ana Documentos',
            telefone='92999991111',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Documento.objects.create(
            cidadao=self.cidadao,
            cpf='55544433322',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

    def _pdf_file(self, name='arquivo.pdf', content=b'%PDF-1.4 teste'):
        return SimpleUploadedFile(name, content, content_type='application/pdf')

    def _png_file(self, name='imagem.png', content=b'\x89PNG\r\n\x1a\nconteudo'):
        return SimpleUploadedFile(name, content, content_type='image/png')

    def test_upload_lista_e_inclusao_no_serializer_do_cidadao(self):
        response = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'rg_frente',
                'arquivo': self._pdf_file('rg.pdf'),
                'substituir': 'true',
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['tipo_documento'], 'rg_frente')
        self.assertEqual(response.data['tipo_documento_legacy'], 'rg')
        self.assertEqual(response.data['nome_arquivo'], 'rg.pdf')
        self.assertEqual(response.data['extensao'], 'pdf')
        self.assertEqual(response.data['status'], 'ENVIADO')
        self.assertIn('/media/', response.data['url'])

        list_response = self.client.get(f'/api/cidadaos/{self.cidadao.id}/documentos/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['tipo_documento'], 'rg_frente')

        detail_response = self.client.get(f'/api/cidadaos/{self.cidadao.id}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(len(detail_response.data['documentos_anexados']), 1)
        self.assertEqual(
            detail_response.data['documentos_anexados'][0]['tipo_documento'],
            'rg_frente',
        )
        self.assertEqual(
            detail_response.data['documentosAnexados'][0]['tipo_documento'],
            'rg_frente',
        )

    def test_upload_rg_verso_em_registro_separado(self):
        self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'rg_frente',
                'arquivo': self._pdf_file('rg-frente.pdf'),
                'substituir': 'true',
            },
        )

        response = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'rg_verso',
                'arquivo': self._pdf_file('rg-verso.pdf'),
                'substituir': 'true',
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['tipo_documento'], 'rg_verso')
        self.assertEqual(DocumentoAnexo.objects.filter(cidadao=self.cidadao).count(), 2)

    def test_upload_legado_rg_salva_como_rg_frente(self):
        response = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'rg',
                'arquivo': self._pdf_file('rg-legado.pdf'),
                'substituir': 'true',
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['tipo_documento'], 'rg_frente')
        self.assertTrue(
            DocumentoAnexo.objects.filter(
                cidadao=self.cidadao,
                tipo_documento='rg_frente',
            ).exists()
        )

    def test_leitura_normaliza_anexo_legado_rg_como_frente(self):
        DocumentoAnexo.objects.create(
            cidadao=self.cidadao,
            tipo_documento='rg',
            arquivo=self._pdf_file('rg-antigo.pdf'),
            nome_arquivo='rg-antigo.pdf',
            extensao='pdf',
            tamanho_bytes=12,
            status='ENVIADO',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        response = self.client.get(f'/api/cidadaos/{self.cidadao.id}/documentos/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]['tipo_documento'], 'rg_frente')
        self.assertEqual(response.data[0]['tipo_documento_legacy'], 'rg')

    def test_substitui_documento_por_tipo_sem_duplicar_registro(self):
        primeira_resposta = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'foto_residencia',
                'arquivo': self._png_file('foto1.png', b'primeira'),
                'substituir': 'true',
            },
        )
        documento_id = primeira_resposta.data['id']
        primeiro_arquivo = DocumentoAnexo.objects.get(id=documento_id).arquivo.path

        segunda_resposta = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'foto_residencia',
                'arquivo': self._pdf_file('foto2.pdf', b'segunda'),
                'substituir': 'true',
            },
        )

        self.assertEqual(segunda_resposta.status_code, 200)
        self.assertEqual(DocumentoAnexo.objects.count(), 1)
        documento = DocumentoAnexo.objects.get(
            cidadao=self.cidadao,
            tipo_documento='foto_residencia',
        )
        self.assertEqual(str(documento.id), documento_id)
        self.assertEqual(documento.extensao, 'pdf')
        self.assertFalse(os.path.exists(primeiro_arquivo))

    def test_upload_comprovante_residencia_em_imagem(self):
        response = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'comprovante_residencia',
                'arquivo': self._png_file('comprovante.png', b'comprovante'),
                'substituir': 'true',
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['tipo_documento'], 'comprovante_residencia')
        self.assertEqual(response.data['extensao'], 'png')
        self.assertEqual(DocumentoAnexo.objects.filter(cidadao=self.cidadao).count(), 1)

    def test_upload_foto_ato_atualizacao_em_imagem(self):
        response = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'foto_ato_atualizacao',
                'arquivo': self._png_file('foto-ato.png', b'foto-ato'),
                'substituir': 'true',
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['tipo_documento'], 'foto_ato_atualizacao')
        self.assertEqual(response.data['extensao'], 'png')
        self.assertTrue(
            DocumentoAnexo.objects.filter(
                cidadao=self.cidadao,
                tipo_documento='foto_ato_atualizacao',
            ).exists()
        )

    def test_upload_novos_documentos_do_beneficiario(self):
        tipos = [
            ('certidao_nascimento', 'nascimento.pdf'),
            ('certidao_casamento', 'casamento.pdf'),
            ('quitacao_eleitoral', 'quitacao.pdf'),
        ]

        for tipo_documento, nome_arquivo in tipos:
            response = self.client.post(
                f'/api/cidadaos/{self.cidadao.id}/documentos/',
                {
                    'tipo_documento': tipo_documento,
                    'arquivo': self._pdf_file(nome_arquivo),
                    'substituir': 'true',
                },
            )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data['tipo_documento'], tipo_documento)
            self.assertTrue(
                DocumentoAnexo.objects.filter(
                    cidadao=self.cidadao,
                    tipo_documento=tipo_documento,
                ).exists()
            )

    def test_delete_documento_por_id_e_por_tipo(self):
        documento = DocumentoAnexo.objects.create(
            cidadao=self.cidadao,
            tipo_documento='cpf',
            arquivo=self._pdf_file('cpf.pdf'),
            nome_arquivo='cpf.pdf',
            extensao='pdf',
            tamanho_bytes=12,
            status='ENVIADO',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        response = self.client.delete(
            f'/api/cidadaos/{self.cidadao.id}/documentos/{documento.id}/',
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(DocumentoAnexo.objects.filter(id=documento.id).exists())

        documento_tipo = DocumentoAnexo.objects.create(
            cidadao=self.cidadao,
            tipo_documento='comprovante_residencia',
            arquivo=self._pdf_file('comprovante.pdf'),
            nome_arquivo='comprovante.pdf',
            extensao='pdf',
            tamanho_bytes=12,
            status='ENVIADO',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        response_tipo = self.client.delete(
            f'/api/cidadaos/{self.cidadao.id}/documentos/comprovante_residencia/',
        )
        self.assertEqual(response_tipo.status_code, 204)
        self.assertFalse(DocumentoAnexo.objects.filter(id=documento_tipo.id).exists())

    def test_delete_rg_frente_e_rg_verso_separadamente(self):
        frente = DocumentoAnexo.objects.create(
            cidadao=self.cidadao,
            tipo_documento='rg_frente',
            arquivo=self._pdf_file('frente.pdf'),
            nome_arquivo='frente.pdf',
            extensao='pdf',
            tamanho_bytes=12,
            status='ENVIADO',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        verso = DocumentoAnexo.objects.create(
            cidadao=self.cidadao,
            tipo_documento='rg_verso',
            arquivo=self._pdf_file('verso.pdf'),
            nome_arquivo='verso.pdf',
            extensao='pdf',
            tamanho_bytes=12,
            status='ENVIADO',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        response = self.client.delete(
            f'/api/cidadaos/{self.cidadao.id}/documentos/rg_verso/',
        )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(DocumentoAnexo.objects.filter(id=frente.id).exists())
        self.assertFalse(DocumentoAnexo.objects.filter(id=verso.id).exists())

    def test_rejeita_tipo_invalido_e_arquivo_maior_que_limite(self):
        response_tipo = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'tipo_inexistente',
                'arquivo': self._pdf_file('quitacao.pdf'),
                'substituir': 'true',
            },
        )
        self.assertEqual(response_tipo.status_code, 400)
        self.assertEqual(response_tipo.data['detail'], 'Tipo de documento inválido.')

        arquivo_grande = SimpleUploadedFile(
            'grande.pdf',
            b'a' * (10 * 1024 * 1024 + 1),
            content_type='application/pdf',
        )
        response_tamanho = self.client.post(
            f'/api/cidadaos/{self.cidadao.id}/documentos/',
            {
                'tipo_documento': 'rg_frente',
                'arquivo': arquivo_grande,
                'substituir': 'true',
            },
        )
        self.assertEqual(response_tamanho.status_code, 400)
        self.assertEqual(
            response_tamanho.data['detail'],
            'Arquivo excede o tamanho máximo de 10 MB.',
        )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, MEDIA_URL='/media/')
class DocumentoPdfApiTests(BaseApiTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.cidadao = Cidadao.objects.create(
            nome='Ana PDF',
            telefone='92999992222',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )
        Documento.objects.create(
            cidadao=self.cidadao,
            cpf='88877766655',
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

    def _pdf_file(self, name='documento.pdf', content=b'%PDF-1.4 teste pdf'):
        return SimpleUploadedFile(name, content, content_type='application/pdf')

    def test_upload_pdf_devolve_url_no_serializer_do_cidadao(self):
        response = self.client.post(
            '/api/documentos/pdf/',
            {
                'cidadao_id': str(self.cidadao.id),
                'arquivo': self._pdf_file('cadastro.pdf'),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['sincronizado'])
        self.assertEqual(response.data['documento_pdf']['status'], 'SINCRONIZADO')
        self.assertIn('/media/', response.data['documento_pdf']['url'])

        detail_response = self.client.get(f'/api/cidadaos/{self.cidadao.id}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.data['documento_pdf']['nome_arquivo'],
            'cadastro.pdf',
        )

    def test_substitui_pdf_existente_e_valida_extensao_e_tamanho(self):
        primeiro = self.client.post(
            '/api/documentos/pdf/',
            {
                'cidadao_id': str(self.cidadao.id),
                'arquivo': self._pdf_file('primeiro.pdf'),
            },
        )
        self.assertEqual(primeiro.status_code, 200)

        antigo = Cidadao.objects.get(pk=self.cidadao.pk)
        primeiro_caminho = antigo.documento_pdf.path

        segundo = self.client.post(
            '/api/documentos/pdf/',
            {
                'cidadao_id': str(self.cidadao.id),
                'arquivo': self._pdf_file('segundo.pdf', b'%PDF-1.4 novo pdf'),
            },
        )

        self.assertEqual(segundo.status_code, 200)
        self.assertFalse(os.path.exists(primeiro_caminho))

        resposta_extensao = self.client.post(
            '/api/documentos/pdf/',
            {
                'cidadao_id': str(self.cidadao.id),
                'arquivo': SimpleUploadedFile(
                    'imagem.png',
                    b'not-a-pdf',
                    content_type='image/png',
                ),
            },
        )
        self.assertEqual(resposta_extensao.status_code, 400)
        self.assertEqual(
            resposta_extensao.data['detail'],
            'Envie um arquivo PDF válido.',
        )

        arquivo_grande = SimpleUploadedFile(
            'grande.pdf',
            b'a' * (25 * 1024 * 1024 + 1),
            content_type='application/pdf',
        )
        resposta_tamanho = self.client.post(
            '/api/documentos/pdf/',
            {
                'cidadao_id': str(self.cidadao.id),
                'arquivo': arquivo_grande,
            },
        )
        self.assertEqual(resposta_tamanho.status_code, 400)
        self.assertEqual(
            resposta_tamanho.data['detail'],
            'Arquivo excede o tamanho máximo de 25 MB.',
        )
