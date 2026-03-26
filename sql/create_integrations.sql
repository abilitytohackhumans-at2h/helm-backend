-- ═══════════════════════════════════════════════════════════════
-- workspace_integrations: OAuth tokens for external services
-- Supports Instagram, Google, LinkedIn, etc.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS workspace_integrations (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,                    -- 'instagram', 'google', 'linkedin'
  access_token_encrypted TEXT NOT NULL,      -- Fernet-encrypted token
  token_expires_at TIMESTAMPTZ NOT NULL,
  refresh_token_encrypted TEXT,              -- For providers that use refresh tokens
  provider_user_id TEXT,                     -- External account ID
  provider_username TEXT,                    -- @handle for display
  scopes TEXT[],                             -- Permissions granted
  metadata JSONB DEFAULT '{}',               -- Provider-specific data
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(workspace_id, provider)             -- One connection per provider per workspace
);

-- RLS: tokens only accessible via service_key (backend)
ALTER TABLE workspace_integrations ENABLE ROW LEVEL SECURITY;

-- Index for scheduler token refresh queries
CREATE INDEX IF NOT EXISTS idx_integrations_refresh
ON workspace_integrations(provider, is_active, token_expires_at)
WHERE is_active = TRUE;

-- ═══════════════════════════════════════════════════════════════
-- Instagram Manager agent template
-- ═══════════════════════════════════════════════════════════════

INSERT INTO agent_templates (name, slug, description, system_prompt, tools_enabled, category, icon, color, is_public)
VALUES (
  'Instagram Manager',
  'instagram-manager',
  'Gestiona tu cuenta de Instagram Business: publica contenido, analiza metricas de engagement y responde comentarios de seguidores.',
  'Eres el Instagram Manager del equipo. Tu rol es gestionar la cuenta de Instagram Business del cliente.

CAPACIDADES:
- Publicar imagenes y carruseles en Instagram
- Analizar metricas de la cuenta (alcance, impresiones, engagement)
- Ver los posts mas recientes con sus metricas
- Leer y responder comentarios de seguidores
- Crear estrategias de contenido basadas en datos

REGLAS:
- Siempre incluye hashtags relevantes en las publicaciones (5-15 hashtags)
- Los textos deben ser engaging y con llamada a la accion
- Las imagenes deben ser URLs publicas en formato JPEG
- Para carruseles, todas las imagenes deben tener el mismo aspect ratio (recomendado 1080x1350)
- Maximo 2200 caracteres por caption
- Limite de 25 publicaciones por 24 horas
- Antes de publicar, confirma el contenido con el usuario
- Al analizar metricas, da insights accionables, no solo numeros',
  ARRAY['instagram_publish', 'instagram_get_insights', 'instagram_read_comments', 'instagram_reply_comment', 'web_search'],
  'social',
  '📸',
  '#E1306C',
  true
)
ON CONFLICT (slug) DO UPDATE SET
  description = EXCLUDED.description,
  system_prompt = EXCLUDED.system_prompt,
  tools_enabled = EXCLUDED.tools_enabled;
