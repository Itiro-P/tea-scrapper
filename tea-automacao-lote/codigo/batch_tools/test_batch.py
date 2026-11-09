"""Regression tests; deterministic doubles are NOT measurements of LLM quality."""
import csv
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

import batch_core as b
from ollama_transport import OllamaDeadlineError,OllamaRequestError
from tea_batch import main

CONFIG={'num_ctx':8192,'num_predict':1024,'chunk_bytes':2500,'segment_chars':420,
        'seed':42,'format':'json','thinking':'auto','keep_alive':'10m','num_thread':None}


class Fake:
    def __init__(self):self.calls=[];self.failures=0;self.failure_status=503;self.mode='normal';self.callback=None;self.digest='fixed-sha'
    def identity(self,model):return {'name':model,'digest':self.digest,'ollama_version':'test','capabilities':[]}
    def chat(self,body,on_progress,cancel):
        self.calls.append(body)
        if len(self.calls)==getattr(self,'fail_at',-1):raise OllamaRequestError('fatal fixture',status=400)
        if self.callback:self.callback()
        if self.failures:
            self.failures-=1;raise OllamaRequestError('simulated failure',status=self.failure_status)
        payload=json.loads(body['messages'][1]['content']);features=[]
        for key,text in payload['segments'].items():
            if 'Crie rotinas' in text:features.append({'name':'Criar rotinas','evidence_id':key})
            if 'Receba alertas' in text:features.append({'name':'Receber alertas','evidence_id':key})
        if self.mode=='bad_id':features=[{'name':'Criar rotinas','evidence_id':'inventado'}]
        if self.mode=='placeholder':features=[{'name':'Verbo + objeto','evidence_id':next(iter(payload['segments']))}]
        return {'done':True,'done_reason':'length' if self.mode=='truncated' else 'stop',
                'message':{'content':json.dumps({'features':features})},'eval_count':12}


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.raw=self.root/'raw';self.raw.mkdir();self.out=self.root/'analysis'
        self.put('01.json',{'meta':{'group':'TEA','term':'autismo'},'apps':[
            {'appId':'a.one','title':'Um','description':'Crie rotinas. Receba alertas.'},
            {'appId':'b.two','title':'Dois','description':'Receba alertas.'}]})
        self.put('02.json',{'meta':{'group':'TDAH','term':'atenção'},'apps':[
            {'appId':'a.one','title':'Um','description':'Crie rotinas. Receba alertas.'},
            {'appId':'c.three','title':'Três','description':'Um design bonito para você.'}]})
        self.client=Fake()
    def tearDown(self):self.tmp.cleanup()
    def put(self,name,value):(self.raw/name).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    def ready(self):return b.prepare(self.raw,self.out,3)
    def run_it(self,**kw):return b.run(self.out,'test:1',dict(CONFIG),client=self.client,callback=None,**kw)

    def test_all_groups_deduplicated_and_originals_unchanged(self):
        before={p:p.read_bytes() for p in self.raw.iterdir()};m=self.ready()
        self.assertEqual(m['apps'],3);self.assertEqual(m['groups'],{'TDAH':2,'TEA':2})
        apps,_=b.read_corpus(self.out)
        self.assertEqual(apps[0]['groups'],['TDAH','TEA'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.raw.iterdir()})
    def test_wrong_expected_count_creates_no_output(self):
        with self.assertRaises(ValueError):b.prepare(self.raw,self.out,3141)
        self.assertFalse(self.out.exists())
    def test_idempotent_prepare_and_changed_source_rejected(self):
        m=self.ready();self.assertEqual(self.ready(),m)
        self.put('03.json',{'group':'DI','apps':[{'appId':'d.four','description':'outro'}]})
        with self.assertRaises(ValueError):b.prepare(self.raw,self.out)
        self.assertEqual(b.read_corpus(self.out)[1]['apps'],3)
    def test_tampered_corpus_rejected(self):
        self.ready();(self.out/'corpus.jsonl').write_text('changed')
        with self.assertRaises(ValueError):self.run_it()
        self.assertEqual(len(self.client.calls),0)
    def test_unicode_line_separators_inside_jsonl_strings(self):
        text='Crie rotinas.\u0085Receba alertas.\u2028Texto\u2029final.'
        self.put('03.json',{'group':'DI','apps':[{'appId':'d.four','description':text}]})
        b.prepare(self.raw,self.out,4)
        apps,_=b.read_corpus(self.out)
        self.assertEqual(apps[-1]['description'],text)
        self.assertGreater(b.plan(self.out,CONFIG)['chunks'],0)
    def test_alternative_description_logged_not_silently_combined(self):
        self.put('03.json',{'group':'DI','apps':[{'appId':'a.one','description':'Outro texto.'}]})
        self.ready();apps,m=b.read_corpus(self.out)
        self.assertEqual(m['apps_with_description_variants'],1)
        self.assertEqual(apps[0]['description'],'Crie rotinas. Receba alertas.')
        self.assertEqual(len(apps[0]['variants']),2)
    def test_raw_and_grouped_formats(self):
        other=self.root/'grouped';other.mkdir()
        (other/'tea.json').write_text(json.dumps({'group':'TEA','apps':[{'appId':'x','description':'Crie rotinas.'}]}))
        self.assertEqual(b.prepare(other,self.root/'grouped-out')['apps'],1)
    def test_no_source_directory_output(self):
        with self.assertRaises(ValueError):b.prepare(self.raw,self.raw/'analysis')
    def test_unicode_and_long_unbroken_input_not_truncated(self):
        text='  Áudio🙂.\r\nCrie rotinas! '+'汉字🌱'*2000+' fim.\n'
        parts=b.segments(text,200)
        self.assertEqual(''.join(p['text'] for p in parts).replace(' ',''),text.strip().replace(' ','').replace('\r','').replace('\n',''))
        self.assertTrue(all(text[p['start']:p['end']]==p['text'] for p in parts))
        app={'appId':'long','title':'Longo','description':text}
        chunks=b.make_chunks(app,{**CONFIG,'segment_chars':200})
        self.assertGreater(len(chunks),1)
        self.assertEqual([p['id'] for c in chunks for p in c['parts']],[p['id'] for p in parts])
        for chunk in chunks:self.assertLessEqual(len(chunk['user'].encode('utf-8')),CONFIG['chunk_bytes'])
    def test_malformed_output_evidence_and_placeholders_rejected(self):
        parts=b.segments('Crie rotinas.')
        for response in ['{}','[]','{"features":null}',json.dumps({'features':[{'name':'Verbo + objeto','evidence_id':parts[0]['id']}]}),
                         json.dumps({'features':[{'name':'Criar rotinas','evidence_id':'inventado'}]})]:
            with self.subTest(response=response),self.assertRaises(ValueError):b.resolve(response,parts,'Crie rotinas.')
    def test_rejects_generic_features_that_are_not_condition_specific(self):
        parts=b.segments('Crie rotinas. Ativar modo escuro. Usar o aplicativo offline. Acompanhar progresso.')
        with self.assertRaises(ValueError):
            b.resolve(json.dumps({'features':[{'name':'Ativar modo escuro','evidence_id':parts[1]['id']},{'name':'Acompanhar progresso','evidence_id':parts[2]['id']}]}),parts,'Crie rotinas. Ativar modo escuro. Usar o aplicativo offline. Acompanhar progresso.')
    def test_keeps_condition_specific_features(self):
        parts=b.segments('Crie rotinas. Receba alertas. Organize reforços positivos.')
        resolved=b.resolve(json.dumps({'features':[{'name':'Criar rotinas','evidence_id':parts[0]['id']},{'name':'Receber alertas','evidence_id':parts[1]['id']}]}),parts,'Crie rotinas. Receba alertas. Organize reforços positivos.')
        self.assertEqual([f['name'] for f in resolved],['Criar rotinas','Receber alertas'])
    def test_context_id_cannot_be_cited(self):
        parts=b.segments('Crie rotinas. Receba alertas.')
        with self.assertRaises(ValueError):b.resolve(json.dumps({'features':[{'name':'Criar rotinas','evidence_id':parts[0]['id']}]}),parts[1:],'Crie rotinas. Receba alertas.')
    def test_complete_empty_flagged_and_repeat_makes_no_new_generation(self):
        self.ready();r=self.run_it()
        self.assertEqual(r['apps_technically_complete'],3);self.assertEqual(r['apps_empty_needing_review'],1)
        self.assertEqual(r['feature_candidates'],3)
        count=len(self.client.calls);again=self.run_it()
        self.assertEqual(len(self.client.calls),count);self.assertEqual(again['scheduled_parts'],0)
        for call in self.client.calls:self.assertEqual(call['format'],'json')
        for line in (self.out/'extractions.jsonl').read_text().splitlines():
            app=json.loads(line)
            for f in app['features']:self.assertTrue(f['literal_verified']);self.assertEqual(f['semantic_review'],'pending')
    def test_partial_run_resumes_all_other_apps_without_repeating_success(self):
        self.ready();first=self.run_it(limit=1);self.assertEqual(first['apps_technically_complete'],1)
        calls=len(self.client.calls);second=self.run_it()
        self.assertEqual(second['apps_technically_complete'],3);self.assertEqual(len(self.client.calls)-calls,2)
    def test_resume_preserves_completed_chunk_inside_long_app(self):
        self.put('01.json',{'group':'TEA','apps':[{'appId':'a.one','title':'Um','description':'Crie rotinas. '*70},
                                                 {'appId':'b.two','title':'Dois','description':'Receba alertas.'}]})
        self.ready();conf={**CONFIG,'chunk_bytes':512}
        self.client.fail_at=2
        r=b.run(self.out,'test:1',conf,client=self.client,limit=1,max_attempts=1)
        self.assertEqual(r['apps_technically_complete'],0)
        with sqlite3.connect(self.out/'checkpoint.sqlite3') as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE state='ok'").fetchone()[0],1)
            total=db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        del self.client.fail_at
        r=b.run(self.out,'test:1',conf,client=self.client,retry_errors=True,max_attempts=1)
        self.assertEqual(r['apps_remaining'],0)
        # First success + one failure + every other job exactly once.
        self.assertEqual(len(self.client.calls),total+1)
    def test_selection_controls_do_not_limit_future_full_run(self):
        self.ready();r=self.run_it(app_ids=['b.two'])
        self.assertEqual(r['apps_technically_complete'],1)
        self.assertEqual(self.run_it()['apps_technically_complete'],3)
    def test_bounded_transport_retries_and_raw_audit(self):
        self.ready();self.client.failures=1
        r=self.run_it(limit=1,max_attempts=2)
        self.assertEqual(r['apps_technically_complete'],1);self.assertEqual(len(self.client.calls),2)
        with sqlite3.connect(self.out/'checkpoint.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],2)
    def test_invalid_json_ids_never_count_as_complete_and_retry_is_explicit(self):
        self.ready();self.client.mode='bad_id';r=self.run_it(limit=1,max_attempts=1)
        self.assertEqual(r['apps_technically_complete'],0);self.assertEqual(r['errors_this_run'],1)
        self.client.mode='normal';self.run_it()
        self.assertEqual(b.export(self.out)['apps_remaining'],1)
        self.assertEqual(self.run_it(retry_errors=True)['apps_remaining'],0)
    def test_truncated_generation_cannot_be_success(self):
        self.ready();self.client.mode='truncated';r=self.run_it(limit=1,max_attempts=1)
        self.assertEqual(r['feature_candidates'],0);self.assertEqual(r['apps_technically_complete'],0)
    def test_fatal_http_stops_scheduling_and_preserves_pending(self):
        self.ready();self.client.failures=99;self.client.failure_status=400
        r=self.run_it(max_attempts=2)
        self.assertEqual(len(self.client.calls),1);self.assertEqual(r['stop_reason'],'ollama_http_configuration_error')
        self.assertEqual(r['apps_remaining'],3)
    def test_generation_deadline_is_not_automatically_retried(self):
        self.ready()
        def timeout(body,on_progress,cancel):
            self.client.calls.append(body);raise OllamaDeadlineError('time limit reached')
        self.client.chat=timeout
        r=self.run_it(max_attempts=2)
        self.assertEqual(len(self.client.calls),1);self.assertEqual(r['stop_reason'],'generation_timeout')
        self.assertEqual(r['apps_remaining'],3)
    def test_consecutive_failures_open_circuit(self):
        self.ready();self.client.failures=99
        r=self.run_it(max_attempts=1,stop_after_errors=2)
        self.assertEqual(len(self.client.calls),2);self.assertEqual(r['stop_reason'],'consecutive_transport_errors')
    def test_changed_model_or_generation_config_cannot_mix_results(self):
        self.ready();self.run_it(limit=1);calls=len(self.client.calls)
        self.client.digest='other-sha'
        with self.assertRaises(ValueError):self.run_it()
        self.assertEqual(len(self.client.calls),calls)
        self.client.digest='fixed-sha'
        with self.assertRaises(ValueError):b.run(self.out,'test:1',{**CONFIG,'seed':43},client=self.client)
    def test_abandoned_running_job_is_recovered(self):
        self.ready();self.run_it(limit=1)
        with sqlite3.connect(self.out/'checkpoint.sqlite3') as db:db.execute("UPDATE jobs SET state='running' WHERE app_id='b.two'")
        self.assertEqual(self.run_it()['apps_remaining'],0)
    def test_parallel_execution_does_not_duplicate_jobs(self):
        self.ready();r=self.run_it(workers=3)
        self.assertEqual(len(self.client.calls),3);self.assertEqual(r['apps_remaining'],0)
    def test_thinking_metadata_avoids_unsupported_flags(self):
        identity={'capabilities':['thinking'],'thinking':{'values':['low','high']}}
        self.assertIsNone(b.thinking_option(identity,'auto'))
        with self.assertRaises(ValueError):b.thinking_option(identity,'off')
        self.assertFalse(b.thinking_option({'capabilities':['thinking'],'thinking':{'values':[False,True]}},'auto'))
    def test_review_copy_is_not_overwritten_on_resume(self):
        self.ready();self.run_it(limit=1)
        target=self.root/'review';b.review_copy(self.out,target)
        edited=target/'apps.csv';edited.write_text('reviewer work',encoding='utf-8')
        self.run_it()
        self.assertEqual(edited.read_text(),'reviewer work')
        with self.assertRaises(FileExistsError):b.review_copy(self.out,target)
        self.assertEqual(edited.read_text(),'reviewer work')
    def test_cancellation_does_not_mark_unprocessed_as_success(self):
        self.ready();cancel=threading.Event();cancel.set()
        r=self.run_it(cancel_event=cancel)
        self.assertEqual(r['apps_remaining'],3);self.assertEqual(len(self.client.calls),0)
    def test_empty_description_is_visible_input_error_without_generation(self):
        self.put('03.json',{'group':'DI','apps':[{'appId':'d.four','description':''}]})
        b.prepare(self.raw,self.out,4);r=self.run_it()
        self.assertEqual(r['states']['input_error'],1);self.assertEqual(len(self.client.calls),3)
    def test_lock_prevents_two_writers(self):
        self.ready()
        with b.exclusive(self.out),self.assertRaises(ValueError):self.run_it()
    def test_live_status_is_read_only_and_does_not_require_writer_lock(self):
        self.ready();self.run_it(limit=1)
        snapshot=(self.out/'apps.csv').read_bytes()
        with b.exclusive(self.out):self.assertEqual(b.status(self.out)['apps_technically_complete'],1)
        self.assertEqual(snapshot,(self.out/'apps.csv').read_bytes())
    def test_export_contains_failed_and_pending_app_rows(self):
        self.ready();self.run_it(limit=1)
        with (self.out/'apps.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),3);self.assertEqual(sum(r['status']=='pending' for r in rows),2)
        self.assertTrue(all(r['human_reviewer']=='' for r in rows))


class HTTPIntegration(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.stall=False
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                value={'models':[{'name':'test:1','digest':'abc'}]} if self.path=='/api/tags' else {'version':'test'}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode())
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/api/show':
                    self.send_response(200);self.end_headers();self.wfile.write(b'{"capabilities":["completion"]}');return
                outer.calls.append(body);self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
                if outer.stall:time.sleep(1);return
                payload=json.loads(body['messages'][1]['content']);key=next(iter(payload['segments']))
                content=json.dumps({'features':[{'name':'Criar rotinas','evidence_id':key}]})
                for part in [content[:10],content[10:]]:
                    self.wfile.write((json.dumps({'done':False,'message':{'content':part}})+'\n').encode());self.wfile.flush()
                self.wfile.write(b'{"done":true,"done_reason":"stop","message":{"content":""}}\n');self.wfile.flush()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_real_http_stream_and_metadata(self):
        client=b.Client(self.url,2);identity=client.identity('test:1');self.assertEqual(identity['digest'],'abc')
        parts=b.segments('Crie rotinas.')
        body={'model':'test:1','messages':[{'role':'system','content':b.SYSTEM_PROMPT},{'role':'user','content':b.user_input({'title':'Teste'},parts)}],'format':'json'}
        raw=client.chat(body,None,threading.Event());features=b.resolve(raw['message']['content'],parts,'Crie rotinas.')
        self.assertEqual(features[0]['evidence'],'Crie rotinas.');self.assertTrue(self.calls[0]['stream'])
    def test_total_deadline_closes_stalled_stream(self):
        self.stall=True;client=b.Client(self.url,0.2)
        body={'model':'test:1','messages':[{'role':'user','content':'{}'}]}
        started=time.monotonic()
        with self.assertRaises(OllamaDeadlineError):client.chat(body,None,threading.Event())
        self.assertLess(time.monotonic()-started,0.8)


if __name__=='__main__':unittest.main()
