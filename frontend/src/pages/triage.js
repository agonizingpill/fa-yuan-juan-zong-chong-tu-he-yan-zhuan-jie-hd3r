import {store} from '../stores/workspace.js';
import {field,input,select,table,badge,textarea} from '../components/controls.js';
import {topics,triageStates} from '../constants/enums.js';
import {esc} from '../utils/format.js';
import {bindForm,request} from '../utils/forms.js';

const QUESTION_TEXT={
  relation:'这次来访主要围绕您和哪一方的关系？',
  subject:'您希望协助处理的核心事项是什么？',
  document:'您手上最主要的书面凭证是哪一类？',
};

function currentVersionRows(){
  const c=store.data.intakes.find(i=>i.id===store.selected);
  return store.data.triages.filter(t=>t.intake_id===c.id&&t.facts_version===c.facts_version);
}
function findQuestion(t){
  const cand=(t.followup_detail?.candidates||[]).find(q=>q.question_id===t.followup_question);
  return cand||null;
}
function stateBadge(t){
  const kind=t.status==='reviewed'?'good':(t.status==='stale'||t.status==='failed')?'warning':'';
  return badge(triageStates[t.status]||t.status,kind);
}

function followupPanel(t){
  if(t.status!=='awaiting_answer')return '';
  const q=findQuestion(t);
  if(!q)return '';
  const outcomes=q.outcomes.map(o=>`<li><b>${esc(o.label)}</b><small>答法概率 ${Math.round(o.answer_probability*100)}% · 答复后主题倾向：${Object.entries(o.posterior).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`${topics[k]} ${Math.round(v*100)}%`).join(' / ')}</small></li>`).join('');
  const options=q.options.map(o=>`<option value="${o.id}">${esc(o.label)}</option>`).join('');
  return `<div class="followup-card">
    <span class="kicker">建议追问（只问这一件事）</span>
    <h3>${esc(QUESTION_TEXT[t.followup_question]||q.question_text)}</h3>
    <p class="followup-reason">${esc(t.followup_detail?.reason||'')}</p>
    <p class="hint">先验熵 ${t.followup_detail?.prior_entropy_bits??'—'} 比特 · 期望信息增益 <b>${q.expected_gain_bits}</b> 比特（确认阈值 ${t.followup_detail?.min_gain_bits??'—'}）</p>
    <ul class="outcomes">${outcomes}</ul>
    <form id="answer" class="paper-form">
      ${field('来访者的答法',select('option_id',options))}
      ${field('实际答复记录（脱敏）',textarea('answer_text','来访者口头答复：'))}
      <button>登记答复并重新分流</button>
      <p class="hint">答复入卷后才重新分流；同一答复重复提交不会再次派活。</p>
    </form>
    <form id="escalate" class="paper-form">
      ${field('交主管说明',input('note','text','追问后仍难以分清主题，提请主管人工研判'))}
      <button class="secondary">答了也难分，卷交主管</button>
    </form>
  </div>`;
}

function escalatedPanel(t){
  if(t.status!=='escalated')return '';
  const post=t.metrics?.followup_posterior;
  return `<div class="followup-card escalated">
    <span class="kicker">主管人工研判队列</span>
    <h3>自动分流置信度不足，已卷交主管</h3>
    <p class="followup-reason">${esc(t.followup_detail?.reason||'追问各答法的期望区分度不足，或答复后仍低于68%确认线。')}</p>
    ${t.answer_text?`<p class="hint">已登记答复：${esc(t.answer_text)}${post?' · 融合后倾向 '+Object.entries(post).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`${topics[k]} ${Math.round(v*100)}%`).join(' / '):''}</p>`:''}
    ${t.followup_detail?.manual_note?`<p class="hint">接待员说明：${esc(t.followup_detail.manual_note)}</p>`:''}
    <form id="escalate" class="paper-form">
      ${field('补充交主管说明',input('note','text','维持人工研判，请主管直接确认专长方向'))}
      <button class="secondary">补充说明并留主管队列</button>
    </form>
  </div>`;
}

