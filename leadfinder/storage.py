import json, sqlite3, time
from .schema import Lead


def connect(path="leads.db"):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, ts REAL, icp TEXT, filters TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS leads(run_id INT, email TEXT, score INT, data TEXT, UNIQUE(run_id,email))")
    return db


def save_run(db, filters, leads: list[Lead]) -> int:
    cur = db.execute("INSERT INTO runs(ts,icp,filters) VALUES(?,?,?)", (time.time(), filters.raw_icp, json.dumps(filters.to_dict())))
    rid = cur.lastrowid
    for l in leads:
        db.execute("INSERT OR REPLACE INTO leads VALUES(?,?,?,?)", (rid, l.email, l.score, json.dumps(l.to_row())))
    db.commit()
    return rid
