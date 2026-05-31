# Auditoria LGPD — ZapDin

**Responsável pelo tratamento:** Empresa contratante do serviço (controladora)  
**Responsável técnico:** ZapDin (operadora de dados)  
**Data desta revisão:** 2026-05-16

---

## Dados pessoais armazenados

| Tabela | Dados pessoais | Base legal | Retenção |
|--------|---------------|------------|---------|
| `usuarios` | username, password_hash | Execução de contrato | Enquanto a conta estiver ativa |
| `contatos` | phone, nome | Legítimo interesse / consentimento | Até exclusão manual ou cancelamento |
| `mensagens` | destinatario (phone), mensagem | Execução de contrato | 90 dias (limpeza manual recomendada) |
| `arquivos` | destinatario (phone) | Execução de contrato | 90 dias |
| `avaliacoes` | phone, nome_cliente, comentario | Legítimo interesse | 1 ano |
| `campanha_envios` | phone, nome | Execução de contrato | 90 dias |
| `sessoes_wa` | phone (do número WA) | Execução de contrato | Enquanto sessão ativa |
| `pdv_sessoes` | phone | Execução de contrato | 90 dias |

---

## Dados NÃO armazenados (por design)

- Senhas em texto puro — apenas `bcrypt` hash (rounds ≥ 12)
- Tokens ERP em texto puro — apenas SHA-256 hash (M8)
- Cartão de crédito, dados bancários, CPF/RG — nunca coletados
- Localização geográfica — não coletada
- Dados biométricos — não coletados

---

## Direitos do titular (Art. 18 LGPD)

| Direito | Implementação atual | Pendência |
|---------|--------------------|-----------| 
| Confirmação e acesso | Manual (DBA exporta do banco) | Endpoint `/api/dados-pessoais` não implementado |
| Correção | Via interface de contatos | ✅ |
| Eliminação | Exclusão de contatos | Não há endpoint de exclusão em massa por titular |
| Portabilidade | Não implementado | Exportação CSV planejada |
| Revogação de consentimento | Não implementado | ⚠️ Pendente |
| Oposição | Não implementado | ⚠️ Pendente |

---

## Medidas técnicas de proteção

- **Autenticação**: cookies de sessão assinados com `itsdangerous` (HMAC-SHA256)
- **Senhas**: `bcrypt` com rounds ≥ 12 (tempo de processamento > 100ms)
- **Tokens**: SHA-256 hash no banco, token puro apenas em memória durante auth
- **Logout seguro**: tokens revogados persistidos em `invalidated_sessions` (M3)
- **Rate limiting**: login (10/min), ERP (60/min), ativação (5/h) — por IP
- **XSS**: `html.escape()` em todos os campos interpolados no HTML
- **SQL Injection**: consultas parametrizadas (sem f-strings em queries)
- **IDOR**: todas as queries filtram por `empresa_id` (tenant isolation)
- **Headers HTTP**: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`

---

## Retenção recomendada (a implementar)

Rodar mensalmente via cron ou manualmente:

```sql
-- Remove mensagens com mais de 90 dias
DELETE FROM mensagens WHERE created_at < NOW() - INTERVAL '90 days';
DELETE FROM arquivos   WHERE created_at < NOW() - INTERVAL '90 days';
DELETE FROM campanha_envios WHERE created_at < NOW() - INTERVAL '90 days';

-- Remove sessões blacklisted expiradas (já implementado no reporter.py)
DELETE FROM invalidated_sessions WHERE invalidated_at < NOW() - INTERVAL '24 hours';
```

---

## Débitos técnicos de segurança (CSP e outros)

| # | Item | Impacto | Esforço |
|---|------|---------|---------|
| T1 | Content-Security-Policy | Alto — previne XSS avançado | Alto (refatorar inline JS) |
| T2 | Endpoint de exportação de dados (portabilidade) | Médio | Médio |
| T3 | Endpoint de exclusão por titular | Médio | Baixo |
| T4 | Limpeza automática de dados antigos (cron) | Médio | Baixo |
| T5 | HSTS (só aplicável com HTTPS/proxy reverso) | Médio | Baixo |
