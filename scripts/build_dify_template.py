"""Generate an importable, local-only Dify chatflow without a model API key."""
from pathlib import Path
import sys
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.dialogue import SYSTEM

project=Path(__file__).resolve().parents[1]
build_code='''import json
def main(query: str, audio_emotion: str = "unknown") -> dict:
    system = %r
    payload = {"model":"qwen3.5:4b","messages":[{"role":"system","content":system},{"role":"user","content":"用户原话："+query+"\\n语音情绪："+(audio_emotion or "unknown")}],"stream":False,"think":False,"format":"json","options":{"num_ctx":4096,"num_predict":300,"temperature":0.3}}
    return {"payload":json.dumps(payload,ensure_ascii=False)}
''' % SYSTEM
parse_code='''import json
def main(body: str) -> dict:
    content = json.loads(body)["message"]["content"]
    value = json.loads(content)
    if not isinstance(value.get("reply"), str):
        raise ValueError("模型未生成回复")
    return {"answer":json.dumps(value,ensure_ascii=False)}
'''
def node(nid,title,type_,x,data):
    return {'id':nid,'type':'custom','position':{'x':x,'y':200},'positionAbsolute':{'x':x,'y':200},'width':244,'height':100,'sourcePosition':'right','targetPosition':'left','data':{'title':title,'type':type_,'desc':'','selected':False,**data}}
nodes=[
node('start','开始','start',80,{'variables':[{'label':'语音情绪','variable':'audio_emotion','type':'text-input','required':False,'max_length':50}]}),
node('build','构建模型输入','code',380,{'code_language':'python3','code':build_code,'variables':[{'variable':'query','value_selector':['sys','query']},{'variable':'audio_emotion','value_selector':['start','audio_emotion']}],'outputs':{'payload':{'type':'string','children':None}}}),
node('model','本机 Ollama','http-request',680,{'method':'post','url':'http://host.docker.internal:11434/api/chat','authorization':{'type':'no-auth','config':None},'headers':'Content-Type:application/json','params':'','body':{'type':'raw-text','data':[{'id':'body','type':'text','key':'','value':'{{#build.payload#}}'}]},'timeout':{'connect':10,'read':180,'write':30},'retry_config':{'retry_enabled':False,'max_retries':1,'retry_interval':1000},'ssl_verify':True}),
node('parse','解析共情结果','code',980,{'code_language':'python3','code':parse_code,'variables':[{'variable':'body','value_selector':['model','body']}],'outputs':{'answer':{'type':'string','children':None}}}),
node('answer','返回结果','answer',1280,{'answer':'{{#parse.answer#}}','variables':[]})]
edges=[]
for a,b in zip(nodes,nodes[1:]):
    edges.append({'id':a['id']+'-'+b['id'],'type':'custom','source':a['id'],'sourceHandle':'source','target':b['id'],'targetHandle':'target','data':{'sourceType':a['data']['type'],'targetType':b['data']['type'],'isInIteration':False,'isInLoop':False}})
doc={'app':{'name':'湖大机械狗文本共情','description':'本机 Ollama 驱动的文本共情流程。图像交互由主应用处理。','mode':'advanced-chat','icon':'robot','icon_background':'#E4FBCC','use_icon_as_answer_icon':False},'kind':'app','version':'0.3.0','dependencies':[],'workflow':{'conversation_variables':[],'environment_variables':[],'features':{'opening_statement':'你好，我是小伴。今天想聊些什么？','suggested_questions':[],'suggested_questions_after_answer':{'enabled':False},'speech_to_text':{'enabled':False},'text_to_speech':{'enabled':False},'retriever_resource':{'enabled':False},'sensitive_word_avoidance':{'enabled':False},'file_upload':{'enabled':False}},'graph':{'nodes':nodes,'edges':edges,'viewport':{'x':0,'y':0,'zoom':0.7}}}}
(project/'deploy/empathy-chatflow.yml').write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False),encoding='utf-8')
print('Dify template generated')
