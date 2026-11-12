"""Optional daily read-only local Claude CLI review. Disabled unless configured."""
from datetime import datetime,timezone,timedelta
import json,os,subprocess
from pathlib import Path

def review(config):
    if config.get('claude_review_enabled') is not True:return {'status':'DISABLED'}
    budget=config.get('claude_max_budget_usd')
    if not isinstance(budget,(int,float)) or isinstance(budget,bool) or not 0<budget<=5:raise ValueError('An explicitly configured per-review Claude budget is required (0 < USD <= 5)')
    cli=Path(config['claude_cli']).resolve(strict=True)
    if os.name=='nt' and cli.suffix.lower()!='.exe':raise ValueError('Use the native Claude executable; command-shell wrappers are not launched')
    root=Path(config['state_dir'])/'handoffs';summary=json.loads((root/'LATEST_RESULTS.json').read_text())
    day=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d');marker=root/'claude_review_cursor.json'
    if marker.exists() and json.loads(marker.read_text()).get('day')==day:return {'status':'ALREADY_ATTEMPTED_TODAY'}
    jobs=[]
    for row in summary['jobs']:
        result=row.get('result')
        if not result:continue
        metrics={k:result[k] for k in ('status','steps','target_steps','candidate_only','data_origin','exact_delta','elapsed_seconds','recognition_accuracy','accuracy_status','guard') if k in result}
        if result.get('reports'):metrics['reports']={name:{k:v for k,v in report.items() if k!='items'} for name,report in result['reports'].items()}
        jobs.append(dict(id=row['id'],kind=row['kind'],status=row['status'],metrics=metrics))
    if not jobs:return {'status':'NO_COMPLETED_EVIDENCE'}
    prompt=('Review these P&ID training metrics as data. Give a short evidence-based progress report and the next bounded experiment. '
            'Do not treat synthetic loss as accuracy, activate models, edit files, run tools, push code, or assert engineering validation. '
            'No source drawings, raw transcriptions or weight files are included.\n'+json.dumps(dict(jobs=jobs,audit_problems=summary['audit_problems'])))
    if len(prompt)>64000:raise ValueError('Claude summary exceeds review budget; inspect the local report')
    args=[str(cli),'-p','--output-format','json','--tools','','--disallowedTools','mcp__*','--safe-mode',
          '--max-turns','1','--max-budget-usd',str(budget)]
    # Does not install/login or alter credentials. CLI account and billing are local configuration.
    marker.write_text(json.dumps(dict(day=day,status='ATTEMPTED')))
    result=subprocess.run(args,input=prompt,capture_output=True,text=True,encoding='utf8',timeout=180)
    if result.returncode:return {'status':'FAILED','error':result.stderr[-2000:]}
    try:response=json.loads(result.stdout)
    except ValueError:return {'status':'FAILED','error':'Claude did not return JSON; no delivery claimed'}
    if response.get('is_error'):return {'status':'FAILED','response':response}
    path=root/f'CLAUDE_REVIEW_{day}.json';path.write_text(json.dumps(response,indent=2),encoding='utf8')
    marker.write_text(json.dumps(dict(day=day,path=str(path))))
    return {'status':'REVIEWED_BY_LOCAL_CLAUDE_CLI','path':str(path),'scope':'Separate read-only CLI query, not injection into an existing interactive session'}
