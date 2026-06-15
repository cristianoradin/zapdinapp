from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKeyConstraint, Index, Integer, MetaData, Numeric, PrimaryKeyConstraint, Table, Text, UniqueConstraint, literal_column, text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()


t_agenda_alertas_enviados = Table(
    'agenda_alertas_enviados', metadata,
    Column('compromisso_id', BigInteger, primary_key=True),
    Column('antecedencia_min', Integer, primary_key=True),
    Column('enviado_em', DateTime(True), server_default=text('now()')),
    PrimaryKeyConstraint('compromisso_id', 'antecedencia_min', name='agenda_alertas_enviados_pkey')
)

t_agenda_compromissos = Table(
    'agenda_compromissos', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('usuario_id', BigInteger, nullable=False),
    Column('data', Date, nullable=False),
    Column('hora_inicio', Text),
    Column('hora_fim', Text),
    Column('titulo', Text, nullable=False),
    Column('descricao', Text),
    Column('cor', Text, server_default=text("'#3d7f1f'::text")),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('link', Text, server_default=text("''::text")),
    Column('alerta_enviado_em', DateTime(True)),
    PrimaryKeyConstraint('id', name='agenda_compromissos_pkey'),
    Index('idx_agenda_alerta_pendente', 'empresa_id', 'data', postgresql_where='(alerta_enviado_em IS NULL)'),
    Index('idx_agenda_emp_data', 'empresa_id', 'data')
)

t_agenda_wa_usuarios = Table(
    'agenda_wa_usuarios', metadata,
    Column('id', Integer, primary_key=True),
    Column('empresa_id', Integer, nullable=False),
    Column('phone', Text, nullable=False),
    Column('nome', Text, nullable=False, server_default=text("''::text")),
    Column('ativo', Boolean, nullable=False, server_default=text('true')),
    Column('recebe_alertas', Boolean, nullable=False, server_default=text('true')),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('morning_digest_hora', Text),
    Column('morning_digest_enviado', Date),
    Column('alert_antecedencias', Text, server_default=text("'[60]'::text")),
    PrimaryKeyConstraint('id', name='agenda_wa_usuarios_pkey'),
    UniqueConstraint('empresa_id', 'phone', name='agenda_wa_usuarios_empresa_id_phone_key'),
    Index('idx_agenda_wa_usuarios_emp', 'empresa_id', 'phone', postgresql_where='(ativo = true)')
)

t_empresas = Table(
    'empresas', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('cnpj', Text, nullable=False),
    Column('nome', Text, nullable=False),
    Column('token', Text, nullable=False),
    Column('ativo', Boolean, server_default=text('true')),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('menus', Text),
    PrimaryKeyConstraint('id', name='empresas_pkey'),
    UniqueConstraint('cnpj', name='empresas_cnpj_key'),
    UniqueConstraint('token', name='empresas_token_key')
)

t_empresas_contabil = Table(
    'empresas_contabil', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('nome', Text, nullable=False),
    Column('cnpj', Text),
    Column('ie', Text),
    Column('cpf', Text),
    Column('rg', Text),
    Column('endereco', Text),
    Column('numero_endereco', Text),
    Column('bairro', Text),
    Column('cep', Text),
    Column('cidade', Text),
    Column('uf', Text),
    Column('telefone', Text, nullable=False),
    Column('email', Text),
    Column('regime_tributario', Text, server_default=text("'simples_nacional'::text")),
    Column('ativo', Boolean, server_default=text('true')),
    Column('boas_vindas_enviadas', Boolean, server_default=text('false')),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('updated_at', DateTime(True), server_default=text('now()')),
    PrimaryKeyConstraint('id', name='empresas_contabil_pkey'),
    Index('idx_empresas_contabil_telefone', 'telefone')
)

t_invalidated_sessions = Table(
    'invalidated_sessions', metadata,
    Column('token_hash', Text, primary_key=True),
    Column('invalidated_at', DateTime(True), server_default=text('now()')),
    PrimaryKeyConstraint('token_hash', name='invalidated_sessions_pkey'),
    Index('idx_invalidated_sessions_at', 'invalidated_at')
)

