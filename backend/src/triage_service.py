import os,redis
from fastapi import HTTPException
from sqlalchemy import select
from .models import Intake,Triage
from .common import get,reject,finish,editable
from .intake_service import authorized
from . import followup
queue=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)

# 分流记录状态：
# queued/running 排队或实算中；done 实算完成待主管复核；
# awaiting_answer 已推荐唯一追问、等待实际答复入卷；
# escalated 追问也难分主题，卷交主管；reviewed 主管已复核；
# failed 实算失败；stale 事实已更正，旧版本不可再操作。
ACTIVE_TASKS=('queued','running')
OPEN_STATES=('done','awaiting_answer','escalated')

def latest(db,id):
    case=get(db,Intake,id)
    return db.scalar(select(Triage).where(Triage.intake_id==id,Triage.facts_version==case.facts_version,Triage.status=='reviewed').order_by(Triage.id.desc()))

def prior_of(row):
    dist=(row.metrics or {}).get('probability_distribution')
    if dist:return [max(dist.get(label,1e-6),1e-6) for label in followup.LABELS]
    # 兼容没有完整分布的旧记录：用置信度构造近似先验
    conf=row.confidence or .5
    rest=(1-conf)/2
    return [conf if label==row.predicted else rest for label in followup.LABELS]

def recommend_followup(row):
    """对低置信实算结果试算各备选问题，决定追问还是交主管。"""
    question_id,detail=followup.recommend(prior_of(row))
    row.followup_detail=detail
    if question_id is None:
        row.status='escalated'
        row.followup_question=None
        row.manual_required=True
    else:
        row.status='awaiting_answer'
        row.followup_question=question_id
        row.manual_required=True
    return row

def enqueue(db,data,user):
    case=editable(db,data.intake_id);reject(not authorized(db,case.id),'未取得授权，不能提交行政分流')
    reject(db.scalar(select(Triage).where(Triage.intake_id==case.id,Triage.facts_version==case.facts_version,Triage.status.in_(ACTIVE_TASKS))) is not None,'当前版本仍在分流')
    row=Triage(intake_id=case.id,facts_version=case.facts_version);db.add(row);db.flush();result=finish(db,user,'提交主题分流',row)
    try:queue.rpush('aid:triage',row.id)
    except redis.RedisError:
        row.status='failed';row.error='任务队列暂不可用，恢复后可重新提交';db.commit()
        raise HTTPException(503,row.error)
    return result

def register_answer(db,id,data,user):
    # 实际答复入卷后才重新分流；只有等待答复的记录可登记，重复登记同一答复不会再次派活
    initial=get(db,Triage,id);case=get(db,Intake,initial.intake_id,True)
    row=get(db,Triage,id,True)
    reject(row.facts_version!=case.facts_version,'事实已更正，旧问题不能接答，请按新版本重新分流')
    reject(row.status!='awaiting_answer','该记录不在等待追问答复状态，答复无法登记（重复提交不会重新派活）')
    reject(not authorized(db,case.id),'来访授权已撤回')
    question=followup.get_question(row.followup_question)
    reject(question is None,'原追问已失效，请重新分流')
    option=next((o for o in question['options'] if o['id']==data.option_id),None)
    reject(option is None,'答法不在该问题的备选范围内')
    label,conf,posterior,matched=followup.reclassify(prior_of(row),data.answer_text,option)
    row.answer_option=data.option_id;row.answer_text=data.answer_text
    row.predicted=label;row.confidence=conf
    row.manual_required=conf<followup.THRESHOLD
    row.metrics={**(row.metrics or {}),'followup_posterior':{followup.LABELS[i]:round(posterior[i],4) for i in range(len(followup.LABELS))},'answer_keywords':matched,'reclassified_by':'模型先验+追问答复证据融合'}
    row.followup_detail={**(row.followup_detail or {}),'registered_option':data.option_id,'registered_answer':data.answer_text}
    # 答复后仍低于确认线，不再追问第二轮，直接卷交主管
    row.status='escalated' if row.manual_required else 'done'
    return finish(db,user,'登记追问答复并重新分流',row)

def escalate(db,id,data,user):
    # 接待员主动把答了也难分的卷交主管
    initial=get(db,Triage,id);case=get(db,Intake,initial.intake_id,True);row=get(db,Triage,id,True)
    reject(row.status not in OPEN_STATES,'当前分流记录不能转交主管')
    reject(row.facts_version!=case.facts_version,'事实已更正，请按新版本重新分流')
    row.status='escalated';row.manual_required=True
    note=(row.followup_detail or {})
    note['manual_note']=data.note;row.followup_detail=note
    return finish(db,user,'难分主题卷交主管',row)

def review(db,id,data,user):
    initial=get(db,Triage,id);case=get(db,Intake,initial.intake_id,True);row=get(db,Triage,id,True)
    reject(row.status not in ('done','escalated'),'等待分流完成或主管人工研判后再复核')
    reject(row.facts_version!=case.facts_version,'事实已更正，请重新分流')
    reject(not authorized(db,case.id),'来访授权已撤回')
    row.approved=data.topic;row.review_note=data.note;row.status='reviewed';return finish(db,user,'专长人工复核',row)
