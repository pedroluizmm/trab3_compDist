#!/usr/bin/env python3
"""Executa a campanha de testes de carga do Trabalho 3 de forma sequencial.

Para cada repeticao x instancias x cenario x usuarios:
  1. restauracao controlada: reinicia os WordPress selecionados, para os demais,
     recria o Nginx com o pool correspondente e confere X-Upstream e o conteudo;
  2. aquecimento (requisicoes nao medidas) e resfriamento;
  3. Locust headless: rampa explicita, --reset-stats ao atingir a carga-alvo,
     medicao por --duracao segundos;
  4. coleta: CSVs do Locust, docker stats, requisicoes por instancia (logs do
     Apache), estado dos conteineres (OOM/reinicios) e alertas de CPU do Locust.

Os resultados ficam em resultados/<maquina>/<campanha>/; uma campanha existente
nunca e sobrescrita (use --retomar para completar execucoes faltantes).
"""
import argparse
import csv
import datetime
import hashlib
import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROJETO = 'trabalho3-experimento'
CENARIOS = ['imagem-1mb', 'texto-400kb', 'imagem-300kb']
NIVEIS = ['baixa', 'media', 'alta']
log = logging.getLogger('experimento')


def agora():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(momento):
    return momento.isoformat(timespec='seconds')


def ler_env():
    valores = {}
    for linha in (RAIZ / '.env').read_text(encoding='utf-8').splitlines():
        if '=' in linha and not linha.lstrip().startswith('#'):
            chave, valor = linha.split('=', 1)
            valores[chave.strip()] = valor.strip()
    return valores


def compose(*args, instancias=3, timeout=600, checar=True):
    env = dict(os.environ, WP_INSTANCIAS=str(instancias))
    proc = subprocess.run(['docker', 'compose', *args], cwd=RAIZ, env=env, capture_output=True,
                          text=True, timeout=timeout, check=False)
    if checar and proc.returncode != 0:
        raise RuntimeError(f'docker compose {" ".join(args)} falhou: {proc.stderr.strip()[-800:]}')
    return proc


def docker(*args, timeout=120):
    return subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout, check=False)


