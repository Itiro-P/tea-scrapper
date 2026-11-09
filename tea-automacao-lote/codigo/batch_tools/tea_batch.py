#!/usr/bin/env python3
"""Batch automation for all collected apps. Python standard library only."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from batch_core import Client, PRINT_LOCK, export, plan, prepare, review_copy, run, status


def settings(parser):
    parser.add_argument('--num-ctx',type=int,default=8192)
    parser.add_argument('--num-predict',type=int,default=1024)
    parser.add_argument('--chunk-bytes',type=int,default=2500)
    parser.add_argument('--segment-chars',type=int,default=420)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--format',choices=['json','schema'],default='json')
    parser.add_argument('--thinking',choices=['auto','off','on'],default='auto')
    parser.add_argument('--keep-alive',default='10m')
    parser.add_argument('--num-thread',type=int)


def config(args):
    keys=['num_ctx','num_predict','chunk_bytes','segment_chars','seed','format','thinking','keep_alive','num_thread']
    result={k:getattr(args,k) for k in keys}
    if result['num_thread'] is not None and result['num_thread']<1:raise ValueError('num-thread deve ser positivo.')
    return result


def progress(event):
    with PRINT_LOCK:
        if event['event']=='waiting':
            print(f"aguardando | {event['appId']} | parte {event['part']} | {event['elapsed_seconds']:.0f}s | {event['content_chars']} caracteres",file=sys.stderr,flush=True)
        else:print(json.dumps(event,ensure_ascii=False),file=sys.stderr,flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare',help='Freeze all unique apps from local JSONs; no network.')
    p.add_argument('--results',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--expect-apps',type=int)
    p=sub.add_parser('plan',help='Calculate chunks without calling any model.')
    p.add_argument('--out',type=Path,required=True);settings(p)
    p=sub.add_parser('doctor',help='Inspect configured Ollama and installed model; no generation.')
    p.add_argument('--model',required=True);p.add_argument('--base-url',default='http://127.0.0.1:11434')
    p=sub.add_parser('run',help='Extract and checkpoint; rerun to resume unfinished work.')
    p.add_argument('--out',type=Path,required=True);p.add_argument('--model',required=True)
    p.add_argument('--base-url',default='http://127.0.0.1:11434');p.add_argument('--timeout',type=int,default=720)
    p.add_argument('--workers',type=int,default=1);p.add_argument('--max-attempts',type=int,default=2)
    p.add_argument('--limit',type=int);p.add_argument('--app-id',action='append',default=[])
    p.add_argument('--retry-errors',action='store_true');p.add_argument('--stop-after-errors',type=int,default=3)
    p.add_argument('--export-every',type=int,default=25);settings(p)
    for command in ['status','export']:
        p=sub.add_parser(command,help='Read checkpoint and export current counts; no generation.')
        p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('review',help='Create a separate, never overwritten copy for human review.')
    p.add_argument('--out',type=Path,required=True);p.add_argument('--review-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            manifest=prepare(args.results,args.out,args.expect_apps)
            result={key:value for key,value in manifest.items() if key!='input_files'}
            result['input_files_count']=len(manifest['input_files'])
        elif args.command=='plan':result=plan(args.out,config(args))
        elif args.command=='doctor':result=Client(args.base_url).identity(args.model)
        elif args.command=='review':result=review_copy(args.out,args.review_dir)
        elif args.command=='status':result=status(args.out)
        elif args.command=='run':
            if args.limit is not None and args.limit<1:raise ValueError('limit deve ser positivo.')
            result=run(args.out,args.model,config(args),args.base_url,args.timeout,args.workers,args.max_attempts,
                args.limit,args.app_id,args.retry_errors,args.stop_after_errors,args.export_every,progress)
        else:
            from batch_core import exclusive
            with exclusive(args.out):result=export(args.out)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        if args.command=='run':
            if result['stop_reason']=='interrupted':return 130
            if result['errors_this_run'] or result['stop_reason']:return 2
            if result['states'].get('error') or result['states'].get('partial_error') or result['states'].get('input_error'):return 2
        return 0
    except (ValueError,OSError,RuntimeError,KeyError,sqlite3.Error) as exc:
        print('Erro: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
