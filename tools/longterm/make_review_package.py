"""Blind human review package: one self-contained HTML app per role. No model readings, no splits, no suggested answers.

FIRST reviewer: every candidate. SECOND reviewer: VALIDATION candidates only, a different shuffled order, and never the first answers.
Each app exports a pid-corpus-review-v1 JSON that tools/longterm/adjudicate.py consumes. A person must type their own name; the
generator never fills one in and nothing here records an AI as a reviewer.
"""
import argparse
import base64
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pid_reader.engineering.longterm import corpus as C  # noqa: E402

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>P&ID blind transcription - __ROLE__</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{font-family:system-ui,Segoe UI,Arial;margin:0;background:#f4f5f7;color:#1b1f24}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #c8ccd2;padding:10px 16px;z-index:5;display:flex;gap:14px;flex-wrap:wrap;align-items:center}
main{max-width:1100px;margin:0 auto;padding:12px 16px 80px}
.card{background:#fff;border:1px solid #c8ccd2;border-radius:8px;margin:14px 0;padding:12px}
.card.done{border-color:#2e7d32}.imgs{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start}
.crop{background:#fff;border:2px solid #1b1f24;padding:4px}.crop img{image-rendering:pixelated;display:block;transform-origin:top left}
.ctx img{max-width:520px;border:1px solid #c8ccd2}
input[type=text]{font:18px/1.2 Consolas,monospace;width:100%;max-width:640px;padding:6px}
label{margin-right:14px}.hint{color:#555;font-size:13px}button{padding:6px 12px;font-size:14px}
.warn{color:#b00020}
</style></head><body>
<header><b>Blind transcription (__ROLE__)</b>
<label>Your full name <input id="who" type="text" style="width:220px;font:14px system-ui" placeholder="required"></label>
<span id="prog"></span><button onclick="exp()">Export my review (JSON)</button><button onclick="document.getElementById('imp').click()">Import saved progress</button>
<input id="imp" type="file" accept=".json" style="display:none" onchange="imp(event)"></header>
<main>
<div class="card"><b>How to transcribe.</b> The red box in the context picture marks the region; the enlarged crop is what to read.
Type exactly the printed characters, <b>including case, dots, dashes and tildes</b>. Do not correct, tidy or complete anything. Do not add spaces that are not printed;
for two printed lines type them in reading order separated by one space. Choose <b>Unreadable</b> when you cannot tell a character
(do not guess) and <b>Not text</b> when the region holds no text. The rotate button is for viewing only. Work from the pixels, not from memory
of other drawings. You will not see any machine reading.<p class="hint">Progress is saved in this browser automatically.</p></div>
<div id="list"></div></main>
<script>
const ITEMS=__ITEMS__,ROLE="__ROLE__",KEY="pidreview-__KEY__";
let S={};try{S=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}}
function upd(){let n=0;for(const i of ITEMS){if(S[i.id]&&S[i.id].state&&(S[i.id].state!="READABLE"||S[i.id].text))n++}document.getElementById("prog").textContent=n+" / "+ITEMS.length+" done";return n}
function draw(){const L=document.getElementById("list");L.innerHTML="";ITEMS.forEach((it,k)=>{const s=S[it.id]||{};const d=document.createElement("div");d.className="card"+((s.state&&(s.state!="READABLE"||s.text))?" done":"");d.id="c"+it.id;
d.innerHTML=`<div><b>#${k+1}</b> <span class="hint">${it.category.replace(/_/g," ").toLowerCase()}</span></div><div class="imgs"><div class="crop"><img id="im${it.id}" src="${it.crop}" style="transform:scale(${s.zoom||3})"></div><div class="ctx"><img src="${it.ctx}"></div></div>
<p><label>Zoom <input type="range" min="1" max="8" step=".5" value="${s.zoom||3}" oninput="zoom('${it.id}',this.value)"></label><button onclick="rot('${it.id}')">Rotate view 90&deg;</button></p>
<p><label><input type="radio" name="r${it.id}" value="READABLE" ${s.state=="READABLE"?"checked":""} onchange="st('${it.id}','READABLE')"> Readable</label>
<label><input type="radio" name="r${it.id}" value="UNREADABLE" ${s.state=="UNREADABLE"?"checked":""} onchange="st('${it.id}','UNREADABLE')"> Unreadable</label>
<label><input type="radio" name="r${it.id}" value="NOT_TEXT" ${s.state=="NOT_TEXT"?"checked":""} onchange="st('${it.id}','NOT_TEXT')"> Not text</label></p>
${it.v?`<p><b>Reading direction</b> (this text is vertical): <label><input type="radio" name="o${it.id}" value="ROTATE_CW" ${s.orientation=="ROTATE_CW"?"checked":""} onchange="og('${it.id}','ROTATE_CW')"> reads bottom-to-top (turn the picture clockwise)</label> <label><input type="radio" name="o${it.id}" value="ROTATE_CCW" ${s.orientation=="ROTATE_CCW"?"checked":""} onchange="og('${it.id}','ROTATE_CCW')"> reads top-to-bottom (turn it anticlockwise)</label> <label><input type="radio" name="o${it.id}" value="UPRIGHT" ${s.orientation=="UPRIGHT"?"checked":""} onchange="og('${it.id}','UPRIGHT')"> already horizontal</label></p>`:""}
<p><input type="text" id="t${it.id}" placeholder="exact printed text" value="${(s.text||"").replace(/"/g,"&quot;")}" oninput="tx('${it.id}',this.value)" autocomplete="off" spellcheck="false"></p>
<p><input type="text" id="n${it.id}" placeholder="note (optional, e.g. partly cut off)" value="${(s.note||"").replace(/"/g,"&quot;")}" oninput="nt('${it.id}',this.value)" style="font:13px system-ui"></p>`;L.appendChild(d)});upd()}
function g(id){S[id]=S[id]||{};return S[id]}
function og(id,v){g(id).orientation=v;save()}function st(id,v){g(id).state=v;save();mark(id)}function tx(id,v){const o=g(id);o.text=v;if(v&&!o.state){o.state="READABLE";const r=document.querySelector(`input[name=r${id}][value=READABLE]`);if(r)r.checked=true}save();mark(id)}
function nt(id,v){g(id).note=v;save()}function zoom(id,v){g(id).zoom=+v;document.getElementById("im"+id).style.transform=`scale(${v})`;save()}
function rot(id){const o=g(id);o.rot=((o.rot||0)+90)%360;const im=document.getElementById("im"+id);im.style.transform=`rotate(${o.rot}deg) scale(${o.zoom||3})`;save()}
function mark(id){const s=S[id]||{};document.getElementById("c"+id).className="card"+((s.state&&(s.state!="READABLE"||s.text))?" done":"");upd()}
const BAD=/\b(claude|gpt|chatgpt|openai|anthropic|assistant|copilot|gemini|llm|bot|ocr|rapidocr|easyocr|trocr|model|auto|script|ai)\b/i;
function exp(){const who=document.getElementById("who").value.trim();if(who.length<3||BAD.test(who)){alert("Type your own full name (a named person) before exporting.");return}
const out={schema:"pid-corpus-review-v1",reviewer:who,role:ROLE,created_utc:new Date().toISOString(),items:{}};let miss=0;
for(const i of ITEMS){const s=S[i.id];if(!s||!s.state||(s.state=="READABLE"&&!s.text)){miss++;continue}if(i.v&&s.state=="READABLE"&&!s.orientation){miss++;continue}out.items[i.id]={state:s.state,text:s.state=="READABLE"?s.text:undefined,orientation:i.v?s.orientation:undefined,note:s.note||undefined}}
if(miss&&!confirm(miss+" items have no answer yet and will be exported as not reviewed. Export anyway?"))return;
const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:"application/json"}));a.download="review_"+ROLE+"_"+who.replace(/\W+/g,"_")+".json";a.click()}
function imp(ev){const f=ev.target.files[0];if(!f)return;const r=new FileReader();r.onload=()=>{try{const o=JSON.parse(r.result);if(o.items){for(const k in o.items){S[k]=Object.assign({},S[k],o.items[k])}save();draw()}}catch(e){alert("Not a review file")}};r.readAsText(f)}
draw();
</script></body></html>"""


# Neutral display labels: the internal category of an abstention candidate ("unreadable candidate") would hint at the answer.
DISPLAY = dict(LINE_LABEL="line label", BUBBLE_CODE="instrument bubble, upper part", BUBBLE_NUMBER="instrument bubble, lower part", VERTICAL="vertical text",
               TITLE_BLOCK="title block", EASY_CONTROL="text", NON_TEXT_CANDIDATE="region", UNREADABLE_CANDIDATE="region")


def data_uri(path, jpeg=False):
    from PIL import Image
    buf = io.BytesIO()
    with Image.open(path) as im:
        if jpeg:
            im.convert("RGB").save(buf, "JPEG", quality=82)
            mime = "image/jpeg"
        else:
            im.save(buf, "PNG")
            mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def build(candidates_path, out_dir, seed="review-v1"):
    root = Path(candidates_path).parent
    doc = json.loads(Path(candidates_path).read_text(encoding="utf8"))
    problems = C.validate_candidates(doc, root=root)
    if problems:
        raise SystemExit("candidates are inconsistent:\n" + "\n".join(problems[:20]))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    made = {}
    for role, pick in (("FIRST", lambda it: True), ("SECOND", lambda it: it["split"] == "VALIDATION")):
        items = [it for it in doc["items"] if pick(it)]
        items.sort(key=lambda it: hashlib.sha256((seed + role + it["id"]).encode()).hexdigest())
        payload = [dict(id=it["id"], category=DISPLAY.get(it["category"], "region"), v=bool(it.get("is_vertical")), crop=data_uri(root / it["crop_path"]), ctx=data_uri(root / "context" / (it["id"] + ".png"), jpeg=True)) for it in items]
        html = HTML.replace("__ITEMS__", json.dumps(payload)).replace("__ROLE__", role).replace("__KEY__", hashlib.sha256((seed + role + doc.get("seed", "")).encode()).hexdigest()[:12])
        (out / f"review_{role}.html").write_text(html, encoding="utf8")
        made[role] = len(items)
    (out / "README_FOR_REVIEWERS.md").write_text(
        "# Blind transcription package\n\nOpen `review_FIRST.html` (first reviewer: all items) or `review_SECOND.html` (second reviewer: validation items only) in a browser.\n"
        "Type your own name, transcribe each region exactly as printed from the pixels, then **Export my review**. Send back only the exported JSON.\n"
        "The second reviewer must be a different person and must not see the first reviewer's answers. Disagreements go to adjudication against the source pixels.\n"
        "No machine readings, splits, families or drawing identities are shown.\n", encoding="utf8")
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(build(a.candidates, a.out)))


if __name__ == "__main__":
    main()
