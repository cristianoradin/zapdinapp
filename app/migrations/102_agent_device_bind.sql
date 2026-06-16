-- Trava de ativação: token do agente vincula a 1 dispositivo (MachineGuid).
-- NULL = ainda não vinculado (primeira ativação vincula). Outro device é bloqueado
-- no connect do /agent. Admin pode liberar (NULL) pra trocar de máquina.
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS bound_device_id TEXT;