export function render(){
  const rows=currentVersionRows(),last=rows.at(-1);
  const reviewable=rows.filter(t=>t.status==='done'||t.status==='escalated');
  return `<h2>咨询主题与专长分流</h2>
  <p class="intro">依据模拟文本推荐劳动、住房或消费方向。置信度低于68%时，系统逐答法试算每个备选问题，只推荐最能分清主题的一问；任何答法都难分则卷交主管。实际答复入卷后才重新分流，所有转介仍需主管确认主题。</p>
  <div class="two-col">
    <form id="enqueue" class="paper-form">
      <h3>按当前事实提交分流</h3>
      <p>提取当前版本描述，送交主题分类。低置信结果会生成追问建议而不是直接给结论。</p>
      <button>提交行政主题识别</button>
      <p class="hint">本页不生成事实判断、法律意见或办案建议。事实更正后旧版本分流自动失效，需重新提交。</p>
    </form>
    <form id="review" class="paper-form">
      <h3>主管主题复核</h3>
      ${field('待复核 / 主管研判记录',select('id',reviewable.map(t=>`<option value="${t.id}">#${t.id} / 版本${t.facts_version} / ${topics[t.predicted]||'待识别'} ${t.confidence===null?'':Math.round(t.confidence*100)+'%'} / ${triageStates[t.status]}</option>`).join('')||'<option value="">当前版本无可复核记录</option>'))}
      ${field('确认专长方向',select('topic',Object.entries(topics).map(([v,l])=>`<option value="${v}">${l}</option>`).join('')))}
      ${field('行政核验说明',input('note','text','已核对来访描述、追问答复和机构接待范围'))}
      <button>确认专长方向</button>
    </form>
  </div>
  ${last?followupPanel(last):''}
  ${last?escalatedPanel(last):''}
  ${table(['记录 / 事实版本','推荐主题','置信度 / 人工','追问与复核进度'],rows.slice().reverse().map(t=>[
    '#'+t.id+' / v'+t.facts_version,
    topics[t.predicted]||'待识别',
    t.confidence===null?'—':Math.round(t.confidence*100)+'% / '+(t.manual_required?'低置信人工介入':'等待主管确认'),
    stateBadge(t)+(t.followup_question&&t.status==='awaiting_answer'?badge('追问：'+(QUESTION_TEXT[t.followup_question]||t.followup_question).slice(0,12)+'…'):''),
  ]))}
  <section class="validation">
    <div><span class="kicker">内部留出评价</span><h3>TF-IDF + 朴素贝叶斯</h3>
      <p>${esc(last?.metrics?.source||'尚无结果')}</p>
      <p>训练 ${last?.metrics?.train_count||0} / 留出 ${last?.metrics?.test_count||0} / seed 34</p>
      ${last?.metrics?.probability_distribution?`<p class="hint">三主题先验：${Object.entries(last.metrics.probability_distribution).map(([k,v])=>`${topics[k]} ${(v*100).toFixed(1)}%`).join(' · ')}</p>`:''}
    </div>
    <div><b>Macro F1 ${last?.metrics?.macro_f1?.toFixed(4)||'—'}</b>
      ${last?.metrics?.confusion_matrix?table(['实际\\预测','劳动','住房','消费'],last.metrics.confusion_matrix.map((r,i)=>[topics[last.metrics.labels[i]],...r])):''}
    </div>
  </section>`;
}

export function bind(r){
  bindForm('enqueue',()=>request('/triages',{intake_id:store.selected}),r);
  bindForm('answer',d=>request('/triages/'+store.data.triages.filter(t=>t.intake_id===store.selected&&t.status==='awaiting_answer').at(-1).id+'/answer',{option_id:d.option_id,answer_text:d.answer_text}),r);
  bindForm('escalate',d=>{const t=store.data.triages.filter(x=>x.intake_id===store.selected&&(x.status==='awaiting_answer'||x.status==='escalated')).at(-1);return request('/triages/'+t.id+'/escalate',{note:d.note});},r);
  bindForm('review',d=>{if(!d.id)throw new Error('当前版本没有可复核的分流记录');return request('/triages/'+d.id+'/review',{topic:d.topic,note:d.note});},r);
}
