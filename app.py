"""
Dashboard Streamlit — Google Forms Monitor
Executa: streamlit run app.py
"""
import time
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
from pathlib import Path

from core import (
    load_config, fetch_form_structure, structure_hash,
    load_state, save_state, detect_changes,
    load_changes_log, save_changes_log,
)

# ─── Página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Google Forms Monitor",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.metric-card {
    background: linear-gradient(135deg,#1a1f35 0%,#1e2540 100%);
    border: 1px solid #2d3a5c;
    border-radius: 14px;
    padding: 22px 18px;
    text-align: center;
    margin-bottom: 8px;
}
.metric-label { color:#7f8fb0; font-size:11px; font-weight:700;
    text-transform:uppercase; letter-spacing:1.2px; margin-bottom:6px; }
.metric-value { color:#ccd6f6; font-size:30px; font-weight:700; }
.metric-sub   { color:#64ffda; font-size:13px; margin-top:4px; }

.alert-box {
    background: linear-gradient(135deg,#7b0000,#c0392b);
    border-radius: 12px; padding: 16px 22px; color:#fff;
    font-weight:600; font-size:15px; margin-bottom:16px;
    border-left: 4px solid #ff6b6b;
    animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.82} }

.change-item {
    background:#1a1f35; border-left:3px solid #e74c3c;
    border-radius:0 8px 8px 0; padding:10px 16px;
    margin-bottom:7px; color:#ccd6f6; font-size:14px;
}
.question-card {
    background:#1a1f35; border:1px solid #2d3a5c;
    border-radius:10px; padding:16px 18px; margin-bottom:12px;
}
.q-title  { color:#64ffda; font-weight:600; font-size:15px; margin-bottom:6px; }
.q-badge  { background:#252b3b; border:1px solid #3a4a6a; border-radius:20px;
    padding:3px 11px; display:inline-block; margin:3px;
    font-size:12px; color:#8892b0; }
.history-row {
    background:#1a1f35; border-radius:8px; padding:14px 18px;
    margin-bottom:10px; border-left:3px solid #6c63ff;
}
.hist-ts { color:#7f8fb0; font-size:12px; margin-bottom:6px; }
.hist-change { color:#ccd6f6; font-size:13px; margin:2px 0; }
.status-dot-ok  { display:inline-block; width:10px; height:10px;
    background:#64ffda; border-radius:50%; margin-right:6px; }
.status-dot-err { display:inline-block; width:10px; height:10px;
    background:#e74c3c; border-radius:50%; margin-right:6px; }
div[data-testid="stSidebar"] { background:#13151f; border-right:1px solid #2d3a5c; }
</style>
""", unsafe_allow_html=True)

# ─── Session state ────────────────────────────────────────────
for k, v in {
    "next_check":   0.0,
    "last_check":   None,
    "last_changes": [],
    "new_alert":    False,
    "check_count":  0,
    "change_count": 0,
    "last_error":   None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─── Carregar config ──────────────────────────────────────────
try:
    cfg = load_config()
except Exception as e:
    st.error(f"Erro ao carregar config.json: {e}")
    st.stop()

URL        = cfg["form_url"]
STATE_FILE = cfg.get("state_file", "form_state.json")
LOG_FILE   = "changes_log.json"
INTERVAL   = cfg.get("check_interval_seconds", 300)

# ─── Beep via Web Audio API ───────────────────────────────────
def play_alert_sound():
    components.html("""<script>
    (function(){
        const ctx = new (window.AudioContext||window.webkitAudioContext)();
        function beep(f,s,d){
            const o=ctx.createOscillator(), g=ctx.createGain();
            o.connect(g); g.connect(ctx.destination);
            o.frequency.setValueAtTime(f, ctx.currentTime+s);
            g.setValueAtTime(0.35, ctx.currentTime+s);
            g.exponentialRampToValueAtTime(0.001, ctx.currentTime+s+d);
            o.start(ctx.currentTime+s); o.stop(ctx.currentTime+s+d);
        }
        beep(880,0,.25); beep(1100,.3,.25); beep(880,.6,.35);
    })();
    </script>""", height=0)

# ─── Executar verificação ─────────────────────────────────────
def do_check():
    st.session_state.new_alert    = False
    st.session_state.last_changes = []
    st.session_state.last_error   = None

    result = fetch_form_structure(URL)
    st.session_state.last_check  = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    st.session_state.check_count += 1

    if result is None:
        st.session_state.last_error = "Não foi possível extrair a estrutura do formulário."
        return
    if "error" in result:
        st.session_state.last_error = result["error"]
        return

    new_hash = structure_hash(result)
    state    = load_state(STATE_FILE)

    if state is None:
        save_state(STATE_FILE, result, new_hash)
    elif state["hash"] != new_hash:
        changes = detect_changes(state["structure"], result)
        st.session_state.last_changes  = changes
        st.session_state.new_alert     = True
        st.session_state.change_count += len(changes)
        save_changes_log({
            "timestamp":  datetime.now().isoformat(),
            "form_title": result["title"],
            "changes":    changes,
        }, LOG_FILE)
        save_state(STATE_FILE, result, new_hash)

# ─── Auto-verificação ─────────────────────────────────────────
if time.time() >= st.session_state.next_check:
    do_check()
    st.session_state.next_check = time.time() + INTERVAL

# ─── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔍 Forms Monitor")
    st.markdown("---")
    st.markdown("**Formulário monitorado:**")
    short_url = URL[36:70] + "..." if len(URL) > 70 else URL
    st.code(short_url, language=None)
    st.markdown(f"**Intervalo:** `{INTERVAL}s`")
    st.markdown("---")

    if st.button("🔄 Verificar Agora", use_container_width=True, type="primary"):
        with st.spinner("Consultando formulário..."):
            do_check()
        st.session_state.next_check = time.time() + INTERVAL
        st.rerun()

    st.markdown("---")
    remaining = max(0, int(st.session_state.next_check - time.time()))
    st.markdown(
        f"<div style='color:#7f8fb0;font-size:13px;text-align:center'>"
        f"⏱️ Próxima verificação em <b style='color:#64ffda'>{remaining}s</b></div>",
        unsafe_allow_html=True,
    )
    if st.session_state.last_check:
        st.markdown(
            f"<div style='color:#7f8fb0;font-size:12px;text-align:center;margin-top:4px'>"
            f"Última: {st.session_state.last_check}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("---")
    c1, c2 = st.columns(2)
    c1.metric("Verificações", st.session_state.check_count)
    c2.metric("Alterações",   st.session_state.change_count)

# ─── Header ───────────────────────────────────────────────────
st.markdown("# 🔍 Google Forms Monitor")
st.markdown("Monitoramento automático de alterações na estrutura do formulário.")

# ─── Alerta de mudança ────────────────────────────────────────
if st.session_state.new_alert and st.session_state.last_changes:
    play_alert_sound()
    preview = " &nbsp;|&nbsp; ".join(st.session_state.last_changes[:2])
    extra   = f" (+{len(st.session_state.last_changes)-2} mais)" if len(st.session_state.last_changes) > 2 else ""
    st.markdown(
        f'<div class="alert-box">🚨 ALTERAÇÃO DETECTADA! &nbsp; {preview}{extra}</div>',
        unsafe_allow_html=True,
    )

if st.session_state.last_error:
    st.error(f"⚠️ Erro: {st.session_state.last_error}")

# ─── Conteúdo principal ───────────────────────────────────────
state = load_state(STATE_FILE)
TYPES = {1:"Texto curto", 2:"Lista suspensa", 3:"Múltipla escolha",
         4:"Caixas de seleção", 5:"Escala linear", 9:"Data", 10:"Hora"}

if state is None:
    st.info("⚡ Aguardando a primeira verificação. Clique em **Verificar Agora** na barra lateral.")
else:
    s = state["structure"]
    tab1, tab2 = st.tabs(["📋 Estrutura Atual", "📜 Histórico de Alterações"])

    # ── Aba 1: Estrutura ──────────────────────────────────────
    with tab1:
        c1, c2, c3 = st.columns(3)
        last_fetch = s.get("fetched_at", "")[:16].replace("T", " ")
        c1.markdown(f'<div class="metric-card"><div class="metric-label">Formulário</div>'
                    f'<div class="metric-value" style="font-size:17px">{s["title"]}</div></div>',
                    unsafe_allow_html=True)
        c2.markdown(f'<div class="metric-card"><div class="metric-label">Perguntas</div>'
                    f'<div class="metric-value">{len(s["questions"])}</div></div>',
                    unsafe_allow_html=True)
        c3.markdown(f'<div class="metric-card"><div class="metric-label">Capturado em</div>'
                    f'<div class="metric-value" style="font-size:16px">{last_fetch}</div></div>',
                    unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if s.get("description"):
            with st.expander("📝 Descrição do formulário"):
                st.text(s["description"])

        st.markdown("### ❓ Perguntas")
        for i, q in enumerate(s["questions"], 1):
            type_lbl = TYPES.get(q.get("type"), f"Tipo {q.get('type')}")
            req_lbl  = "✅ Obrigatória" if q.get("required") else "⬜ Opcional"
            st.markdown(
                f'<div class="question-card">'
                f'<div class="q-title">#{i} — {q["title"]}</div>'
                f'<small style="color:#7f8fb0">{type_lbl} &nbsp;|&nbsp; {req_lbl}</small>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if q.get("options"):
                badges = "".join(f'<span class="q-badge">{o}</span>' for o in q["options"])
                st.markdown(badges, unsafe_allow_html=True)

    # ── Aba 2: Histórico ──────────────────────────────────────
    with tab2:
        log = load_changes_log(LOG_FILE)
        if not log:
            st.success("🟢 Nenhuma alteração registrada até o momento.")
        else:
            st.markdown(f"**{len(log)} evento(s) registrado(s):**")
            for entry in log:
                ts    = entry.get("timestamp", "")[:16].replace("T", " ")
                title = entry.get("form_title", "")
                chgs  = entry.get("changes", [])
                chgs_html = "".join(f'<div class="hist-change">• {c}</div>' for c in chgs)
                st.markdown(
                    f'<div class="history-row">'
                    f'<div class="hist-ts">🕐 {ts} &nbsp;|&nbsp; {title}</div>'
                    f'{chgs_html}</div>',
                    unsafe_allow_html=True,
                )

# ─── Auto-rerun a cada 1s para countdown ─────────────────────
time.sleep(1)
st.rerun()
