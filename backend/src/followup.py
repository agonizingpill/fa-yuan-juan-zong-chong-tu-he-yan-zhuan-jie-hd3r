"""单问追问推荐与答复重算。

接待员拿不准主题时只够时间追问一件事。本模块对每个备选问题逐种答法
试算期望信息增益（先验熵减去答复后的期望后验熵），挑最能分清三主题的
一问；任何答法都难以降低不确定性时建议交主管（escalate）。

仅用于行政分流，不产生法律意见或实体判断。
"""
import math
from .constants import Topic

LABELS=[t.value for t in Topic]
THRESHOLD=.68
# 期望信息增益低于该值（比特）时，认为追问也难分主题，卷交主管
MIN_GAIN=.08
# 答复证据相对模型先验的融合强度：越大越偏向答复关键词
EVIDENCE_LAMBDA=.75

# 关键词 -> 三主题证据权重
KEYWORDS={
    # 劳动
    '工资':{'labor':.9,'housing':.05,'consumer':.05},
    '薪水':{'labor':.9,'housing':.05,'consumer':.05},
    '报酬':{'labor':.85,'housing':.08,'consumer':.07},
    '加班':{'labor':.9,'housing':.05,'consumer':.05},
    '工时':{'labor':.85,'housing':.1,'consumer':.05},
    '劳动合同':{'labor':.92,'housing':.05,'consumer':.03},
    '用工':{'labor':.85,'housing':.1,'consumer':.05},
    '单位':{'labor':.75,'housing':.15,'consumer':.1},
    '辞退':{'labor':.9,'housing':.05,'consumer':.05},
    '离职':{'labor':.7,'housing':.15,'consumer':.15},
    '考勤':{'labor':.9,'housing':.05,'consumer':.05},
    '社保':{'labor':.85,'housing':.1,'consumer':.05},
    # 住房
    '租房':{'labor':.05,'housing':.9,'consumer':.05},
    '租赁':{'labor':.05,'housing':.9,'consumer':.05},
    '房东':{'labor':.05,'housing':.9,'consumer':.05},
    '押金':{'labor':.05,'housing':.88,'consumer':.07},
    '退租':{'labor':.05,'housing':.9,'consumer':.05},
    '租金':{'labor':.08,'housing':.85,'consumer':.07},
    '房屋':{'labor':.05,'housing':.85,'consumer':.1},
    '住房':{'labor':.05,'housing':.9,'consumer':.05},
    '物业':{'labor':.1,'housing':.8,'consumer':.1},
    '漏水':{'labor':.05,'housing':.88,'consumer':.07},
    '维修':{'labor':.1,'housing':.75,'consumer':.15},
    # 消费
    '购物':{'labor':.05,'housing':.05,'consumer':.9},
    '商品':{'labor':.05,'housing':.08,'consumer':.87},
    '消费':{'labor':.05,'housing':.08,'consumer':.87},
    '退款':{'labor':.08,'housing':.1,'consumer':.82},
    '订单':{'labor':.05,'housing':.05,'consumer':.9},
    '商家':{'labor':.05,'housing':.08,'consumer':.87},
    '收据':{'labor':.08,'housing':.1,'consumer':.82},
    '质量':{'labor':.08,'housing':.15,'consumer':.77},
    '保修':{'labor':.05,'housing':.1,'consumer':.85},
    '电器':{'labor':.05,'housing':.1,'consumer':.85},
    '消费者':{'labor':.05,'housing':.05,'consumer':.9},
}

# 备选问题库。每个选项携带证据权重（与关键词同构），逐答法试算后验。
QUESTIONS=[
    {
        'id':'relation',
        'text':'这次来访主要围绕您和哪一方的关系？',
        'options':[
            {'id':'employer','label':'用工单位、雇主或工作场所','weights':{'labor':.9,'housing':.05,'consumer':.05}},
            {'id':'landlord','label':'房东、物业或出租房屋','weights':{'labor':.05,'housing':.9,'consumer':.05}},
            {'id':'merchant','label':'商家、店铺或网购平台','weights':{'labor':.05,'housing':.05,'consumer':.9}},
        ],
    },
    {
        'id':'subject',
        'text':'您希望协助处理的核心事项是什么？',
        'options':[
            {'id':'pay','label':'拖欠的工资、加班费或劳动报酬','weights':{'labor':.92,'housing':.04,'consumer':.04}},
            {'id':'rent','label':'租房押金、租金退结或房屋维修','weights':{'labor':.04,'housing':.92,'consumer':.04}},
            {'id':'refund','label':'商品质量、退款或售后保修','weights':{'labor':.04,'housing':.04,'consumer':.92}},
        ],
    },
    {
        'id':'document',
        'text':'您手上最主要的书面凭证是哪一类？',
        'options':[
            {'id':'contract','label':'劳动合同、考勤或工资条','weights':{'labor':.9,'housing':.07,'consumer':.03}},
            {'id':'lease','label':'租赁合同、押金或租金收据','weights':{'labor':.05,'housing':.9,'consumer':.05}},
            {'id':'order','label':'购物订单、消费小票或保修单','weights':{'labor':.05,'housing':.07,'consumer':.88}},
        ],
    },
]


