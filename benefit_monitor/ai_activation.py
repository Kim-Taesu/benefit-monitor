"""Prepare disabled, reviewable local daily-job artifacts; never installs them."""
import argparse
from pathlib import Path
import plistlib
import shutil
import sys

from .official_reader import project_path
from .store import save


def prepare(root,output):
    root=Path(root).resolve();output=project_path(root,Path(output).resolve())
    if output.exists() and any(output.iterdir()):raise ValueError('activation output must be empty')
    output.mkdir(parents=True,exist_ok=True)
    config={'schema_version':1,'enabled':False,'recurring_spend_approved':False,'public_application_approved':False,
            'hour_kst':6,'minute_kst':0,'max_ai_candidates_per_day':2,
            'remote_delivery_approved':False,'repository':'Kim-Taesu/benefit-monitor',
            'deploy_ref':'docs/ai-research-playbook','trial_expires_at':None}
    save(output/'ai-automation.json',config)
    from .public_topics import CATEGORY_TOPICS
    save(output/'topic-basis.json',{'schema_version':1,'items':[],
                                  'category_policy':{'approved':False,'mapping':CATEGORY_TOPICS}})
    save(output/'topic-publication.json',{'approved':False,'mode':'reviewed_policy','policy_sha256':None,'expires_at':None})
    paths=[str(Path(sys.executable).parent)]
    gh=shutil.which('gh')
    if gh:paths.append(str(Path(gh).parent))
    paths.extend(['/usr/bin','/bin','/usr/sbin','/sbin'])
    agent={'Label':'com.benefit-monitor.ai-daily','ProgramArguments':[sys.executable,'-m','benefit_monitor.ai_daily','--root',str(root),'--scheduled'],
           'WorkingDirectory':str(root),'StartInterval':900,'RunAtLoad':True,
           'EnvironmentVariables':{'TZ':'Asia/Seoul','PATH':':'.join(dict.fromkeys(paths)),
                                   'TMPDIR':str(root/'.tools/tmp')},
           'StandardOutPath':str(root/'cache/ai_daily/scheduler.log'),
           'StandardErrorPath':str(root/'cache/ai_daily/scheduler-error.log')}
    (output/'ai-daily.plist').write_bytes(plistlib.dumps(agent))
    plan={'installed':False,'enabled':False,'root':str(root),'candidate_limit_per_day':2,'topic_limit_per_day':1,
          'daily_kst':'06:00 이후 첫15분간격 점검; 중복 실행 차단','budget':'기존 전체 누적 $5·40요청. 초기화하지 않음.',
          'proposed_agent_file':str(Path.home()/'Library/LaunchAgents/com.benefit-monitor.ai-daily.plist'),
          'approval_required':['반복 Claude API 지출','검토 정책에 따른 공개 적용','명시한 LaunchAgent 파일 설치·등록',
                               '개인 저장소 briefing-data 반영·작업 브랜치 push와 workflow 배포','Pages 환경의 작업 브랜치 허용'],
          'installation_preconditions':['프로젝트 내부 cache/ai_daily 및 .tools/tmp 디렉터리 준비','개인 gh 계정 확인','작업 브랜치·배포 코드 SHA 일치'],
          'deployment':'원격 배포·main 병합은 수행하지 않음'}
    save(output/'plan.json',plan)
    return plan


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    prepare(args.root,args.output)
    print('Prepared disabled plan; not installed')


if __name__=='__main__':main()
