"""One daily topic proposal from approved facts; private drafts and safe fallback."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .ai_review import invoke
from .claude_trial import evaluate_draft
from .daily_topics import fallback
from .official_reader import project_path
from .public_topics import approved_snapshot
from .store import load,save,lock


def refresh(root,now=None,execute=False):
    root=Path(root).resolve()
    now=now or datetime.now(ZoneInfo('Asia/Seoul'))
    if now.tzinfo is None:raise ValueError('timezone required')
    now=now.astimezone(ZoneInfo('Asia/Seoul'))
    with lock(project_path(root,'cache/ai_topics/.lock')):
        previous=load(project_path(root,'cache/ai_topics/last_valid.json'),{'topics':[]})
        host=approved_snapshot(root,now,previous['topics'])
        state=load(project_path(root,'cache/ai_topics/days.json'),{'days':{}})
        day=now.date().isoformat()
        cards=fallback(previous['topics'],host)
        result={'status':'not_requested','run_id':None}
        validation=None
        used_fallback=True
        if execute and host['approved_items'] and day not in state['days']:
            input_path=project_path(root,'.tools/ai-topic-inputs/'+day+'-'+host['snapshot_id']+'.json')
            save(input_path,host)
            # Persist before calling: a crash cannot open another paid daily attempt.
            state['days'][day]={'input_file':str(input_path.relative_to(root)),'status':'attempted','snapshot_id':host['snapshot_id']}
            save(project_path(root,'cache/ai_topics/days.json'),state)
            result=invoke(root,'topic',input_path)
            if result['status']=='validated_draft':
                try:
                    model=load(project_path(root,'.tools/claude-trial/live/runs/'+result['run_id']+'/result.json'),None)
                    _,validation=evaluate_draft(model,host,'topic')
                    if validation['valid']:
                        cards=model['topics'];used_fallback=False
                        save(project_path(root,'cache/ai_topics/last_valid.json'),{'topics':cards,'run_id':result['run_id'],'generated_at':now.isoformat()})
                except (OSError,ValueError,KeyError,TypeError):
                    validation={'valid':False,'errors':['topic draft cannot be revalidated']}
            state['days'][day].update(result)
            save(project_path(root,'cache/ai_topics/days.json'),state)
        elif execute and day in state['days']:
            result={'status':'already_attempted_today','run_id':state['days'][day].get('run_id')}
        draft=dict(schema_version='topic-refresh-v1',generated_at=now.isoformat(),source_review_id=host['source_review_id'],
                   snapshot_id=host['snapshot_id'],model=result,validation=validation,topics=cards,
                   used_fallback=used_fallback,publication_approved=False)
        save(project_path(root,'cache/ai_topics/draft.json'),draft)
        return draft