t_postits = Table(
    'postits', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('usuario_id', BigInteger, nullable=False),
    Column('titulo', Text, server_default=text("''::text")),
    Column('conteudo', Text, server_default=text("''::text")),
    Column('cor', Text, server_default=text("'#fef08a'::text")),
    Column('ordem', Integer, server_default=text('0')),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('updated_at', DateTime(True), server_default=text('now()')),
    PrimaryKeyConstraint('id', name='postits_pkey'),
    Index('idx_postits_emp_user', 'empresa_id', 'usuario_id')
)

t_schema_migrations = Table(
    'schema_migrations', metadata,
    Column('version', Text, primary_key=True),
    Column('applied_at', DateTime(True), server_default=text('now()')),
    Column('descricao', Text),
    PrimaryKeyConstraint('version', name='schema_migrations_pkey')
)

t_system_logs = Table(
    'system_logs', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', Integer),
    Column('nivel', Text, nullable=False, server_default=text("'info'::text")),
    Column('modulo', Text, nullable=False, server_default=text("'sistema'::text")),
    Column('acao', Text, nullable=False, server_default=text("''::text")),
    Column('mensagem', Text, nullable=False, server_default=text("''::text")),
    Column('detalhe', Text),
    Column('created_at', DateTime(True), nullable=False, server_default=text('now()')),
    PrimaryKeyConstraint('id', name='system_logs_pkey'),
    Index('idx_system_logs_empresa_created', 'empresa_id', literal_column('created_at DESC')),
    Index('idx_system_logs_modulo', 'modulo'),
    Index('idx_system_logs_nivel', 'nivel')
)

t_worker_heartbeats = Table(
    'worker_heartbeats', metadata,
    Column('worker_name', Text, primary_key=True),
    Column('last_seen', DateTime(True), nullable=False, server_default=text('now()')),
    Column('status', Text, nullable=False, server_default=text("'ok'::text")),
    Column('detail', Text),
    PrimaryKeyConstraint('worker_name', name='worker_heartbeats_pkey')
)

t_alertas_criticos_pendentes = Table(
    'alertas_criticos_pendentes', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('nome', Text, server_default=text("''::text")),
    Column('telefone_cliente', Text, server_default=text("''::text")),
    Column('nota', Integer, nullable=False),
    Column('vendedor', Text, server_default=text("''::text")),
    Column('comentario', Text, server_default=text("''::text")),
    Column('data_avaliacao', DateTime(True), server_default=text('now()')),
    Column('tentativas', Integer, server_default=text('0')),
    Column('criado_em', DateTime(True), server_default=text('now()')),
    Column('enviado_em', DateTime(True)),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='alertas_criticos_pendentes_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='alertas_criticos_pendentes_pkey'),
    Index('idx_alertas_criticos_empresa', 'empresa_id', postgresql_where='(enviado_em IS NULL)')
)

t_arquivos = Table(
    'arquivos', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('nome_original', Text, nullable=False),
    Column('nome_arquivo', Text, nullable=False),
    Column('tamanho', Integer),
    Column('destinatario', Text),
    Column('sessao_id', Text),
    Column('caption', Text),
    Column('status', Text, server_default=text("'pending'::text")),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('sent_at', DateTime(True)),
    Column('delivered_at', DateTime(True)),
    Column('read_at', DateTime(True)),
    Column('erro', Text),
    Column('nome_destinatario', Text, server_default=text("''::text")),
    CheckConstraint("status = ANY (ARRAY['queued'::text, 'pending'::text, 'sent'::text, 'failed'::text, 'delivered'::text, 'read'::text])", name='chk_arquivos_status'),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='arquivos_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='arquivos_pkey'),
    Index('idx_arquivos_empresa', 'empresa_id'),
    Index('idx_arquivos_empresa_created', 'empresa_id', literal_column('created_at DESC')),
    Index('idx_arquivos_status', 'empresa_id', 'status'),
    Index('idx_arquivos_status_worker', 'status', 'id')
)

