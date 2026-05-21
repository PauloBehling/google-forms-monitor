"""
Funções compartilhadas: fetch, hash, estado e detecção de mudanças.
"""
import urllib.request
import urllib.parse
import re
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path


def get_now(config_path=None) -> datetime:
    """Retorna o datetime atual no fuso horário configurado."""
    try:
        cfg = load_config(config_path)
        offset = cfg.get("timezone_offset", -3)
    except Exception:
        offset = -3
    return datetime.now(timezone(timedelta(hours=offset)))



def load_config(config_path=None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    
    import os
    env_url = os.environ.get("FORM_URL") or os.environ.get("GOOGLE_FORM_URL")
    if env_url:
        cfg["form_url"] = env_url
    return cfg


def get_state_and_log_paths(cfg: dict, custom_url: str = None) -> tuple[str, str, str, str]:
    """
    Retorna os caminhos para: (state_file, changes_log_file, monitor_log_file, submissions_log_file)
    Se custom_url for diferente da URL padrão em config.json, adiciona um hash ao nome do arquivo
    para evitar colisões no monitoramento de múltiplos formulários.
    """
    default_url = cfg.get("form_url", "")
    url = custom_url if custom_url else default_url
    
    state_file = cfg.get("state_file", "form_state.json")
    changes_log = "changes_log.json"
    monitor_log = cfg.get("log_file", "monitor.log")
    submissions_log = "submissions_log.json"
    
    # Se custom_url for fornecido e for diferente do padrão, adiciona hash
    if url and url != default_url:
        h = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        
        p_state = Path(state_file)
        state_file = str(p_state.with_name(f"{p_state.stem}_{h}{p_state.suffix}"))
        
        p_changes = Path(changes_log)
        changes_log = str(p_changes.with_name(f"{p_changes.stem}_{h}{p_changes.suffix}"))
        
        p_monitor = Path(monitor_log)
        monitor_log = str(p_monitor.with_name(f"{p_monitor.stem}_{h}{p_monitor.suffix}"))
        
        p_submissions = Path(submissions_log)
        submissions_log = str(p_submissions.with_name(f"{p_submissions.stem}_{h}{p_submissions.suffix}"))
        
    return state_file, changes_log, monitor_log, submissions_log



def fetch_form_structure(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    except Exception as e:
        return {"error": str(e)}

    match = re.search(r"var FB_PUBLIC_LOAD_DATA_ = (\[.*?\]);\s*</script>", html, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    title       = data[3] if len(data) > 3 else ""
    description = data[1][0] if len(data) > 1 and data[1] else ""
    raw_qs      = data[1][1] if len(data) > 1 and len(data[1]) > 1 else []

    questions = []
    for q in raw_qs:
        try:
            qid = q[4][0][0]
        except (IndexError, TypeError):
            qid = q[1]
        questions.append({
            "id":       qid,
            "title":    q[1] if len(q) > 1 else "",
            "type":     q[3] if len(q) > 3 else None,
            "required": bool(q[7]) if len(q) > 7 else False,
            "options":  _extract_options(q),
        })

    return {
        "title":       title,
        "description": description,
        "questions":   questions,
        "fetched_at":  get_now().isoformat(),
    }


def _extract_options(q: list) -> list[str]:
    try:
        return [c[0] for c in q[4][0][1] if c]
    except (IndexError, TypeError):
        return []


def structure_hash(structure: dict) -> str:
    comparable = {k: v for k, v in structure.items() if k != "fetched_at"}
    return hashlib.sha256(
        json.dumps(comparable, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def load_state(state_file: str) -> dict | None:
    p = Path(state_file)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(state_file: str, structure: dict, digest: str) -> None:
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"hash": digest, "structure": structure}, f, indent=2, ensure_ascii=False)


def detect_changes(old: dict, new: dict) -> list[str]:
    changes = []
    if old.get("title") != new.get("title"):
        changes.append(f"📌 Título: '{old.get('title')}' → '{new.get('title')}'")
    if old.get("description") != new.get("description"):
        changes.append("📝 Descrição do formulário foi alterada.")

    old_qs = {q["id"]: q for q in old.get("questions", [])}
    new_qs = {q["id"]: q for q in new.get("questions", [])}

    for qid, q in new_qs.items():
        if qid not in old_qs:
            changes.append(f"➕ Nova pergunta: \"{q['title']}\"")
        else:
            oq = old_qs[qid]
            if oq["title"] != q["title"]:
                changes.append(f"✏️ Pergunta: '{oq['title']}' → '{q['title']}'")
            old_opts = set(oq.get("options", []))
            new_opts = set(q.get("options", []))
            if old_opts != new_opts:
                added   = new_opts - old_opts
                removed = old_opts - new_opts
                detail  = ""
                if added:   detail += f" +{len(added)} adicionadas"
                if removed: detail += f" -{len(removed)} removidas"
                changes.append(f"🔄 Opções de \"{q['title']}\" alteradas ({detail.strip()}).")
            if oq.get("required") != q.get("required"):
                s = "obrigatória" if q["required"] else "opcional"
                changes.append(f"⚠️ \"{q['title']}\" agora é {s}.")

    for qid, q in old_qs.items():
        if qid not in new_qs:
            changes.append(f"❌ Pergunta removida: \"{q['title']}\"")
    return changes


# ─── Histórico persistido ──────────────────────────────────────────
CHANGES_LOG = "changes_log.json"


def load_changes_log(log_file: str = CHANGES_LOG) -> list:
    p = Path(log_file)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_changes_log(entry: dict, log_file: str = CHANGES_LOG) -> None:
    log = load_changes_log(log_file)
    log.insert(0, entry)
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def submit_google_form(form_url: str, payload: dict) -> bool:
    """Submete um formulário do Google com o payload de respostas especificado."""
    try:
        response_url = form_url.replace("/viewform", "/formResponse")
        encoded_data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            response_url,
            data=encoded_data,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status == 200 or response.code == 200
    except Exception as e:
        if hasattr(e, "code") and e.code in [200, 302]:
            return True
        return False


def load_submissions_log(log_file: str = "submissions_log.json") -> list:
    """Carrega o histórico de submissões de formulários."""
    p = Path(log_file)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_submissions_log(entry: dict, log_file: str = "submissions_log.json") -> None:
    """Registra uma nova submissão no arquivo JSON de histórico."""
    log = load_submissions_log(log_file)
    log.insert(0, entry)
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def check_and_submit_form(cfg: dict, old_structure: dict | None, new_structure: dict, logger=None, submissions_log: str = "submissions_log.json") -> str | None:
    """
    Verifica se a auto-submissão está habilitada e se algum dos valores configurados em 
    auto_submit_mappings é recém-adicionado como opção nas perguntas do formulário.
    Caso positivo, realiza a submissão com todos os campos mapeados.
    """
    if not cfg.get("auto_submit_enabled", False):
        return None

    mappings = cfg.get("auto_submit_mappings", {})
    if not mappings:
        return None

    # Encontrar se algum valor mapeado foi recém-adicionado nas opções de alguma pergunta
    trigger_found = False
    trigger_question = None
    trigger_value = None

    for q in new_structure.get("questions", []):
        q_title = q.get("title", "")
        q_id = q.get("id")
        
        # Buscar se há um valor mapeado para esta pergunta
        target_value = mappings.get(q_title) or mappings.get(str(q_id))
        if not target_value:
            continue
            
        # Se a pergunta tiver opções, verificar se o valor mapeado está presente nelas
        options = q.get("options", [])
        if target_value in options:
            # Verificar se já estava na estrutura antiga
            already_in_old = False
            if old_structure:
                for old_q in old_structure.get("questions", []):
                    # Localizar a mesma pergunta por ID ou título
                    if old_q.get("id") == q_id or old_q.get("title") == q_title:
                        if target_value in old_q.get("options", []):
                            already_in_old = True
                            break
            
            # Se é a primeira vez que o valor mapeado aparece nas opções desta pergunta!
            if not already_in_old:
                trigger_found = True
                trigger_question = q
                trigger_value = target_value
                break

    if not trigger_found:
        if logger:
            logger.info("Filtro de auto-submissão: nenhum valor mapeado foi adicionado recentemente como opção.")
        return None

    # Montar o payload de submissão e os detalhes do payload amigável
    form_url = cfg["form_url"]
    payload = {}
    payload_details = {}
    
    for q in new_structure.get("questions", []):
        q_title = q.get("title", "")
        q_id = q.get("id")
        val = mappings.get(q_title) or mappings.get(str(q_id))
        if val is not None and val != "":
            payload[f"entry.{q_id}"] = val
            payload_details[q_title] = val

    if logger:
        logger.warning(f"🚀 '{trigger_value}' detectado no campo '{trigger_question['title']}'! Submetendo formulário com {len(payload)} campo(s)...")

    success = submit_google_form(form_url, payload)

    if success:
        msg = f"⚡ Formulário submetido automaticamente. Disparado por: '{trigger_value}' no campo '{trigger_question['title']}'"
        if logger:
            logger.warning(f"Sucesso: {msg}")
            
        # Salva o envio no log JSON de submissões
        save_submissions_log({
            "timestamp": get_now().isoformat(),
            "form_title": new_structure.get("title", ""),
            "trigger": f"Opção '{trigger_value}' adicionada no campo '{trigger_question['title']}'",
            "type": "Automático",
            "payload": payload_details
        }, submissions_log)
        
        return msg
    else:
        msg = f"❌ Falha ao submeter formulário automaticamente para o disparo de: '{trigger_value}'"
        if logger:
            logger.error(msg)
        return msg
