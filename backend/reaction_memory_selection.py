"""Select optional memory inside the request budget; originals stay on disk."""
import hashlib
import json
import re

def terms(text):
    text=str(text).lower()
    words=set(re.findall(r'[a-z0-9_]+',text))
    for run in re.findall(r'[\u3400-\u9fff]+',text):
        words.update(run[i:i+2] for i in range(len(run)-1))
    return words

def select_optional_memories(payloads, query):
    """Lowest relevance first so the common budget removes those first.

    Dedup is confined to explicit memory arrays; independent evidence, dialogue,
    speaker uncertainty, persona and reasoning prefixes are never collapsed.
    """
    seen=set();duplicates=0;q=terms(query)
    def visit(obj):
        nonlocal duplicates
        if not isinstance(obj,dict):return
        for key,value in obj.items():
            if key=='memory' and isinstance(value,list):
                kept=[]
                for row in value:
                    text=row.get('text',row.get('body',json.dumps(row,ensure_ascii=False))) if isinstance(row,dict) else str(row)
                    digest=hashlib.sha256(re.sub(r'\s+',' ',text).strip().encode()).hexdigest()
                    if digest in seen:duplicates+=1;continue
                    seen.add(digest);kept.append((len(q&terms(text)),row))
                obj[key]=[row for _,row in sorted(kept,key=lambda item:item[0])]
            elif isinstance(value,dict):visit(value)
    for obj in payloads:visit(obj)
    return duplicates

def current_query(messages):
    for message in reversed(messages):
        if message.get('role')!='user':continue
        content=message.get('content','')
        if isinstance(content,list):content=' '.join(b.get('text','') for b in content if b.get('type')=='text')
        try:
            data=json.loads(content)
            # Only current evidence/question, never the past memory being ranked.
            content=json.dumps({k:data[k] for k in ('question','evidence','observation','hearing','cursor') if k in data},ensure_ascii=False)
        except (ValueError,TypeError):pass
        return content[-4000:]
    return ''