t_avaliacoes = Table(
    'avaliacoes', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('token', Text, nullable=False),
    Column('phone', Text, nullable=False),
    Column('nome_cliente', Text, server_default=text("''::text")),
    Column('vendedor', Text, server_default=text("''::text")),
    Column('valor', Text, server_default=text("''::text")),
    Column('nota', Integer),
    Column('comentario', Text),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('respondido_em', DateTime(True)),
    CheckConstraint('nota IS NULL OR nota >= 1 AND nota <= 5', name='chk_avaliacoes_nota'),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='avaliacoes_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='avaliacoes_pkey'),
    UniqueConstraint('token', name='avaliacoes_token_key'),
    Index('idx_avaliacoes_empresa', 'empresa_id'),
    Index('idx_avaliacoes_empresa_created', 'empresa_id', literal_column('created_at DESC')),
    Index('idx_avaliacoes_phone_created', 'phone', literal_column('created_at DESC')),
    Index('idx_avaliacoes_respondido', 'empresa_id', 'respondido_em', postgresql_where='(respondido_em IS NOT NULL)'),
    Index('idx_avaliacoes_token', 'token'),
    Index('idx_avaliacoes_vendedor', 'empresa_id', 'vendedor')
)

t_campanhas = Table(
    'campanhas', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('nome', Text, nullable=False),
    Column('tipo', Text, nullable=False, server_default=text("'text'::text")),
    Column('mensagem', Text, server_default=text("''::text")),
    Column('status', Text, server_default=text("'draft'::text")),
    Column('total', Integer, server_default=text('0')),
    Column('enviados', Integer, server_default=text('0')),
    Column('erros', Integer, server_default=text('0')),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('started_at', DateTime(True)),
    Column('done_at', DateTime(True)),
    Column('agendado_em', DateTime(True)),
    Column('updated_at', DateTime(True), server_default=text('now()')),
    CheckConstraint("status = ANY (ARRAY['draft'::text, 'scheduled'::text, 'running'::text, 'paused'::text, 'done'::text])", name='chk_campanhas_status'),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='campanhas_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='campanhas_pkey'),
    Index('idx_campanhas_empresa', 'empresa_id'),
    Index('idx_campanhas_status', 'status')
)

t_chat_historico = Table(
    'chat_historico', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('phone', Text, nullable=False),
    Column('role', Text, nullable=False),
    Column('conteudo', Text, nullable=False),
    Column('created_at', DateTime(True), server_default=text('now()')),
    CheckConstraint("role = ANY (ARRAY['user'::text, 'assistant'::text])", name='chat_historico_role_check'),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='chat_historico_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='chat_historico_pkey'),
    Index('idx_chat_hist_empresa_phone', 'empresa_id', 'phone', literal_column('created_at DESC'))
)

t_chatbot_aprendizado = Table(
    'chatbot_aprendizado', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('phone', Text, nullable=False),
    Column('pergunta', Text, nullable=False),
    Column('resposta', Text, nullable=False),
    Column('aprovado', Boolean),
    Column('created_at', DateTime(True), server_default=text('now()')),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='chatbot_aprendizado_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='chatbot_aprendizado_pkey'),
    Index('idx_chatbot_aprendizado_empresa', 'empresa_id', 'aprovado')
)

t_chatbot_config = Table(
    'chatbot_config', metadata,
    Column('empresa_id', BigInteger, primary_key=True),
    Column('ativo', Boolean, server_default=text('true')),
    Column('system_prompt', Text, server_default=text("''::text")),
    Column('boas_vindas_ativo', Boolean, server_default=text('false')),
    Column('boas_vindas_msg', Text, server_default=text("''::text")),
    Column('memoria_ia_ativa', Boolean, server_default=text('true')),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='chatbot_config_empresa_id_fkey'),
    PrimaryKeyConstraint('empresa_id', name='chatbot_config_pkey')
)

