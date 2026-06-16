-- Grupo de agente compartilhado: empresa pode usar o agente (número WhatsApp) de
-- OUTRA empresa "dona". NULL = usa o próprio agente. Dados continuam isolados por
-- empresa; só o transporte WS (envio/QR/estado) é roteado pra empresa dona.
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS agente_dono_empresa_id INTEGER REFERENCES empresas(id);
CREATE INDEX IF NOT EXISTS idx_empresas_agente_dono ON empresas(agente_dono_empresa_id);
