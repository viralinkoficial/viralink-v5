# Executor do Robô Central

A função `campaign-worker` processa até cinco itens vencidos por chamada.

## Segurança

- A chamada exige o cabeçalho `x-worker-secret`.
- O valor deve ser igual ao segredo `CAMPAIGN_WORKER_SECRET`.
- A atualização da fila usa apenas a chave de serviço disponível no ambiente Supabase.
- Um item é reivindicado antes do envio para impedir processamento duplicado.
- Cada item tem no máximo três tentativas.
- Falta de credencial ou mídia pausa o item; não registra publicação falsa.

## Segredos do projeto

Obrigatório:

- `CAMPAIGN_WORKER_SECRET`: valor aleatório forte.

Instagram:

- `INSTAGRAM_BUSINESS_ID`
- `INSTAGRAM_ACCESS_TOKEN`
- `META_GRAPH_VERSION` (opcional; padrão `v23.0`)

YouTube:

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

O YouTube também exige `payload.video_url` público e HTTPS. Sem vídeo preparado, o item é pausado com uma explicação.

## Relógio

Após implantar a função e configurar os segredos, crie um Cron Job no painel do Supabase:

- nome: `campaign-worker-every-minute`
- frequência: `* * * * *`
- método: POST
- URL: `https://pfbzdktlfdotsgfarhel.supabase.co/functions/v1/campaign-worker`
- cabeçalho: `x-worker-secret` com o mesmo valor de `CAMPAIGN_WORKER_SECRET`
- corpo JSON: `{}`

A configuração segue a orientação oficial do Supabase de usar Cron para invocar Edge Functions periodicamente.