t_chatbot_faq = Table(
    'chatbot_faq', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('pergunta', Text, nullable=False),
    Column('resposta', Text, nullable=False),
    Column('ativo', Boolean, server_default=text('true')),
    Column('created_at', DateTime(True), server_default=text('now()')),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='chatbot_faq_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='chatbot_faq_pkey'),
    Index('idx_chatbot_faq_empresa', 'empresa_id', postgresql_where='(ativo = true)')
)

t_chatbot_memoria_ia = Table(
    'chatbot_memoria_ia', metadata,
    Column('id', Integer, primary_key=True),
    Column('empresa_id', Integer, nullable=False),
    Column('intencao', Text, nullable=False, server_default=text("''::text")),
    Column('variacoes', Text, nullable=False, server_default=text("'[]'::text")),
    Column('resposta_ideal', Text, nullable=False, server_default=text("''::text")),
    Column('confianca', Integer, server_default=text('50')),
    Column('usos', Integer, server_default=text('1')),
    Column('aprovado', Boolean),
    Column('fonte', Text, server_default=text("'ia'::text")),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('updated_at', DateTime(True), server_default=text('now()')),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='chatbot_memoria_ia_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='chatbot_memoria_ia_pkey'),
    Index('idx_memoria_ia_aprovado', 'empresa_id', 'aprovado'),
    Index('idx_memoria_ia_empresa', 'empresa_id')
)

t_config = Table(
    'config', metadata,
    Column('empresa_id', BigInteger, primary_key=True),
    Column('key', Text, primary_key=True),
    Column('value', Text, nullable=False),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='config_empresa_id_fkey'),
    PrimaryKeyConstraint('empresa_id', 'key', name='config_pkey')
)

t_contabil_wa_pendentes = Table(
    'contabil_wa_pendentes', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger),
    Column('telefone', Text, nullable=False),
    Column('nome', Text, nullable=False),
    Column('tentativas', Integer, server_default=text('0')),
    Column('status', Text, server_default=text("'pendente'::text")),
    Column('criado_em', DateTime(True), server_default=text('now()')),
    Column('enviado_em', DateTime(True)),
    ForeignKeyConstraint(['empresa_id'], ['empresas_contabil.id'], ondelete='CASCADE', name='contabil_wa_pendentes_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='contabil_wa_pendentes_pkey'),
    Index('idx_ctb_wa_pendentes_status', 'status', 'criado_em')
)

t_contatos = Table(
    'contatos', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('phone', Text, nullable=False),
    Column('nome', Text, server_default=text("''::text")),
    Column('ativo', Boolean, server_default=text('true')),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('origem', Text, server_default=text("'manual'::text")),
    Column('updated_at', DateTime(True), server_default=text('now()')),
    Column('chatbot_ativo', Boolean, server_default=text('false')),
    Column('boas_vindas_enviada', Boolean, server_default=text('false')),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='contatos_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='contatos_pkey'),
    UniqueConstraint('empresa_id', 'phone', name='contatos_empresa_id_phone_key'),
    Index('idx_contatos_empresa', 'empresa_id')
)

t_documentos_fiscais = Table(
    'documentos_fiscais', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger),
    Column('tipo', Text, server_default=text("'nfe'::text")),
    Column('status', Text, server_default=text("'recebido'::text")),
    Column('origem_wa', Text),
    Column('arquivo_path', Text),
    Column('arquivo_mime', Text),
    Column('arquivo_nome', Text),
    Column('dados_ocr', JSONB),
    Column('dados_manual', JSONB),
    Column('erro_msg', Text),
    Column('chave_acesso', Text),
    Column('numero_nf', Text),
    Column('emitente_nome', Text),
    Column('emitente_cnpj', Text),
    Column('destinatario_nome', Text),
    Column('destinatario_cnpj', Text),
    Column('valor_total', Numeric(14, 2)),
    Column('data_emissao', Date),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('updated_at', DateTime(True), server_default=text('now()')),
    ForeignKeyConstraint(['empresa_id'], ['empresas_contabil.id'], ondelete='CASCADE', name='documentos_fiscais_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='documentos_fiscais_pkey'),
    Index('idx_docs_fiscais_empresa', 'empresa_id', literal_column('created_at DESC')),
    Index('idx_docs_fiscais_status', 'status', literal_column('created_at DESC'))
)

