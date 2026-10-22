#!/usr/bin/env python3
"""Cria (se preciso) e verifica os tres posts dos cenarios de carga.

Executa scripts/cenarios/criar-cenarios.php dentro de wordpress1, confere cada
pagina e imagem por HTTP atraves do Nginx e grava locust/cenarios.json, usado
pelo Locust. Reexecutar e seguro: posts existentes sao apenas verificados.
"""
import datetime
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOLERANCIA = 0.02


def ler_env():
    valores = {}
    for linha in (RAIZ / '.env').read_text(encoding='utf-8').splitlines():
        if '=' in linha and not linha.lstrip().startswith('#'):
            chave, valor = linha.split('=', 1)
            valores[chave.strip()] = valor.strip()
    return valores


class SemRedirecionamento(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def obter(url):
    """GET sem seguir redirecionamentos; devolve (status, corpo)."""
    abridor = urllib.request.build_opener(SemRedirecionamento)
    try:
        with abridor.open(url, timeout=30) as resposta:
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:
        return erro.code, b''


def main():
    site = ler_env().get('SITE_URL', 'http://127.0.0.1:8086').rstrip('/')
    php = (RAIZ / 'scripts/cenarios/criar-cenarios.php').read_bytes()
    execucao = subprocess.run(['docker', 'compose', 'exec', '-T', 'wordpress1', 'php'],
                              input=php, capture_output=True, cwd=RAIZ, check=False)
    if execucao.returncode != 0:
        sys.exit('Falha ao criar cenarios:\n' + execucao.stderr.decode(errors='replace')
                 + execucao.stdout.decode(errors='replace')[-2000:])
    cenarios = json.loads(execucao.stdout)

    problemas = []
    for cen in cenarios:
        status, corpo = obter(site + cen['caminho'])
        cen['http_pagina'] = {'status': status, 'bytes': len(corpo)}
        if status != 200:
            problemas.append(f"{cen['cenario']}: pagina HTTP {status}")
        if abs(cen['desvio_alvo']) > TOLERANCIA:
            problemas.append(f"{cen['cenario']}: desvio {cen['desvio_alvo']:+.2%} do alvo")
        html = corpo.decode('utf-8', errors='replace')
        for img in cen['imagens']:
            if not re.search(r'<img[^>]+src="[^"]*' + re.escape(img['caminho']) + '"', html):
                problemas.append(f"{cen['cenario']}: pagina nao referencia {img['caminho']}")
            status_img, dados = obter(site + img['caminho'])
            img['http'] = {'status': status_img, 'bytes': len(dados),
                           'sha256_confere': hashlib.sha256(dados).hexdigest() == img['sha256']}
            if status_img != 200 or not img['http']['sha256_confere']:
                problemas.append(f"{cen['cenario']}: imagem HTTP {status_img} ou conteudo divergente")
        if cen['cenario'].startswith('imagem') and not cen['imagens']:
            problemas.append(f"{cen['cenario']}: nenhuma imagem anexada")

    manifesto = {
        'gerado_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'host_canonico': site.split('://', 1)[1],
        'cenarios': {c['cenario']: {'pagina': c['caminho'],
                                    'pagina_bytes_minimo': c['tamanho_conteudo_bytes'],
                                    'imagens': {i['caminho']: i['tamanho_bytes'] for i in c['imagens']}}
                     for c in cenarios},
    }
    (RAIZ / 'locust/cenarios.json').write_text(json.dumps(manifesto, indent=2) + '\n', encoding='utf-8')

    evidencias = RAIZ / 'documentacao/evidencias-trabalho3'
    evidencias.mkdir(parents=True, exist_ok=True)
    registro = {'data_utc': manifesto['gerado_utc'], 'aprovado': not problemas,
                'problemas': problemas, 'cenarios': cenarios}
    (evidencias / 'cenarios-verificacao.json').write_text(
        json.dumps(registro, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    for cen in cenarios:
        medido = cen['imagens'][0]['tamanho_bytes'] if cen['imagens'] else cen['tamanho_conteudo_bytes']
        print(f"{cen['cenario']:>13}  post {cen['post_id']:>3}  {medido:>9,} bytes "
              f"({cen['desvio_alvo']:+.2%})  pagina HTTP {cen['http_pagina']['status']} "
              f"{cen['http_pagina']['bytes']:,} bytes  {'novo' if cen['criado_agora'] else 'existente'}")
    if problemas:
        sys.exit('REPROVADO:\n- ' + '\n- '.join(problemas))
    print('Cenarios verificados; manifesto em locust/cenarios.json')


if __name__ == '__main__':
    main()
