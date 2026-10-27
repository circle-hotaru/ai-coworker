"""Private, durable voice-task notification enrollment and delivery deduplication."""
from contextlib import contextmanager
import hashlib
import os
import sqlite3
import time
from pathlib import Path

from core.utils.device_registry import DEVICE_AGENTS
def message_id(session, run, text): return hashlib.sha256((session+'|'+run+'|'+digest(text)).encode()).hexdigest()
def digest(text): return hashlib.sha256(''.join(text.split()).encode()).hexdigest()

class PushStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create privately before sqlite opens it; never temporarily expose message text.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600); os.close(fd)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS tasks(
                session TEXT PRIMARY KEY, device TEXT, active INTEGER, run TEXT, hash TEXT, updated REAL);
                CREATE TABLE IF NOT EXISTS notices(
                id TEXT PRIMARY KEY, session TEXT, run TEXT, text TEXT, state TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS primaries(session TEXT,run TEXT,hash TEXT,created REAL);''')
    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db: yield db
        finally: db.close()
    def recover(self):
        with self.db() as db: db.execute('UPDATE tasks SET active=0')
    def allow_existing(self, conversation, device):
        session = 'agent:'+DEVICE_AGENTS[device]+':openai-user:'+conversation.lower()
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO tasks VALUES(?,?,0,NULL,NULL,?)',(session,device,time.time()))
    def enroll(self, conversation, device):
        session = 'agent:'+DEVICE_AGENTS[device]+':openai-user:'+conversation.lower()
        with self.db() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,1,NULL,NULL,?) ON CONFLICT(session) DO UPDATE SET active=1, run=NULL, hash=NULL, updated=excluded.updated', (session,device,time.time()))
        return session
    def complete_primary(self, session, run, text):
        with self.db() as db:
            db.execute('INSERT INTO primaries VALUES(?,?,?,?)',(session,run,digest(text),time.time()))
            db.execute('UPDATE tasks SET active=0,run=?,hash=?,updated=? WHERE session=?',(run,digest(text),time.time(),session))
            db.execute("UPDATE notices SET state='spoken' WHERE state='pending' AND session=? AND (run=? OR replace(text,' ','')=?)",(session,run,text.replace(' ','')))
    def enqueue(self, session, run, text):
        token = message_id(session,run,text)
        with self.db() as db:
            task = db.execute('SELECT active,run,hash,updated,device FROM tasks WHERE session=?',(session,)).fetchone()
            if not task or task[4] not in DEVICE_AGENTS or not session.startswith('agent:'+DEVICE_AGENTS[task[4]]+':openai-user:'): return None
            state = 'pending'
            if db.execute('SELECT 1 FROM primaries WHERE session=? AND (run=? OR (hash=? AND created>?))',(session,run,digest(text),time.time()-120)).fetchone(): state='spoken'
            if task[1] == run or (task[2] == digest(text) and time.time()-task[3]<120): state='spoken'
            db.execute('INSERT OR IGNORE INTO notices VALUES(?,?,?,?,?,?)',(token,session,run,text,state,time.time()))
        return token
    def owner(self, token):
        with self.db() as db:
            row=db.execute('SELECT t.device FROM notices n JOIN tasks t ON t.session=n.session WHERE n.id=?',(token,)).fetchone()
            return row[0] if row else None
    def next(self, device=None):
        with self.db() as db:
            db.execute("UPDATE notices SET state='expired' WHERE state IN ('pending','accepted') AND created<?",(time.time()-86400,))
            # The primary HTTP stream can finish after agent_end arrives. Hold all
            # events until completion so its final answer is never spoken twice.
            rows=db.execute("SELECT n.id,n.text,n.state,t.run,t.hash,t.updated,n.run FROM notices n JOIN tasks t ON t.session=n.session WHERE n.state IN ('pending','accepted') AND t.active=0 AND (? IS NULL OR t.device=?) ORDER BY n.created LIMIT 1",(device,device)).fetchone()
            if not rows:return None
            token,text,state,primary,hashed,updated,run=rows
            known=db.execute('SELECT 1 FROM primaries WHERE session=(SELECT session FROM notices WHERE id=?) AND (run=? OR (hash=? AND created>?))',(token,run,digest(text),time.time()-120)).fetchone()
            if state=='pending' and (known or run==primary or (digest(text)==hashed and time.time()-updated<120)):
                db.execute("UPDATE notices SET state='spoken' WHERE id=?",(token,));return None
            return token,text,state
    def set_state(self,token,state):
        with self.db() as db:db.execute('UPDATE notices SET state=? WHERE id=?',(state,token))
