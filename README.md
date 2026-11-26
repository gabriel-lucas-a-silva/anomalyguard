# AnomalyGuard

Projeto da minha monografia do MBA em Engenharia de Software (USP/PECE).

A ideia é ajudar quem está de plantão a achar a causa de um incidente em microsserviços. Quando chega um alerta do Prometheus, o sistema coleta métricas e logs do momento, roda o TORAI (Pham et al., 2026) e mostra no site os três serviços mais prováveis de serem a causa, com uma porcentagem e uma explicação em português. A explicação é escrita pelo Gemini e passa por uma checagem simples: as citações e os números do texto precisam existir nas evidências.

O ambiente de testes é o [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo), uma loja de exemplo com dados sintéticos. Para medir a acurácia, o sistema liga falhas conhecidas no Demo e compara o resultado do TORAI com a causa real (Top 1 e Top 3).

## Tecnologias

- Back-end em Python 3.8 com FastAPI (o TORAI precisa do Python 3.8)
- PostgreSQL
- Site em React com TypeScript e Vite
- Docker Compose
- Gemini para a explicação (opcional)

O código do TORAI vem do pacote RCAEval, dos autores do método (licença MIT). Mais detalhes em `backend/NOTICE.md`.

## Como rodar

Precisa de Docker Desktop com WSL 2, o OpenTelemetry Demo 3.1.0 em `~/otel-demo` no Ubuntu e Node.js 22.

1. Copie o `.env.example` para `.env` e preencha a senha do banco e o token do webhook. A chave do Gemini é opcional; sem ela, a explicação usa um texto automático.
2. Rode `scripts\subir.ps1`. Ele sobe o Demo, as regras de alerta, o back-end, o banco e o site.
3. Abra http://127.0.0.1:5174.

Para parar: `scripts\parar.ps1`. O histórico fica salvo no banco.

Dica: espere uns 15 minutos depois de subir antes de simular uma falha, porque o Demo demora para estabilizar.

## O que dá para fazer no site

- Ver as investigações chegando em tempo real, com as etapas e o Top 3
- Ler a explicação de cada resultado
- Simular uma falha (pagamento falhando ou banco do catálogo travado)
- Ver se o TORAI acertou a causa (verde ou vermelho)
- Rodar uma campanha de acurácia, que simula várias falhas seguidas e calcula Top 1 e Top 3

## Testes

```
docker build --target test -t ag2-backend-test backend
docker run --rm ag2-backend-test

cd web
npm test
```

## Limitações

- É uma prova de conceito, com dados sintéticos e poucos tipos de falha.
- A checagem da explicação confere citações e números, não se o raciocínio está certo.
- O modo de simulação não tem autenticação, então só deve ser usado localmente.

## Licença

MIT
