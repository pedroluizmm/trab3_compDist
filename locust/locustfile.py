"""Usuario que le um post do cenario selecionado (API atual do Locust 2.x).

Equivale ao exemplo do enunciado (HttpLocust/TaskSet/min_wait/max_wait), que foi
removido do Locust 1.0+: HttpLocust -> HttpUser/FastHttpUser, task_set -> @task,
min_wait/max_wait (ms) -> wait_time = between(s, s).

Variaveis de ambiente:
  CENARIO     imagem-1mb | texto-400kb | imagem-300kb (ver cenarios.json)
  ESPERA_MIN  pausa minima entre leituras, em segundos (padrao 5, como no PDF)
  ESPERA_MAX  pausa maxima, em segundos (padrao 9)
"""
import json
import os
from pathlib import Path

from locust import FastHttpUser, between, task

MANIFESTO = json.loads((Path(__file__).parent / 'cenarios.json').read_text(encoding='utf-8'))
CENARIO = os.environ.get('CENARIO', 'imagem-1mb')
if CENARIO not in MANIFESTO['cenarios']:
    raise SystemExit(f'CENARIO desconhecido: {CENARIO}; opcoes: {sorted(MANIFESTO["cenarios"])}')
ALVO = MANIFESTO['cenarios'][CENARIO]


class LeitorDoPost(FastHttpUser):
    wait_time = between(float(os.environ.get('ESPERA_MIN', 5)), float(os.environ.get('ESPERA_MAX', 9)))
    # O WordPress redireciona hosts diferentes de SITE_URL; o Host canonico evita
    # um 301 para 127.0.0.1:8086, inacessivel de dentro da rede do Compose.
    default_headers = {'Host': MANIFESTO['host_canonico']}
    connection_timeout = 60.0
    network_timeout = 60.0

    @task
    def ler_post(self):
        # Um GET da pagina nao baixa as imagens; o navegador as pediria em seguida.
        with self.client.get(ALVO['pagina'], name=f'{CENARIO} | pagina',
                             allow_redirects=False, catch_response=True) as resposta:
            if resposta.status_code != 200:
                resposta.failure(f'HTTP {resposta.status_code}')
            elif len(resposta.content or b'') < ALVO['pagina_bytes_minimo']:
                resposta.failure(f'pagina incompleta: {len(resposta.content or b"")} bytes')
        for caminho, tamanho in ALVO['imagens'].items():
            with self.client.get(caminho, name=f'{CENARIO} | imagem',
                                 allow_redirects=False, catch_response=True) as resposta:
                if resposta.status_code != 200:
                    resposta.failure(f'HTTP {resposta.status_code}')
                elif len(resposta.content or b'') != tamanho:
                    resposta.failure(f'imagem incompleta: {len(resposta.content or b"")} bytes')