class SemRedirecionamento(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


ABRIDOR = urllib.request.build_opener(SemRedirecionamento)


def obter(url):
    try:
        with ABRIDOR.open(url, timeout=30) as resposta:
            return resposta.status, resposta.headers, resposta.read()
    except urllib.error.HTTPError as erro:
        return erro.code, erro.headers, b''
    except (urllib.error.URLError, ConnectionError, TimeoutError) as erro:
        return 0, {}, str(erro).encode()


# ---------------------------------------------------------------- restauracao

def configurar_instancias(n, site, manifesto):
    """Deixa exatamente n WordPress ativos, recem-reiniciados, atras do Nginx."""
    ativos = [f'wordpress{i}' for i in range(1, n + 1)]
    inativos = [f'wordpress{i}' for i in range(n + 1, 4)]
    if inativos:
        compose('stop', *inativos, instancias=n)
    compose('up', '-d', '--wait', *ativos, instancias=n)
    compose('restart', *ativos, instancias=n)
    compose('up', '-d', '--wait', *ativos, instancias=n)
    # Recriar o Nginx resolve novamente os IPs e aplica config/instancias/<n>.conf.
    compose('up', '-d', '--no-deps', '--force-recreate', 'nginx', instancias=n)
    for _ in range(60):
        if obter(site + '/saude-proxy')[0] == 200:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Nginx nao respondeu apos recriacao')
    upstreams = set()
    pagina = next(iter(manifesto['cenarios'].values()))['pagina']
    for _ in range(4 * n):
        status, cabecalhos, _ = obter(site + pagina)
        if status != 200:
            raise RuntimeError(f'Verificacao pos-restauracao: HTTP {status}')
        upstreams.add(cabecalhos.get('X-Upstream'))
    if len(upstreams) != n:
        raise RuntimeError(f'Esperados {n} upstreams, observados {sorted(upstreams)}')
    parados = [c for c in inativos if estado_conteiner(c).get('Running')]
    if parados:
        raise RuntimeError(f'Instancias nao selecionadas ainda ativas: {parados}')
    return sorted(upstreams)


def verificar_conteudo(site, manifesto):
    """Confere status e tamanho de paginas e imagens; devolve lista de problemas."""
    problemas = []
    for nome, cen in manifesto['cenarios'].items():
        status, _, corpo = obter(site + cen['pagina'])
        if status != 200 or len(corpo) < cen['pagina_bytes_minimo']:
            problemas.append(f'{nome}: pagina HTTP {status}, {len(corpo)} bytes')
        for caminho, tamanho in cen['imagens'].items():
            status, _, dados = obter(site + caminho)
            if status != 200 or len(dados) != tamanho:
                problemas.append(f'{nome}: {caminho} HTTP {status}, {len(dados)} bytes')
    return problemas


def aquecer(site, cenario, n):
    for _ in range(3 * n):
        obter(site + cenario['pagina'])
        for caminho in cenario['imagens']:
            obter(site + caminho)


def estado_conteiner(servico):
    proc = docker('inspect', f'{PROJETO}-{servico}-1', '--format', '{{json .State}}|{{.RestartCount}}')
    if proc.returncode != 0:
        return {}
    estado, reinicios = proc.stdout.strip().rsplit('|', 1)
    dados = json.loads(estado)
    return {'Running': dados.get('Running'), 'OOMKilled': dados.get('OOMKilled'),
            'ExitCode': dados.get('ExitCode'), 'RestartCount': int(reinicios),
            'Health': (dados.get('Health') or {}).get('Status')}


# ---------------------------------------------------------------- coleta

class Amostrador(threading.Thread):
    """Amostra docker stats e a CPU total da VM (/proc/stat) durante a execucao."""

    def __init__(self, destino, intervalo=5):
        super().__init__(daemon=True)
        self.destino = destino
        self.intervalo = intervalo
        self.parar = threading.Event()

    @staticmethod
    def cpu_total():
        campos = [int(v) for v in Path('/proc/stat').read_text().split('\n', 1)[0].split()[1:]]
        return sum(campos), campos[3] + campos[4]

    def run(self):
        with self.destino.open('w', newline='', encoding='utf-8') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(['t_utc', 'conteiner', 'cpu_pct', 'mem_mib'])
            anterior = self.cpu_total()
            while not self.parar.is_set():
                proc = docker('stats', '--no-stream', '--format', '{{json .}}', timeout=30)
                momento = iso(agora())
                outros = 0.0
                for linha in proc.stdout.splitlines():
                    dados = json.loads(linha)
                    cpu = float(dados['CPUPerc'].rstrip('%') or 0)
                    if not dados['Name'].startswith(PROJETO):
                        outros += cpu
                        continue
                    escritor.writerow([momento, dados['Name'][len(PROJETO) + 1:], cpu,
                                       round(converter_mib(dados['MemUsage'].split('/')[0]), 1)])
                escritor.writerow([momento, 'outros-projetos', round(outros, 2), ''])
                atual = self.cpu_total()
                total, ocioso = atual[0] - anterior[0], atual[1] - anterior[1]
                anterior = atual
                if total:
                    escritor.writerow([momento, 'vm-total', round(100 * (total - ocioso) / total, 2), ''])
                arquivo.flush()
                self.parar.wait(self.intervalo)


def converter_mib(texto):
    texto = texto.strip()
    unidades = {'KiB': 1 / 1024, 'MiB': 1, 'GiB': 1024, 'kB': 1 / 1048.576, 'MB': 1 / 1.048576,
                'GB': 1000 / 1.048576, 'B': 1 / 1048576}
    for sufixo, fator in unidades.items():
        if texto.endswith(sufixo):
            return float(texto[:-len(sufixo)]) * fator
    return 0.0


def requisicoes_por_instancia(inicio, fim):
    contagem = {}
    for i in range(1, 4):
        proc = docker('logs', '--since', iso(inicio), '--until', iso(fim), f'{PROJETO}-wordpress{i}-1')
        contagem[f'wordpress{i}'] = len(re.findall(r'"GET ', proc.stdout + proc.stderr))
    return contagem


def ler_stats(arquivo):
    linhas = {}
    with arquivo.open(newline='', encoding='utf-8') as entrada:
        for linha in csv.DictReader(entrada):
            linhas[linha['Name']] = linha
    return linhas


def resumo_cpu(arquivo):
    series = {}
    with arquivo.open(newline='', encoding='utf-8') as entrada:
        for linha in csv.DictReader(entrada):
            series.setdefault(linha['conteiner'], []).append(float(linha['cpu_pct']))
    return {nome: {'media': round(sum(v) / len(v), 1), 'max': round(max(v), 1)} for nome, v in series.items()}


CAMPOS_RESUMO = [
    'maquina', 'campanha', 'execucao', 'repeticao', 'instancias', 'cenario', 'nivel', 'usuarios',
    'rampa_s', 'duracao_s', 'inicio_utc', 'fim_utc', 'status', 'requisicoes', 'falhas', 'falhas_pct',
    'tempo_medio_ms', 'mediana_ms', 'p95_ms', 'p99_ms', 'max_ms', 'rps',
    'pagina_tempo_medio_ms', 'pagina_p95_ms', 'pagina_rps', 'imagem_tempo_medio_ms', 'imagem_p95_ms',
    'imagem_rps', 'locust_cpu_medio_pct', 'locust_cpu_max_pct', 'locust_alerta_cpu',
    'wordpress_cpu_medio_pct', 'vm_cpu_medio_pct', 'outros_projetos_cpu_medio_pct',
    'req_wordpress1', 'req_wordpress2', 'req_wordpress3', 'incidentes',
]


def executar(args, site, manifesto, pasta, rep, inst, cenario, nivel, usuarios):
    nome = f'r{rep}_i{inst}_{cenario}_u{usuarios}'
    destino = pasta / 'execucoes' / nome
    meta_arquivo = destino / 'meta.json'
    if meta_arquivo.exists() and json.loads(meta_arquivo.read_text())['status'] in ('ok', 'com_falhas'):
        log.info('%s ja concluida; mantida', nome)
        return json.loads(meta_arquivo.read_text())['resumo']
    if destino.exists():
        # Tentativa anterior interrompida: preservada com outro nome.
        destino.rename(destino.with_name(nome + '.incompleta-' + agora().strftime('%H%M%S')))
    destino.mkdir(parents=True)

    log.info('== %s: restauracao controlada', nome)
    upstreams = configurar_instancias(inst, site, manifesto)
    problemas = verificar_conteudo(site, manifesto)
    if problemas:
        raise RuntimeError('Conteudo divergente antes da execucao: ' + '; '.join(problemas))
    aquecer(site, manifesto['cenarios'][cenario], inst)
    time.sleep(args.resfriamento)

    taxa = max(usuarios / args.rampa, 0.1)
    rel = destino.relative_to(RAIZ / 'resultados').as_posix()
    comando = ['--profile', 'carga', 'run', '--rm', '--no-deps', '-T', '--name', f'{PROJETO}-locust-{nome}',
               '-e', f'CENARIO={cenario}', '-e', f'ESPERA_MIN={args.espera_min}',
               '-e', f'ESPERA_MAX={args.espera_max}', 'locust',
               '-f', '/mnt/locust/locustfile.py', '--headless', '-u', str(usuarios), '-r', f'{taxa:.3f}',
               '-t', f'{args.rampa + args.duracao}s', '--reset-stats', '--only-summary',
               '--csv', f'/mnt/resultados/{rel}/locust', '--csv-full-history',
               '--logfile', f'/mnt/resultados/{rel}/locust.log']
    log.info('%s: Locust %d usuarios, rampa %ds (%.3f/s), medicao %ds, %d instancia(s) %s',
             nome, usuarios, args.rampa, taxa, args.duracao, inst, upstreams)
    amostrador = Amostrador(destino / 'docker_stats.csv')
    inicio = agora()
    amostrador.start()
    proc = compose(*comando, instancias=inst, timeout=args.rampa + args.duracao + 300, checar=False)
    fim = agora()
    amostrador.parar.set()
    amostrador.join()
    (destino / 'locust_saida.txt').write_text(proc.stdout + proc.stderr, encoding='utf-8')

    incidentes = []
    estados = {f'wordpress{i}': estado_conteiner(f'wordpress{i}') for i in range(1, inst + 1)}
    estados['nginx'] = estado_conteiner('nginx')
    estados['database'] = estado_conteiner('database')
    for servico, estado in estados.items():
        if not estado.get('Running') or estado.get('OOMKilled'):
            incidentes.append(f'{servico}: {estado}')
    if proc.returncode not in (0, 1):
        incidentes.append(f'locust saiu com codigo {proc.returncode}')
    log_locust = (destino / 'locust.log').read_text(encoding='utf-8', errors='replace') \
        if (destino / 'locust.log').exists() else ''
    alerta_cpu = 'CPU usage above' in log_locust or 'CPU usage was too high' in log_locust
    stats_arquivo = destino / 'locust_stats.csv'
    if not stats_arquivo.exists():
        incidentes.append('locust_stats.csv ausente')
        meta = {'status': 'erro', 'incidentes': incidentes, 'resumo': None}
        meta_arquivo.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + '\n')
        raise RuntimeError(f'{nome}: sem estatisticas do Locust; ver {destino}/locust_saida.txt')

    stats = ler_stats(stats_arquivo)
    total = stats['Aggregated']
    pagina = stats.get(f'{cenario} | pagina', {})
    imagem = stats.get(f'{cenario} | imagem', {})
    cpu = resumo_cpu(destino / 'docker_stats.csv')
    contagem = requisicoes_por_instancia(inicio, fim)
    vazou = [s for s, c in contagem.items() if int(s[-1]) > inst and c > 0]
    if vazou:
        incidentes.append(f'requisicoes em instancias nao selecionadas: {vazou}')
    reqs, falhas = int(total['Request Count']), int(total['Failure Count'])
    wp_cpu = [cpu[s]['media'] for s in cpu if s.startswith('wordpress')]
    resumo = {
        'maquina': args.maquina, 'campanha': pasta.name, 'execucao': nome, 'repeticao': rep,
        'instancias': inst, 'cenario': cenario, 'nivel': nivel, 'usuarios': usuarios,
        'rampa_s': args.rampa, 'duracao_s': args.duracao, 'inicio_utc': iso(inicio), 'fim_utc': iso(fim),
        'status': 'erro' if not reqs else ('com_falhas' if falhas else 'ok'),
        'requisicoes': reqs, 'falhas': falhas, 'falhas_pct': round(100 * falhas / reqs, 3) if reqs else '',
        'tempo_medio_ms': round(float(total['Average Response Time']), 2),
        'mediana_ms': total['Median Response Time'], 'p95_ms': total['95%'], 'p99_ms': total['99%'],
        'max_ms': round(float(total['Max Response Time']), 1), 'rps': round(float(total['Requests/s']), 3),
        'pagina_tempo_medio_ms': round(float(pagina.get('Average Response Time') or 0), 2),
        'pagina_p95_ms': pagina.get('95%', ''), 'pagina_rps': round(float(pagina.get('Requests/s') or 0), 3),
        'imagem_tempo_medio_ms': round(float(imagem['Average Response Time']), 2) if imagem else '',
        'imagem_p95_ms': imagem.get('95%', ''),
        'imagem_rps': round(float(imagem['Requests/s']), 3) if imagem else '',
        'locust_cpu_medio_pct': cpu.get(f'locust-{nome}', {}).get('media', ''),
        'locust_cpu_max_pct': cpu.get(f'locust-{nome}', {}).get('max', ''),
        'locust_alerta_cpu': alerta_cpu,
        'wordpress_cpu_medio_pct': round(sum(wp_cpu), 1) if wp_cpu else '',
        'vm_cpu_medio_pct': cpu.get('vm-total', {}).get('media', ''),
        'outros_projetos_cpu_medio_pct': cpu.get('outros-projetos', {}).get('media', ''),
        'req_wordpress1': contagem['wordpress1'], 'req_wordpress2': contagem['wordpress2'],
        'req_wordpress3': contagem['wordpress3'], 'incidentes': ' | '.join(incidentes),
    }
    meta = {'status': resumo['status'], 'parametros': {'usuarios': usuarios, 'taxa_spawn_por_s': taxa,
            'rampa_s': args.rampa, 'duracao_s': args.duracao, 'espera_s': [args.espera_min, args.espera_max],
            'instancias': inst, 'cenario': cenario, 'nivel': nivel, 'repeticao': rep},
            'upstreams': upstreams, 'locust_codigo_saida': proc.returncode, 'estados_conteineres': estados,
            'cpu_docker_stats': cpu, 'incidentes': incidentes, 'resumo': resumo}
    meta_arquivo.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    log.info('%s: %s req, %s falhas (%s%%), media %s ms, p95 %s ms, %s req/s; locust CPU med %s%% max %s%%%s',
             nome, reqs, falhas, resumo['falhas_pct'], resumo['tempo_medio_ms'], resumo['p95_ms'],
             resumo['rps'], resumo['locust_cpu_medio_pct'], resumo['locust_cpu_max_pct'],
             '; INCIDENTES: ' + resumo['incidentes'] if incidentes else '')
    return resumo


