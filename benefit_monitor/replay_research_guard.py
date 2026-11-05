"""Read-only compact-response coverage replay; never reads keys or calls HTTP."""
import argparse
import json
from pathlib import Path

from .replay_quality import _json, _local, _recorded, PROJECT
from .research_extraction import assemble
from .research_guard import audit


def replay_record(root, request_id):
    root=_local(root,PROJECT)
    state=_json(_local(root/'live/budget.json',root))
    ledger={r['id']:r for r in state['requests']}
    host,draft=_recorded(root,request_id,ledger,'research')
    _,original=assemble(draft,host)
    return {'request_id':request_id,'recorded_contract':draft['schema_version'],
            'original_contract':original,'current_coverage':audit(draft,host),
            'new_api_calls':0,'new_http_requests':0,'publication_approved':False,
            'v3_model_quality':'not_measured'}


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot-root',type=Path,default=root/'.tools/claude-trial')
    parser.add_argument('--request-id',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=_local(args.output,root)
    if output.exists() or output.is_relative_to(args.pilot_root.resolve()/'live'):
        parser.error('output must be new and outside recorded live artifacts')
    report=replay_record(_local(args.pilot_root,root),args.request_id)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:
        f.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'original_contract_valid':report['original_contract']['valid'],
                      'current_coverage_valid':report['current_coverage']['valid'],'new_api_calls':0}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
