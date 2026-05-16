# Módulos Frontend — ZapDin

Arquitetura vanilla JS modular. Cada arquivo é um módulo independente por tela.

## Ordem de carregamento (index.html)

```html
<script src="/static/js/modules/utils.js"></script>      <!-- 1. Utilitários base (api, showToast, escHtml, ZD.registry) -->
<script src="/static/js/modules/avaliacao.js"></script>   <!-- 2. Tela Avaliações -->
<script src="/static/js/modules/dashboard.js"></script>   <!-- 3. Dashboard (KPIs, recentes) -->
<!-- futuros módulos aqui -->
<script src="/static/js/app.js"></script>                 <!-- ÚLTIMO: orquestrador -->
```

## Padrão de módulo

Cada módulo usa IIFE para evitar poluição do escopo global.
Expõe apenas o necessário via `window.nomeFuncao` ou `ZD.registry`.

```js
(function () {
  'use strict';

  // Estado privado do módulo
  let _dadosPrivados = [];

  // Funções privadas (não expostas)
  function _helper() { ... }

  // Funções públicas (chamadas pelo HTML via onclick ou pelo app.js)
  window.minhaFuncaoPublica = function () { ... };

  // Registra no router de páginas
  document.addEventListener('DOMContentLoaded', () => {
    ZD.registry.register('minha-pagina', minhaFuncaoPublica);
  });
})();
```

## Módulos planejados

| Arquivo | Tela | Status |
|---|---|---|
| `utils.js` | Utilitários compartilhados (api, escHtml, showToast, ZD.registry) | ✅ Criado |
| `avaliacao.js` | Gestão de Avaliação | ✅ Criado |
| `dashboard.js` | Gestão de Envios (KPIs, fila, recentes) | ✅ Criado |
| `whatsapp.js` | Conectar WhatsApp | 🔲 Pendente |
| `campanhas.js` | Campanhas e disparos | 🔲 Pendente |
| `contatos.js` | Contatos e grupos | 🔲 Pendente |
| `mensagem.js` | Configurar Mensagem | 🔲 Pendente |
| `config.js` | Configurações de Envio | 🔲 Pendente |
| `arquivos.js` | Gestão de Arquivos | 🔲 Pendente |
| `tokens.js` | Token API + PDV | 🔲 Pendente |
| `telegram.js` | Configuração Telegram | 🔲 Pendente |

## Como adicionar uma nova tela

1. Criar `js/modules/nova-tela.js` com o padrão acima
2. Adicionar `<script src="/static/js/modules/nova-tela.js"></script>` no index.html **antes** de `app.js`
3. Registrar no router: `ZD.registry.register('nova-tela', loadNovaTela)`
4. No `onPageLoad` do `app.js`, adicionar: `else if (page === 'nova-tela') ZD.registry.dispatch('nova-tela')`
