# Backlog Priorizado — ZapDin

**Critério de priorização:** Impacto no cliente × facilidade de implementação × risco  
**Última revisão:** 2026-05-16  
**Responsável:** PM / Produto

---

## 🔴 Prioridade 1 — Agora (próximo sprint)

### P1-1 · Dashboard de campanha em tempo real
**Por quê:** Usuários disparam campanhas de 1.000+ contatos e não têm visibilidade do progresso.  
**Impacto:** Reduz chamados de suporte ("minha campanha travou?").  
**Entregável:** Barra de progresso com % enviados, botão pausar/retomar visível durante o disparo.  
**Estimativa:** 3 dias · **Risco:** Baixo (API já existe, só falta UI)

### P1-2 · Agendamento de campanha (UI)
**Por quê:** Coluna `agendado_em` já existe no banco; o worker já verifica `status='scheduled'`. Falta só o formulário de data/hora.  
**Impacto:** Permite envios fora do horário comercial sem intervenção manual.  
**Entregável:** Seletor de data/hora no modal de campanha.  
**Estimativa:** 2 dias · **Risco:** Baixo

### P1-3 · Exportação de relatório de avaliações (CSV)
**Por quê:** Clientes precisam apresentar NPS em reuniões gerenciais. Hoje copiam dados manualmente.  
**Impacto:** Economia de ~2h/mês por cliente; feature solicitada por 3 clientes.  
**Entregável:** Botão "Exportar CSV" na tela de Avaliações.  
**Estimativa:** 1 dia · **Risco:** Baixo

---

## 🟡 Prioridade 2 — Próximos 30 dias

### P2-1 · Multi-sessão WhatsApp com balanceamento de carga
**Por quê:** Clientes com alto volume (500+ mensagens/dia) sofrem bloqueio de um número.  
**Impacto:** Aumenta capacidade de envio sem comprar mais chips.  
**Entregável:** Worker distribui envios entre sessões conectadas por round-robin.  
**Estimativa:** 5 dias · **Risco:** Médio (tocar no worker de fila)

### P2-2 · Webhook de status de entrega
**Por quê:** ERPs precisam saber se a mensagem foi entregue/lida para acionar fluxo de cobrança.  
**Impacto:** Destrava integrações avançadas.  
**Entregável:** POST para URL configurável quando status muda (sent → delivered → read).  
**Estimativa:** 4 dias · **Risco:** Médio

### P2-3 · Importação de contatos via planilha (Excel/CSV UI)
**Por quê:** Hoje a importação é via API REST. Usuários sem TI não conseguem usar.  
**Impacto:** Amplia o perfil de usuários que conseguem usar o sistema autonomamente.  
**Entregável:** Upload de arquivo na tela de Contatos com preview e confirmação.  
**Estimativa:** 3 dias · **Risco:** Baixo

### P2-4 · Relatório de campanhas com gráfico de taxa de entrega
**Por quê:** Managers querem saber eficiência de cada campanha.  
**Entregável:** Tela de histórico com taxa enviados/erros por campanha + gráfico de barra.  
**Estimativa:** 3 dias · **Risco:** Baixo

---

## 🟢 Prioridade 3 — Backlog futuro (90 dias+)

### P3-1 · Chatbot simples (resposta automática por palavra-chave)
**Impacto:** Permite autoatendimento básico.  
**Estimativa:** 2 semanas · **Risco:** Alto (nova complexidade no worker)

### P3-2 · Integração nativa com Google Planilhas
**Impacto:** Clientes usam Planilhas como CRM improvisado.  
**Estimativa:** 1 semana · **Risco:** Médio (OAuth Google)

### P3-3 · App mobile (PWA) para aprovação de avaliações
**Impacto:** Gerentes querem ver avaliações no celular.  
**Estimativa:** 2 semanas · **Risco:** Baixo (frontend responsivo já existe)

### P3-4 · Endpoint LGPD de exportação de dados do titular
**Impacto:** Conformidade legal (Art. 18 LGPD).  
**Estimativa:** 2 dias · **Risco:** Baixo  
*(Registrado em LGPD.md como débito técnico T2)*

### P3-5 · Content-Security-Policy completo
**Impacto:** Elimina risco XSS avançado via scripts injetados.  
**Estimativa:** 3 dias (refatorar inline JS) · **Risco:** Médio  
*(Registrado em LGPD.md como débito técnico T1)*

---

## 🔵 Débitos técnicos priorizados

| # | Item | Sprint sugerido |
|---|------|----------------|
| DT-1 | Módulos JS restantes (dashboard.js, whatsapp.js, campanhas.js) | P1 |
| DT-2 | Limpeza automática de mensagens antigas (> 90 dias) | P2 |
| DT-3 | Testes E2E de campanha (iniciar → progresso → done) | P2 |
| DT-4 | Validação Pydantic M7 no ERP arquivo | P2 |
| DT-5 | Migração: hash de tokens ERP existentes (M8) | P2 |
| DT-6 | SECRET_KEY obrigatória em produção (M2) | P1 |

---

## Métricas de sucesso

| KPI | Baseline (Mai/26) | Meta (Ago/26) |
|-----|-------------------|---------------|
| NPS dos clientes | ? | ≥ 60 |
| Chamados de suporte/mês | ? | -30% |
| Taxa de erro em campanhas | ~5% | < 2% |
| Tempo médio de deploy | Manual (~15 min) | < 5 min (CI/CD) |
| Cobertura de testes | 40 testes | ≥ 80 testes |
