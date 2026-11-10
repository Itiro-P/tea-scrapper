"""Apply only new files after checks; supports a project inside a monorepo."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


UPGRADE_FROM={
    'batch_tools/batch_core.py':{'4a754aa2cc1d5bc33fde9ada55325b82d34f1257ce1752190830a736fe05a237'},
    'batch_tools/test_batch.py':{'42fa4050dc5ff57d6921dad1a972f00beac3d2625c48cfbdc5ccd04cfa40d7b8'},
    'batch_tools/tea_batch.py':{'ce8145f8108fc31c62768de0d4a27d94dbb943675e6e352c840f76177ce29eb5'},
    'docs/AUTOMACAO-3141.md':{'0e5af788c6d31033984972b3e767ad249180bbb3e1f5a16e5edbd93c8dc8d90c'},
}


def atomic_copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as stream:
            temporary=Path(stream.name)
            with source.open('rb') as original:shutil.copyfileobj(original,stream)
            stream.flush()
        shutil.copystat(source,temporary)
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()


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
    existing=[];upgrade=[]
    for name,expected in files.items():
        target=(project/name).resolve()
        if not target.is_relative_to(project):raise ValueError('Destino inválido ou link para fora do projeto: '+name)
        if target.exists():
            if not target.is_file():raise ValueError('Arquivo existente não é arquivo regular: '+name)
            current=digest(target)
            if current==expected:existing.append(name)
            elif current in UPGRADE_FROM.get(name,set()):upgrade.append(name)
            else:raise ValueError('Arquivo existente diferente: '+name+'. Nada foi aplicado; não force.')
    if len(existing)==len(files):
        print('Automação já aplicada com conteúdo idêntico. Nenhum arquivo foi alterado.');return
    if existing or upgrade:
        if len(existing)+len(upgrade)!=len(files):
            raise ValueError('Aplicação parcial encontrada. Nada foi alterado; preserve os arquivos e compare com codigo/.')
        for name in upgrade:atomic_copy(package/'codigo'/name,project/name)
    else:
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
