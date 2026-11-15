"""Provider-reported usage, independent of checkpoints and successful output."""
import json
from pathlib import Path

def usage_report(root):
    stages={};partial_lines=0
    for path in Path(root).rglob('model-usage.jsonl'):
        for line in path.read_text('utf8').splitlines():
            try:row=json.loads(line)
            except ValueError:partial_lines+=1;continue
            stage=stages.setdefault(row.get('stage','unspecified'),{'requests':0,'reported_requests':0,'failed_outputs':0,'input_tokens':0,'output_tokens':0,'total_tokens':0,'cached_input_tokens':0,'reasoning_tokens':0})
            stage['requests']+=1
            usage=row.get('usage')
            if isinstance(usage,dict):
                stage['reported_requests']+=1
                for target,source in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens'),('total_tokens','total_tokens')]:stage[target]+=usage.get(source,0)
                stage['cached_input_tokens']+=usage.get('prompt_cache_hit_tokens',usage.get('prompt_tokens_details',{}).get('cached_tokens',0))
                stage['reasoning_tokens']+=usage.get('completion_tokens_details',{}).get('reasoning_tokens',0)
            if row.get('finish_reason')!='stop':stage['failed_outputs']+=1
    return {'stages':stages,'partial_log_lines':partial_lines,'note':'Provider-reported tokens, not money. Pre-instrumentation calls are not included; absent usage is unknown, not zero cost.'}
