"""Actor-owned speech onset, separate from evidence arrival and observation time."""
import math


def validate_timing(plan, *, evidence_ready, considered_at, source_end):
    for key in ('understood_at','speak_at'):
        value=plan.get(key)
        if type(value) not in (float,int) or not math.isfinite(value):
            raise ValueError('Timing must use finite source seconds')
    if not evidence_ready <= plan['understood_at'] < plan['speak_at'] <= source_end:
        raise ValueError('Speech must follow evidence and understanding, within the viewed segment')
    if plan['speak_at'] < considered_at:
        raise ValueError('Do not backdate a decision to a frame already processed')
    if not isinstance(plan.get('reason'),str) or not plan['reason'].strip():
        raise ValueError('Actor must explain the chosen opening moment')
    return {**plan,'evidence_ready_at':evidence_ready,'considered_at':considered_at}
