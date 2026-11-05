"""Apply only new files after checks; supports a project inside a monorepo."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(package, project):
    package=Path(package).resolve();project=Path(project).resolve()
    for line in (package/'SHA256SUMS.txt').read_text().splitlines():
        expected,name=line.split('  ',1)
        file=(package/name).resolve()
        if not file.is_relative_to(package) or not file.is_file() or digest(file)!=expected:
            raise ValueError('Pacote incompleto ou alterado: '+name)
    if not (project/'pyproject.toml').is_file() or not (project/'tea_analysis').is_dir():
        raise ValueError('Entre na pasta tea-scrapper que contém pyproject.toml e tea_analysis antes de aplicar.')
    repo=Path(subprocess.check_output(['git','-C',str(project),'rev-parse','--show-toplevel'],text=True).strip()).resolve()
    prefix=project.relative_to(repo).as_posix()
    files=json.loads((package/'arquivos.json').read_text())
    existing=[]
    for name,expected in files.items():
        target=(project/name).resolve()
        if not target.is_relative_to(project):raise ValueError('Destino inválido ou link para fora do projeto: '+name)
        if target.exists():
            if not target.is_file() or digest(target)!=expected:raise ValueError('Arquivo existente diferente: '+name+'. Nada foi aplicado; não force.')
            existing.append(name)
    if len(existing)==len(files):
        print('Automação já aplicada com conteúdo idêntico. Nenhum arquivo foi alterado.');return
    if existing:raise ValueError('Aplicação parcial encontrada. Nada foi alterado; preserve os arquivos e compare com codigo/.')
    command=['git','-C',str(repo),'apply']
    if prefix!='.':command+=['--directory',prefix]
    patch=str(package/'tea-automacao-lote.patch')
    subprocess.run([*command,'--check',patch],check=True)
    subprocess.run([*command,patch],check=True)
    if not all(digest(project/name)==expected for name,expected in files.items()):raise ValueError('Conferência após aplicação falhou; preserve a saída para diagnóstico.')
    print('Automação aplicada e hashes conferidos. Nenhum commit foi feito.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True)
    args=p.parse_args()
    try:apply(args.package,Path.cwd())
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        print('Erro: '+str(exc),file=sys.stderr);raise SystemExit(2)