def entropy(probs):
    return -sum(p*math.log2(p) for p in probs if p>0)


def _posterior(prior, evidence, lam=EVIDENCE_LAMBDA):
    """模型先验与答复证据在对数空间融合，归一化为新后验。"""
    logs=[math.log(prior[i])+lam*math.log(evidence[i]) for i in range(len(LABELS))]
    m=max(logs)
    exps=[math.exp(v-m) for v in logs]
    total=sum(exps)
    return [v/total for v in exps]


def _option_evidence(weights):
    return [max(weights.get(label,.02),.02) for label in LABELS]


def expected_gain(prior, question):
    """对一个问题的每种答法试算后验，返回期望信息增益和逐答法明细。"""
    base=entropy(prior)
    expected=0.0
    outcomes=[]
    for opt in question['options']:
        evidence=_option_evidence(opt['weights'])
        post=_posterior(prior, evidence)
        # 该答法出现的概率：用先验在该答法所指向主题上的吻合度估计
        p_answer=sum(prior[i]*evidence[i] for i in range(len(LABELS)))
        p_answer=max(p_answer,1e-6)
        expected+=p_answer*entropy(post)
        outcomes.append({'option_id':opt['id'],'label':opt['label'],
                         'posterior':{LABELS[i]:round(post[i],4) for i in range(len(LABELS))},
                         'answer_probability':round(p_answer,4)})
    total_p=sum(o['answer_probability'] for o in outcomes)
    for o in outcomes:o['answer_probability']=round(o['answer_probability']/total_p,4)
    expected/=total_p
    return max(base-expected,0.0), outcomes


def recommend(prior):
    """试算每个备选问题的各种答法，挑最能分清主题的一问。

    返回 (question_id 或 None, 详情 dict)。增益全部过低时返回 None，建议交主管。
    """
    base=entropy(prior)
    scored=[]
    for q in QUESTIONS:
        gain, outcomes=expected_gain(prior,q)
        scored.append({'question_id':q['id'],'question_text':q['text'],
                       'expected_gain_bits':round(gain,4),'outcomes':outcomes,
                       'options':q['options']})
    scored.sort(key=lambda x:x['expected_gain_bits'],reverse=True)
    best=scored[0]
    detail={'prior_entropy_bits':round(base,4),'candidates':scored,
            'min_gain_bits':MIN_GAIN}
    if best['expected_gain_bits']<MIN_GAIN:
        detail['reason']='各备选问题任一答法后的期望不确定性仍偏高，追问难以分清主题，建议卷交主管人工研判。'
        return None,detail
    top=LABELS[max(range(len(LABELS)),key=lambda i:prior[i])]
    detail['reason']=(f"该问在三种答法下期望信息增益最高（{best['expected_gain_bits']} 比特），"
                      f"能把当前最接近的候选主题进一步拉开；现有先验以「{topic_label(top)}」最可能但未达确认线。")
    return best['question_id'],detail


def get_question(question_id):
    return next((q for q in QUESTIONS if q['id']==question_id),None)


def topic_label(value):
    return {'labor':'劳动报酬','housing':'住房租赁','consumer':'消费服务'}.get(value,value)


def answer_evidence(text, option=None):
    """从答复自由文本抽取关键词证据，并叠加所选选项的权重。"""
    evidence=[.05]*len(LABELS)
    matched=[]
    for token,weight in KEYWORDS.items():
        if token in text:
            matched.append(token)
            for i,label in enumerate(LABELS):
                evidence[i]+=weight.get(label,0.0)
    if option is not None:
        for i,label in enumerate(LABELS):
            evidence[i]+=option['weights'].get(label,0.0)
    total=sum(evidence)
    evidence=[v/total for v in evidence]
    return evidence, matched


def reclassify(prior, answer_text, option=None):
    """实际答复入卷后，融合模型先验与答复证据重新分流。"""
    raw,matched=answer_evidence(answer_text,option)
    post=_posterior(prior,raw)
    idx=max(range(len(LABELS)),key=lambda i:post[i])
    return LABELS[idx],post[idx],post,matched
