"""Job-scoped control mailbox. Does not expose arbitrary paths to an agent."""
import contextlib
import json
import os
import time
import uuid


@contextlib.contextmanager
def exclusive_job(path):
    with path.open('a+b') as f:
        if f.tell()==0:f.write(b'0');f.flush()
        f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:raise RuntimeError('Job already owned') from exc
        try:yield
        finally:
            f.seek(0)
            if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)


def write_json(path,value):
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for n in range(40):
        try:temp.replace(path);return
        except PermissionError:
            if n==39:raise
            time.sleep(.025)


def pending_control(output,state):
    folder=output.parent/'controls'
    done={e.get('control_id') for e in state['events']}
    for path in sorted(folder.glob('*.json')):
        value=json.loads(path.read_text(encoding='utf-8'))
        if value['id'] not in done:return value
    return None
