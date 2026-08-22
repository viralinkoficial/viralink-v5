# YouTube Shorts automático

Esta automação usa a fila `campaign_queue` já existente no VIRALINK.

## Fluxo

1. O Robô Central coloca produtos no canal `youtube`.
2. O GitHub Actions executa às 12h, 18h e 21h (horário de Belém).
3. A imagem do produto vira um vídeo vertical de 22 segundos com texto e trilha instrumental própria.
4. O vídeo é publicado como público no YouTube e o ID fica registrado na fila.
5. Falhas são tentadas novamente até três vezes.

## Segredos necessários no GitHub

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

O refresh token exige uma única autorização inicial do canal. Depois, as execuções são automáticas.