t_grupos_contatos = Table(
    'grupos_contatos', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('nome', Text, nullable=False),
    Column('created_at', DateTime(True), server_default=text('now()')),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='grupos_contatos_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='grupos_contatos_pkey'),
    UniqueConstraint('empresa_id', 'nome', name='grupos_contatos_empresa_id_nome_key'),
    Index('idx_grupos_contatos_empresa', 'empresa_id')
)

t_mensagens = Table(
    'mensagens', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('sessao_id', Text),
    Column('destinatario', Text, nullable=False),
    Column('mensagem', Text),
    Column('tipo', Text, server_default=text("'text'::text")),
    Column('status', Text, server_default=text("'pending'::text")),
    Column('erro', Text),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('sent_at', DateTime(True)),
    Column('delivered_at', DateTime(True)),
    Column('read_at', DateTime(True)),
    Column('nome_destinatario', Text, server_default=text("''::text")),
    CheckConstraint("status = ANY (ARRAY['queued'::text, 'pending'::text, 'sent'::text, 'error'::text, 'failed'::text, 'delivered'::text, 'read'::text])", name='chk_mensagens_status'),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='mensagens_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='mensagens_pkey'),
    Index('idx_mensagens_empresa', 'empresa_id'),
    Index('idx_mensagens_empresa_created', 'empresa_id', literal_column('created_at DESC')),
    Index('idx_mensagens_empresa_sent', 'empresa_id', literal_column('sent_at DESC'), postgresql_where='(sent_at IS NOT NULL)'),
    Index('idx_mensagens_status', 'empresa_id', 'status'),
    Index('idx_mensagens_status_worker', 'status', 'id')
)

t_pdv_sessoes = Table(
    'pdv_sessoes', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('sessao_id', Text, nullable=False),
    Column('pdv_nome', Text, nullable=False, server_default=text("''::text")),
    Column('phone', Text),
    Column('status', Text, nullable=False, server_default=text("'unknown'::text")),
    Column('updated_at', DateTime(True), server_default=text('now()')),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='pdv_sessoes_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='pdv_sessoes_pkey'),
    UniqueConstraint('empresa_id', 'sessao_id', name='pdv_sessoes_empresa_id_sessao_id_key'),
    Index('idx_pdv_sessoes_empresa', 'empresa_id')
)

t_pdv_tokens = Table(
    'pdv_tokens', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('token', Text, nullable=False),
    Column('nome', Text, nullable=False, server_default=text("'PDV'::text")),
    Column('ativo', Boolean, server_default=text('true')),
    Column('criado_em', DateTime(True), server_default=text('now()')),
    Column('ultimo_uso', DateTime(True)),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='pdv_tokens_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='pdv_tokens_pkey'),
    UniqueConstraint('token', name='pdv_tokens_token_key'),
    Index('idx_pdv_tokens_ativo', 'ativo'),
    Index('idx_pdv_tokens_empresa', 'empresa_id')
)

t_sessoes_wa = Table(
    'sessoes_wa', metadata,
    Column('empresa_id', BigInteger, primary_key=True),
    Column('id', Text, primary_key=True),
    Column('nome', Text, nullable=False),
    Column('status', Text, server_default=text("'disconnected'::text")),
    Column('qr_data', Text),
    Column('phone', Text),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('last_seen', DateTime(True)),
    Column('usos', Text, server_default=text('\'["chatbot","campanhas","arquivos","agenda"]\'::text')),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='sessoes_wa_empresa_id_fkey'),
    PrimaryKeyConstraint('empresa_id', 'id', name='sessoes_wa_pkey'),
    Index('idx_sessoes_wa_empresa', 'empresa_id')
)

t_usuarios = Table(
    'usuarios', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger, nullable=False),
    Column('username', Text, nullable=False),
    Column('password_hash', Text, nullable=False),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('menus', Text),
    Column('avatar_url', Text),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='usuarios_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='usuarios_pkey'),
    UniqueConstraint('empresa_id', 'username', name='usuarios_empresa_id_username_key')
)

