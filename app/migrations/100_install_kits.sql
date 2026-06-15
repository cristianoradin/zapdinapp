-- Kits de instalação self-service: link único com token embutido.
-- Kit expira em 7 dias e é invalidado quando o WhatsApp conecta (completed_at).
CREATE TABLE IF NOT EXISTS install_kits (
    id           BIGSERIAL PRIMARY KEY,
    kit_token    TEXT UNIQUE NOT NULL,
    empresa_id   BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_install_kits_token ON install_kits(kit_token);
CREATE INDEX IF NOT EXISTS idx_install_kits_empresa ON install_kits(empresa_id);
