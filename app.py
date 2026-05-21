"""
Dashboard Streamlit — Google Forms Monitor
Executa: streamlit run app.py
"""
import time
import json
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
from pathlib import Path

from core import (
    load_config, fetch_form_structure, structure_hash,
    load_state, save_state, detect_changes,
    load_changes_log, save_changes_log, get_now,
    check_and_submit_form, get_state_and_log_paths,
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
STATE_FILE, LOG_FILE, _, SUBMISSIONS_LOG_FILE = get_state_and_log_paths(cfg, URL)
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
    st.session_state.last_check  = get_now().strftime("%d/%m/%Y %H:%M:%S")
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
        
        # Verificar e submeter formulário se o valor alvo for recém-adicionado
        submit_msg = check_and_submit_form(cfg, state["structure"], result, submissions_log=SUBMISSIONS_LOG_FILE)
        if submit_msg:
            changes.append(submit_msg)

        st.session_state.last_changes  = changes
        st.session_state.new_alert     = True
        st.session_state.change_count += len(changes)
        save_changes_log({
            "timestamp":  get_now().isoformat(),
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
    sidebar_state = load_state(STATE_FILE)
    form_title = sidebar_state["structure"]["title"] if sidebar_state and "structure" in sidebar_state else "Aguardando verificação..."
    st.markdown(f"<div style='color:#64ffda;font-weight:600;font-size:14px;background:#1a1f35;padding:12px;border-radius:10px;border:1px solid #2d3a5c;text-align:center;margin-bottom:12px;'>{form_title}</div>", unsafe_allow_html=True)
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

    st.markdown("---")
    with st.expander("⚙️ Ajustar Parâmetros", expanded=True):
        import os
        env_active = bool(os.environ.get("FORM_URL") or os.environ.get("GOOGLE_FORM_URL"))
        if env_active:
            st.warning("⚠️ A URL está sendo sobrescrita por uma variável de ambiente (FORM_URL/GOOGLE_FORM_URL).")
            
        new_url = st.text_input(
            "URL do Formulário",
            value=cfg.get("form_url", ""),
            placeholder="Ex: https://docs.google.com/forms/...",
            disabled=env_active,
            help="Link público do formulário do Google Forms a ser monitorado."
        )
        new_interval = st.number_input(
            "Intervalo (segundos)",
            min_value=5,
            max_value=3600,
            value=int(INTERVAL),
            step=5,
            help="Tempo de espera entre cada consulta ao formulário."
        )
        new_auto_submit = st.checkbox(
            "Habilitar Envio Automático",
            value=cfg.get("auto_submit_enabled", False),
            help="Ativa o preenchimento e envio automático do formulário se qualquer um dos valores parametrizados for adicionado às opções."
        )
        
        # Campo para parametrização dos novos/outros campos do forms
        st.markdown("---")
        st.markdown("📝 **Parametrização dos Campos**")
        state = load_state(STATE_FILE)
        new_mappings = {}
        if state and "structure" in state and "questions" in state["structure"]:
            current_mappings = cfg.get("auto_submit_mappings", {})
            for q in state["structure"]["questions"]:
                q_title = q.get("title", "")
                q_id = q.get("id")
                q_val = current_mappings.get(q_title) or current_mappings.get(str(q_id), "")
                
                # Exibir um input de texto para cada pergunta cadastrada
                new_mappings[q_title] = st.text_input(
                    f"Resposta para '{q_title}'",
                    value=q_val,
                    key=f"map_{q_id}",
                    help=f"Valor opcional para preencher o campo '{q_title}' na submissão automática."
                )
            # Botão para submissão manual forçada
            st.markdown("---")
            if st.button("🚀 Forçar Submissão Manual", use_container_width=True, help="Submete o formulário imediatamente com os valores preenchidos acima."):
                # Recarregar config do disco para capturar edições manuais feitas no arquivo
                try:
                    fresh_cfg = load_config()
                except Exception:
                    fresh_cfg = cfg
                    
                active_mappings = fresh_cfg.get("auto_submit_mappings", {})
                payload = {}
                payload_details = {}
                for q in state["structure"]["questions"]:
                    q_title = q.get("title", "")
                    q_id = q.get("id")
                    
                    # Apenas submete se o campo estiver configurado com um valor válido na configuração ativa
                    cfg_val = active_mappings.get(q_title) or active_mappings.get(str(q_id))
                    if cfg_val is not None and str(cfg_val).strip() != "":
                        val = new_mappings.get(q_title)
                        if val is not None and str(val).strip() != "":
                            payload[f"entry.{q_id}"] = val
                            payload_details[q_title] = val
                
                if not payload:
                    st.warning("⚠️ Nenhum campo configurado e preenchido para submissão.")
                else:
                    with st.spinner("Enviando formulário..."):
                        from core import submit_google_form
                        success = submit_google_form(URL, payload)
                    if success:
                        st.success("⚡ Formulário submetido com sucesso!")
                        from core import save_submissions_log
                        save_submissions_log({
                            "timestamp": get_now().isoformat(),
                            "form_title": state["structure"].get("title", ""),
                            "trigger": "Submissão manual via botão",
                            "type": "Manual",
                            "payload": payload_details
                        }, SUBMISSIONS_LOG_FILE)
                    else:
                        st.error("❌ Falha ao submeter o formulário.")
        else:
            st.info("💡 A estrutura do formulário ainda não foi carregada. Salve a URL e clique em 'Verificar Agora' para habilitar a parametrização por campo.")

        if st.button("💾 Salvar Parâmetros", use_container_width=True):
            if not env_active:
                cfg["form_url"] = new_url
            cfg["check_interval_seconds"] = new_interval
            cfg["auto_submit_enabled"] = new_auto_submit
            cfg.pop("auto_submit_value", None)  # Remover campo obsoleto
            
            # Salvar apenas mapeamentos com valores não vazios
            clean_mappings = {}
            if new_mappings:
                for k, v in new_mappings.items():
                    if v is not None and str(v).strip() != "":
                        clean_mappings[k] = v
            cfg["auto_submit_mappings"] = clean_mappings
            try:
                config_path = Path(__file__).parent / "config.json"
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                st.success("Configurações salvas!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")


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
    tab1, tab2, tab3 = st.tabs(["📋 Estrutura Atual", "📜 Histórico de Alterações", "🚀 Envios Realizados"])

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

    # ── Aba 3: Envios Realizados ────────────────────────────────
    with tab3:
        from core import load_submissions_log
        sub_log = load_submissions_log(SUBMISSIONS_LOG_FILE)
        if not sub_log:
            st.info("🟢 Nenhum envio de dados registrado até o momento.")
        else:
            st.markdown(f"**{len(sub_log)} envio(s) realizado(s):**")
            for entry in sub_log:
                ts = entry.get("timestamp", "")[:16].replace("T", " ")
                trigger = entry.get("trigger", "")
                stype = entry.get("type", "Automático")
                badge = "⚡ Automático" if stype == "Automático" else "👤 Manual"
                
                # Exibir com visual elegante de expansor
                with st.expander(f"🕐 {ts} &nbsp;|&nbsp; {badge} &nbsp;|&nbsp; {trigger}", expanded=False):
                    payload = entry.get("payload", {})
                    if payload:
                        for k, v in payload.items():
                            st.markdown(f"**{k}**: `{v}`")
                    else:
                        st.info("Nenhum dado imputado.")


# ─── Auto-rerun a cada 1s para countdown ─────────────────────
time.sleep(1)
st.rerun()
