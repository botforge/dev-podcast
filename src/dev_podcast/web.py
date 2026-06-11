"""Local web UI: tweak the persona sliders + starting point, generate, and watch the
script render live as a screenplay (not JSON).

Run:  uv run dev-podcast-web   ->  open http://127.0.0.1:5005
Nothing heavy runs locally -- it drives the same Dialogue engine (Claude API).
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template_string, request, url_for

from .dialogue import TEACHER, Dialogue
from .personas import (
    DEFAULT_STARTING_POINT,
    STUDENT_PRESETS,
    TEACHER_PRESETS,
    Episode,
    PodcastConfig,
    StudentPersona,
    TeacherPersona,
)

load_dotenv()
app = Flask(__name__)
JOBS: dict[str, dict] = {}
OUT = Path("out")

STUDENT_SLIDERS = ["pace", "depth", "testing_appetite", "assertiveness", "tangents"]
TEACHER_SLIDERS = ["directness", "conciseness", "rigor", "encouragement", "testing_inclination"]


def _run(job_id: str, cfg: PodcastConfig) -> None:
    job = JOBS[job_id]

    def on_turn(t):
        job["turns"].append(
            {"speaker": "SENIOR" if t.speaker_id == TEACHER else "JUNIOR",
             "text": t.text, "segment": t.segment_type}
        )

    try:
        dlg = Dialogue(cfg, on_turn=on_turn)
        dlg.run()
        dlg.save(OUT / cfg.repo.replace("/", "__"))
        job["status"] = "done"
    except Exception as e:  # surface in the UI
        job["status"] = "error"
        job["error"] = str(e)


INDEX = """
<!doctype html><html><head><meta charset="utf-8"><title>dev-podcast</title>
<style>
 body{font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:880px;margin:24px auto;padding:0 16px;color:#1a1a1a}
 h1{font-size:22px} h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:#666;margin:22px 0 8px}
 .row{display:flex;align-items:center;gap:12px;margin:6px 0}
 .row label{width:150px;font-size:13px} .row input[type=range]{flex:1} .row .val{width:38px;text-align:right;color:#888;font-variant-numeric:tabular-nums}
 .cols{display:flex;gap:32px;flex-wrap:wrap} .col{flex:1;min-width:300px}
 input[type=text],textarea,select{width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;font:inherit;box-sizing:border-box}
 textarea{height:64px} .meta{display:flex;gap:12px} .meta>div{flex:1}
 button{margin-top:18px;padding:10px 20px;font:inherit;font-weight:600;background:#111;color:#fff;border:0;border-radius:8px;cursor:pointer}
 .preset{margin-bottom:8px}
</style></head><body>
<h1>dev-podcast — persona studio</h1>
<form method="post" action="/generate">
 <div class="meta">
  <div><label>Repo (public owner/name)</label><input type="text" name="repo" value="{{repo}}"></div>
  <div><label>Minutes</label><input type="text" name="minutes" value="{{minutes}}"></div>
  <div><label>Tone</label><select name="tone"><option>casual</option><option>formal</option></select></div>
 </div>
 <h2>Starting point (student's opening line)</h2>
 <textarea name="starting_point">{{starting_point}}</textarea>
 <div class="cols">
  <div class="col"><h2>Student (junior)</h2>
   <div class="preset">preset: <select onchange="applyPreset('s',this.value)">
     <option value="">custom</option>{% for p in student_presets %}<option>{{p}}</option>{% endfor %}</select></div>
   {% for k in student_sliders %}
   <div class="row"><label>{{k}}</label>
    <input type="range" name="s_{{k}}" min="0" max="1" step="0.05" value="{{student[k]}}"
      oninput="this.nextElementSibling.textContent=(+this.value).toFixed(2)">
    <span class="val">{{'%.2f'|format(student[k])}}</span></div>
   {% endfor %}
  </div>
  <div class="col"><h2>Teacher (senior)</h2>
   <div class="preset">preset: <select onchange="applyPreset('t',this.value)">
     <option value="">custom</option>{% for p in teacher_presets %}<option>{{p}}</option>{% endfor %}</select></div>
   {% for k in teacher_sliders %}
   <div class="row"><label>{{k}}</label>
    <input type="range" name="t_{{k}}" min="0" max="1" step="0.05" value="{{teacher[k]}}"
      oninput="this.nextElementSibling.textContent=(+this.value).toFixed(2)">
    <span class="val">{{'%.2f'|format(teacher[k])}}</span></div>
   {% endfor %}
  </div>
 </div>
 <button type="submit">Generate script</button>
</form>
<script>
 const PRESETS={{presets_json|safe}};
 function applyPreset(side,name){ if(!name)return; const vals=PRESETS[side][name];
   for(const k in vals){ const inp=document.querySelector(`[name=${side}_${k}]`);
     if(inp){ inp.value=vals[k]; inp.nextElementSibling.textContent=(+vals[k]).toFixed(2);} } }
</script></body></html>
"""

VIEW = """
<!doctype html><html><head><meta charset="utf-8"><title>{{repo}} — script</title>
<style>
 body{font:16px/1.6 Georgia,serif;max-width:760px;margin:24px auto;padding:0 16px;color:#1a1a1a}
 .top{font:13px -apple-system,system-ui,sans-serif;color:#666;display:flex;justify-content:space-between;align-items:center}
 a{color:#666} .turn{margin:16px 0} .who{font:12px -apple-system,system-ui,sans-serif;font-weight:700;letter-spacing:.05em}
 .SENIOR .who{color:#0b7285} .JUNIOR .who{color:#c2410c}
 .seg{font:11px -apple-system,system-ui,sans-serif;color:#999;text-transform:uppercase;margin-left:6px}
 .status{font:13px -apple-system,system-ui,sans-serif;color:#888;margin-top:20px}
</style></head><body>
<div class="top"><div><b>{{repo}}</b></div><div><a href="/">&larr; new</a></div></div>
<div id="script"></div>
<div class="status" id="status">starting (querying DeepWiki, then the two agents converse)…</div>
<script>
 const id="{{job_id}}"; let n=0;
 async function poll(){
   const r=await fetch(`/job/${id}`); const j=await r.json();
   const s=document.getElementById('script');
   for(;n<j.turns.length;n++){ const t=j.turns[n];
     const d=document.createElement('div'); d.className='turn '+t.speaker;
     const seg=(t.segment&&t.segment!=='dialogue')?`<span class="seg">${t.segment}</span>`:'';
     d.innerHTML=`<div class="who">${t.speaker}${seg}</div><div>${t.text.replace(/</g,'&lt;')}</div>`;
     s.appendChild(d); }
   const st=document.getElementById('status');
   if(j.status==='running'){ st.textContent=`generating… ${j.turns.length} turns so far`; setTimeout(poll,2000); }
   else if(j.status==='error'){ st.textContent='error: '+j.error; }
   else { st.textContent=`done — ${j.turns.length} turns. Saved to out/. (Render audio from the CLI.)`; }
 }
 poll();
</script></body></html>
"""


@app.get("/")
def index():
    presets = {
        "s": {n: {k: getattr(p, k) for k in STUDENT_SLIDERS} for n, p in STUDENT_PRESETS.items()},
        "t": {n: {k: getattr(p, k) for k in TEACHER_SLIDERS} for n, p in TEACHER_PRESETS.items()},
    }
    return render_template_string(
        INDEX,
        repo="botforge/GibsonEnvV2", minutes=6, starting_point=DEFAULT_STARTING_POINT,
        student_sliders=STUDENT_SLIDERS, teacher_sliders=TEACHER_SLIDERS,
        student={k: getattr(StudentPersona(), k) for k in STUDENT_SLIDERS},
        teacher={k: getattr(TeacherPersona(), k) for k in TEACHER_SLIDERS},
        student_presets=list(STUDENT_PRESETS), teacher_presets=list(TEACHER_PRESETS),
        presets_json=json.dumps(presets),
    )


@app.post("/generate")
def generate():
    f = request.form
    student = StudentPersona(**{k: float(f.get("s_" + k, 0.5)) for k in STUDENT_SLIDERS})
    teacher = TeacherPersona(**{k: float(f.get("t_" + k, 0.5)) for k in TEACHER_SLIDERS})
    episode = Episode(
        target_minutes=int(f.get("minutes", 6) or 6),
        tone=f.get("tone", "casual"),
        starting_point=(f.get("starting_point") or DEFAULT_STARTING_POINT).strip(),
    )
    cfg = PodcastConfig(repo=f.get("repo", "").strip(), student=student, teacher=teacher, episode=episode)
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {"status": "running", "turns": [], "repo": cfg.repo}
    threading.Thread(target=_run, args=(job_id, cfg), daemon=True).start()
    return redirect(url_for("view", job_id=job_id))


@app.get("/job/<job_id>")
def job(job_id):
    j = JOBS.get(job_id) or {}
    return jsonify(status=j.get("status"), turns=j.get("turns", []), error=j.get("error"))


@app.get("/view/<job_id>")
def view(job_id):
    j = JOBS.get(job_id)
    if not j:
        return "no such job", 404
    return render_template_string(VIEW, job_id=job_id, repo=j["repo"])


def main() -> int:
    print("dev-podcast studio -> http://127.0.0.1:5005")
    app.run(host="127.0.0.1", port=5005, debug=False)
    return 0


if __name__ == "__main__":
    main()
