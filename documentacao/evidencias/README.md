# Evidências verificadas em 15/10/2026

O código desta revisão foi executado na porta local 8086. O registro checagem-runtime.json contém APROVADO_RUNTIME, cinco serviços, nove HTTP 200, três destinos X-Upstream e o mesmo SHA-256 do HTML. persistencia-2026-10-15.txt registra stop/up e a aprovação posterior.

## Capturas reais

| Arquivo em capturas/ | Conteúdo |
|---|---|
| 01-terminal-containers.png | Terminal real: cinco serviços ativos, saúde e porta 8086 |
| 02-terminal-balanceamento.png | Terminal real: nove cabeçalhos X-Upstream e HTTP 200 |
| 03-terminal-validacao.png | Terminal real: nginx -t, php -l, APROVADO_RUNTIME e 12 tabelas |
| site-desktop.png | Página inicial instalada, viewport 1440 px |
| site-mobile.png | Página inicial instalada, viewport 390 px |
| navegador-http.json | Nove respostas Document observadas por Chromium/CDP, com status e X-Upstream |

As capturas do Terminal foram feitas diretamente de janelas dedicadas, excluindo a barra de título. As imagens da aplicação foram capturadas pelo navegador, com perfil novo e sem autenticação. Não há captura visual de DevTools: os cabeçalhos aparecem no terminal real e no JSON do navegador. Os IPs podem mudar em outra execução.

## Reproduzir

No Terminal configurado para este Docker, na pasta do projeto:

```sh
python3 scripts/preparar.py
docker-compose config --quiet
docker-compose up -d
docker-compose ps
python3 scripts/verificar.py
```

O verificador não inicia, para ou remove contêineres. Ele grava texto/JSON, sem produzir screenshots. Código de saída 2 indica bloqueio/reprovação. Os arquivos de verificação estática registram a estrutura e não substituem os testes de execução. Não houve teste de carga.

Para nova captura, mostre apenas os comandos e a aplicação local. Não inclua senhas, arquivos de segredos, cookies ou telas pessoais.

## Capturas da execução

![Cinco serviços ativos](capturas/01-terminal-containers.png)

![Balanceamento e HTTP 200](capturas/02-terminal-balanceamento.png)

![Validação e banco](capturas/03-terminal-validacao.png)

![Aplicação em desktop](capturas/site-desktop.png)

![Aplicação em celular](capturas/site-mobile.png)