t_campanha_arquivos = Table(
    'campanha_arquivos', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('campanha_id', BigInteger, nullable=False),
    Column('nome_original', Text, nullable=False),
    Column('nome_arquivo', Text, nullable=False),
    Column('created_at', DateTime(True), server_default=text('now()')),
    ForeignKeyConstraint(['campanha_id'], ['campanhas.id'], ondelete='CASCADE', name='campanha_arquivos_campanha_id_fkey'),
    PrimaryKeyConstraint('id', name='campanha_arquivos_pkey')
)

t_campanha_envios = Table(
    'campanha_envios', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('campanha_id', BigInteger, nullable=False),
    Column('empresa_id', BigInteger, nullable=False),
    Column('phone', Text, nullable=False),
    Column('nome', Text, server_default=text("''::text")),
    Column('status', Text, server_default=text("'queued'::text")),
    Column('erro', Text),
    Column('created_at', DateTime(True), server_default=text('now()')),
    Column('sent_at', DateTime(True)),
    Column('delivered_at', DateTime(True)),
    Column('read_at', DateTime(True)),
    CheckConstraint("status = ANY (ARRAY['queued'::text, 'paused'::text, 'sent'::text, 'failed'::text, 'error'::text, 'delivered'::text, 'read'::text])", name='chk_envios_status'),
    ForeignKeyConstraint(['campanha_id'], ['campanhas.id'], ondelete='CASCADE', name='campanha_envios_campanha_id_fkey'),
    ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE', name='campanha_envios_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='campanha_envios_pkey'),
    Index('idx_campanha_envios_campanha', 'campanha_id'),
    Index('idx_campanha_envios_empresa_status', 'empresa_id', 'status'),
    Index('idx_campanha_envios_status', 'campanha_id', 'status')
)

t_contabil_feed = Table(
    'contabil_feed', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('empresa_id', BigInteger),
    Column('documento_id', BigInteger),
    Column('tipo', Text, nullable=False),
    Column('descricao', Text, nullable=False),
    Column('criado_em', DateTime(True), server_default=text('now()')),
    ForeignKeyConstraint(['documento_id'], ['documentos_fiscais.id'], ondelete='SET NULL', name='contabil_feed_documento_id_fkey'),
    ForeignKeyConstraint(['empresa_id'], ['empresas_contabil.id'], ondelete='SET NULL', name='contabil_feed_empresa_id_fkey'),
    PrimaryKeyConstraint('id', name='contabil_feed_pkey'),
    Index('idx_contabil_feed_ts', literal_column('criado_em DESC'))
)

t_grupo_contatos = Table(
    'grupo_contatos', metadata,
    Column('grupo_id', BigInteger, primary_key=True),
    Column('contato_id', BigInteger, primary_key=True),
    ForeignKeyConstraint(['contato_id'], ['contatos.id'], ondelete='CASCADE', name='grupo_contatos_contato_id_fkey'),
    ForeignKeyConstraint(['grupo_id'], ['grupos_contatos.id'], ondelete='CASCADE', name='grupo_contatos_grupo_id_fkey'),
    PrimaryKeyConstraint('grupo_id', 'contato_id', name='grupo_contatos_pkey'),
    Index('idx_grupo_contatos_contato', 'contato_id')
)

t_ocr_jobs = Table(
    'ocr_jobs', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('documento_id', BigInteger, nullable=False),
    Column('status', Text, nullable=False, server_default=text("'pending'::text")),
    Column('tentativas', Integer, server_default=text('0')),
    Column('erro', Text),
    Column('criado_em', DateTime(True), server_default=text('now()')),
    Column('processado_em', DateTime(True)),
    ForeignKeyConstraint(['documento_id'], ['documentos_fiscais.id'], ondelete='CASCADE', name='ocr_jobs_documento_id_fkey'),
    PrimaryKeyConstraint('id', name='ocr_jobs_pkey'),
    UniqueConstraint('documento_id', name='ocr_jobs_documento_id_key')
)