# ---------------------------------------------------------------- maquina

def registrar_maquina(destino, args):
    def ler(comando):
        proc = subprocess.run(comando, capture_output=True, text=True, check=False)
        return proc.stdout.strip()

    lscpu = dict(linha.split(':', 1) for linha in ler(['lscpu']).splitlines() if ':' in linha)
    meminfo = dict(linha.split(':', 1) for linha in Path('/proc/meminfo').read_text().splitlines())
    info = json.loads(ler(['docker', 'info', '--format', '{{json .}}']) or '{}')
    imagens = {}
    for imagem in ['mysql:5.7', 'wordpress:5.4.2-php7.2-apache', 'nginx:1.19.0', 'locustio/locust:2.46.7']:
        imagens[imagem] = ler(['docker', 'image', 'inspect', imagem, '--format', '{{.Id}}'])
    env = ler_env()
    dados = {
        'maquina': args.maquina, 'registrado_utc': iso(agora()),
        'cpu_modelo': lscpu.get('Model name', '').strip(), 'cpus_logicas': int(lscpu.get('CPU(s)', 0)),
        'threads_por_nucleo': lscpu.get('Thread(s) per core', '').strip(),
        'memoria_vm_gib': round(int(meminfo['MemTotal'].split()[0]) / 1048576, 2),
        'sistema': platform.platform(), 'kernel': platform.release(),
        'wsl': 'microsoft' in platform.release().lower(),
        'docker_servidor': info.get('ServerVersion'), 'docker_os': info.get('OperatingSystem'),
        'docker_ncpu': info.get('NCPU'), 'docker_memoria_gib': round((info.get('MemTotal') or 0) / 2**30, 2),
        'compose': ler(['docker', 'compose', 'version', '--short']),
        'limites': {'WP_CPUS': env.get('WP_CPUS', '1.0'), 'WP_MEMORIA': env.get('WP_MEMORIA', '1536m'),
                    'WP_MAX_WORKERS': env.get('WP_MAX_WORKERS', '25'), 'LOCUST_CPUS': env.get('LOCUST_CPUS', '4.0'),
                    'mysql_max_connections': 100},
        'imagens': imagens,
        'outros_conteineres_ativos': len([n for n in ler(['docker', 'ps', '--format', '{{.Names}}']).splitlines()
                                          if not n.startswith(PROJETO)]),
        'observacao': 'Gerador (Locust) e aplicacao compartilham a mesma maquina/VM.',
    }
    destino.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return dados


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--maquina', required=True, help='rotulo da maquina, ex.: maquina-a')
    parser.add_argument('--campanha', help='nome da campanha (padrao: data/hora UTC)')
    parser.add_argument('--usuarios', type=int, nargs='+', required=True,
                        help='niveis de usuarios em ordem crescente (3 valores = baixa/media/alta)')
    parser.add_argument('--instancias', type=int, nargs='+', default=[1, 2, 3], choices=[1, 2, 3])
    parser.add_argument('--cenarios', nargs='+', default=CENARIOS, choices=CENARIOS)
    parser.add_argument('--repeticoes', type=int, default=3)
    parser.add_argument('--rampa', type=int, default=30, help='segundos para atingir a carga-alvo')
    parser.add_argument('--duracao', type=int, default=60, help='segundos medidos apos a rampa')
    parser.add_argument('--resfriamento', type=int, default=10, help='pausa antes de cada execucao (s)')
    parser.add_argument('--espera-min', type=float, default=5, help='pausa minima do usuario (s)')
    parser.add_argument('--espera-max', type=float, default=9, help='pausa maxima do usuario (s)')
    parser.add_argument('--retomar', action='store_true', help='completa uma campanha existente')
    parser.add_argument('--simular', action='store_true', help='mostra o plano sem executar')
    args = parser.parse_args()

    if sorted(args.usuarios) != args.usuarios:
        parser.error('--usuarios deve estar em ordem crescente')
    niveis = NIVEIS if len(args.usuarios) == 3 else [f'n{i + 1}' for i in range(len(args.usuarios))]
    # Agrupa todas as combinacoes de um nivel antes de passar ao proximo:
    # baixa -> media -> alta. Mantem 1, 2, 3 instancias e todos os cenarios.
    plano = [(rep, inst, cen, nivel, u)
             for nivel, u in zip(niveis, args.usuarios)
             for rep in range(1, args.repeticoes + 1)
             for inst in args.instancias
             for cen in args.cenarios]
    por_execucao = args.rampa + args.duracao + args.resfriamento + 40
    print(f'{len(plano)} execucoes; estimativa {len(plano) * por_execucao / 3600:.1f} h')
    if args.simular:
        for item in plano:
            print('  r{}  {} inst  {:<13} {:<5} {} usuarios'.format(*item))
        return

    campanha = args.campanha or agora().strftime('%Y%m%dT%H%M%SZ')
    pasta = RAIZ / 'resultados' / args.maquina / campanha
    if pasta.exists() and not args.retomar:
        sys.exit(f'{pasta} ja existe; resultados anteriores sao preservados (use --retomar ou outro nome)')
    pasta.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.FileHandler(pasta / 'campanha.log', encoding='utf-8'),
                                  logging.StreamHandler(sys.stdout)])

    site = ler_env().get('SITE_URL', 'http://127.0.0.1:8086').rstrip('/')
    manifesto_texto = (RAIZ / 'locust/cenarios.json').read_text(encoding='utf-8')
    manifesto = json.loads(manifesto_texto)
    registrar_maquina(pasta / 'maquina.json', args)
    (pasta / 'plano.json').write_text(json.dumps({
        'parametros': {k: v for k, v in vars(args).items() if k not in ('simular', 'retomar')},
        'niveis': dict(zip(niveis, args.usuarios)), 'ordem': [list(p) for p in plano],
        'manifesto_cenarios_sha256': hashlib.sha256(manifesto_texto.encode()).hexdigest(),
        'manifesto_cenarios': manifesto}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    problemas = verificar_conteudo(site, manifesto)
    if problemas:
        sys.exit('Conteudo divergente; execute scripts/preparar_cenarios.py: ' + '; '.join(problemas))

    resumo_arquivo = pasta / 'resumo_execucoes.csv'
    concluidas = 0
    try:
        for indice, (rep, inst, cen, nivel, usuarios) in enumerate(plano, 1):
            log.info('[%d/%d]', indice, len(plano))
            resumo = executar(args, site, manifesto, pasta, rep, inst, cen, nivel, usuarios)
            concluidas += 1
            existentes = set()
            if resumo_arquivo.exists():
                with resumo_arquivo.open(newline='', encoding='utf-8') as entrada:
                    existentes = {linha['execucao'] for linha in csv.DictReader(entrada)}
            if resumo['execucao'] not in existentes:
                novo = not resumo_arquivo.exists()
                with resumo_arquivo.open('a', newline='', encoding='utf-8') as saida:
                    escritor = csv.DictWriter(saida, fieldnames=CAMPOS_RESUMO)
                    if novo:
                        escritor.writeheader()
                    escritor.writerow(resumo)
    finally:
        log.info('Restaurando o estado padrao (3 instancias)')
        try:
            configurar_instancias(3, site, manifesto)
            problemas = verificar_conteudo(site, manifesto)
            log.info('Verificacao final do conteudo: %s', 'aprovada' if not problemas else problemas)
        except Exception as erro:  # o estado final e registrado mesmo apos falhas
            log.error('Falha ao restaurar estado padrao: %s', erro)
        log.info('%d/%d execucoes concluidas nesta chamada; resultados em %s', concluidas, len(plano), pasta)


if __name__ == '__main__':
    main()
