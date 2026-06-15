# Migrations do ZapDin App

Schema base congelado em `app/core/schema_baseline.py` (2026-06-09).
**Mudanças novas de schema entram AQUI**, nunca no baseline.

## Como criar

1. Próximo número: `ls *.sql | tail -1` → incrementa
2. Nome: `NNN_descricao_curta.sql` — comecar em **100** (001-011 sao historicas do baseline) (ex: `001_add_coluna_x.sql`)
3. SQL idempotente quando possível (`IF NOT EXISTS`)
4. Deploy normal — `init_db()` aplica no startup e registra em `schema_migrations`

## Regras

- Um arquivo = uma mudança lógica
- Roda em transação: ou aplica tudo ou nada
- NUNCA editar migration já aplicada em produção — criar uma nova corrigindo
