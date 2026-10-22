#!/usr/bin/env python3
"""Verificacao local sem iniciar, parar ou remover containers; nao gera imagens."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--diretorio', type=Path, default=Path(__file__).resolve().parent.parent)
parser.add_argument('--estatico', action='store_true', help='Valida Compose sem acessar o daemon')
args = parser.parse_args()
root = args.diretorio.resolve()
out = root / 'documentacao/evidencias'
out.mkdir(parents=True, exist_ok=True)
compose = ['docker-compose', '--project-directory', str(root), '-f', str(root/'docker-compose.yml')]
report = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'modo': 'estatico' if args.estatico else 'runtime', 'checagens': [], 'status': 'PENDENTE'}

def registrar(nome, comando):
    result = subprocess.run(comando, capture_output=True, text=True, timeout=45)
    safe_command = [v.replace(str(root), '<PASTA_DO_PROJETO>') for v in comando]
    output = (result.stdout + result.stderr).replace(str(root), '<PASTA_DO_PROJETO>')
    report['checagens'].append({'nome': nome, 'comando': safe_command,
                               'exit_code': result.returncode, 'saida': output})
    if result.returncode:
        raise RuntimeError(nome + ': comando nao concluiu; confira a saida registrada')
    return result.stdout

try:
    config_run = subprocess.run(compose+['config', '--format', 'json'],
                                capture_output=True, text=True, timeout=30)
    if config_run.returncode:
        raise RuntimeError('Compose invalido; execute o preparador e confira a configuracao local')
    config = json.loads(config_run.stdout)
    services = config['services']
    assert set(services) == {'database', 'wordpress1', 'wordpress2', 'wordpress3', 'nginx'}
    assert services['database']['image'] == 'mysql:5.7'
    assert services['nginx']['image'] == 'nginx:1.19.0'
    assert all(services[n]['image'] == 'wordpress:5.4.2-php7.2-apache'
               for n in ['wordpress1', 'wordpress2', 'wordpress3'])
    assert all(not c.get('privileged') for c in services.values())
    for name, service in services.items():
        if name != 'nginx':
            assert not service.get('ports'), 'Porta publicada fora do proxy'
    bindings = services['nginx']['ports']
    assert len(bindings) == 1 and bindings[0]['host_ip'] == '127.0.0.1'
    report['estrutura'] = {'servicos': 5, 'imagens_corretas': True,
                           'apenas_nginx_publicado_em_loopback': True, 'privileged': False}
    if not args.estatico:
        registrar('servidor_docker', ['docker', 'info', '--format', '{{.Name}}'])
        registrar('containers', compose+['ps', '-a'])
        raw_ids = registrar('identificadores', compose+['ps', '-q']).split()
        assert len(raw_ids) == 5, 'Esperados cinco containers ativos'
        inspected = json.loads(subprocess.check_output(['docker', 'inspect', *raw_ids], text=True))
        safe = []
        expected = set()
        for container in inspected:
            service = container['Config']['Labels']['com.docker.compose.service']
            assert container['Config']['Image'] == services[service]['image'], 'Imagem diferente da especificada'
            state = container['State']
            assert state['Running'], service + ' parado'
            if service != 'nginx':
                assert state.get('Health', {}).get('Status') == 'healthy', service + ' sem saude'
            assert not container['HostConfig']['Privileged']
            if service != 'nginx':
                assert not container['HostConfig']['PortBindings']
            else:
                assert container['HostConfig']['PortBindings'] == {
                    '80/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(bindings[0]['published'])}]}
            networks = {n: value['IPAddress'] for n, value in container['NetworkSettings']['Networks'].items()}
            if service.startswith('wordpress'):
                expected.update(ip+':80' for n, ip in networks.items() if n.endswith('_requisicoes'))
            safe.append({'servico': service, 'estado': state['Status'],
                         'saude': state.get('Health', {}).get('Status'), 'redes': networks,
                         'portas': container['HostConfig']['PortBindings'], 'privileged': False})
        report['containers'] = safe
        assert {c['servico'] for c in safe} == set(services)
        registrar('nginx_config', compose+['exec', '-T', 'nginx', 'nginx', '-t'])
        registrar('php_config', compose+['exec', '-T', 'wordpress1', 'php', '-l', '/var/www/html/wp-config.php'])
        registrar('banco', compose+['exec', '-T', 'database', 'sh', '-c',
            'MYSQL_PWD="$(cat /run/secrets/senha_aplicacao)" mysql -uaplicacao -D experimento -e "SELECT DATABASE(); SHOW TABLES;"'])
        url = services['wordpress1']['environment']['SITE_URL'].rstrip('/') + '/'
        parsed = urllib.parse.urlsplit(url)
        assert parsed.scheme == 'http' and parsed.hostname in ['127.0.0.1', 'localhost']
        responses = []
        for i in range(9):
            with urllib.request.urlopen(url, timeout=15) as response:
                assert response.status == 200 and response.url.rstrip('/') == url.rstrip('/'), 'Site nao instalado ou URL diferente'
                body = response.read()
                responses.append({'numero': i+1, 'status': response.status,
                    'upstream': response.headers.get('X-Upstream'), 'bytes': len(body),
                    'sha256_html': hashlib.sha256(body).hexdigest()})
        report['http'] = responses
        assert len(expected) == 3 and {r['upstream'] for r in responses} == expected
        assert len({r['sha256_html'] for r in responses}) == 1, 'HTML diferente entre destinos'
        report['status'] = 'APROVADO_RUNTIME'
    else:
        report['status'] = 'APROVADO_ESTATICO_RUNTIME_NAO_TESTADO'
except Exception as error:
    report['status'] = 'BLOQUEADO_OU_REPROVADO'
    report['erro'] = str(error).replace(str(root), '<PASTA_DO_PROJETO>')
finally:
    file = out / ('checagem-estatica.json' if args.estatico else 'checagem-runtime.json')
    file.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(report['status'])
    if 'erro' in report:
        print(report['erro'])
    print('Registro salvo em documentacao/evidencias/' + file.name)
    print('Este registro e texto/JSON; nao e um print de terminal ou da aplicacao.')
sys.exit(0 if report['status'].startswith('APROVADO') else 2)
