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
        return json.load(f)


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


def submit_google_form(form_url: str, entry_id: int | str, value: str) -> bool:
    """Submete um formulário do Google com a resposta especificada."""
    try:
        response_url = form_url.replace("/viewform", "/formResponse")
        data = {
            f"entry.{entry_id}": value
        }
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")
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


def check_and_submit_form(cfg: dict, old_structure: dict | None, new_structure: dict, logger=None) -> str | None:
    """
    Verifica se a auto-submissão está habilitada e se o valor configurado
    existe nas novas opções e NÃO existia nas opções anteriores (ou se é o primeiro carregamento).
    Caso positivo, submete o formulário e retorna a mensagem de log correspondente.
    """
    if not cfg.get("auto_submit_enabled", False):
        return None

    target_value = cfg.get("auto_submit_value")
    if not target_value:
        return None

    # Verificar se o valor de auto-submissão está presente nas novas opções
    target_in_new = False
    found_question = None
    for q in new_structure.get("questions", []):
        if target_value in q.get("options", []):
            target_in_new = True
            found_question = q
            break

    if not target_in_new:
        if logger:
            logger.info(f"Filtro de auto-submissão: '{target_value}' não encontrado nas opções do formulário.")
        return None

    # Verificar se o valor já estava presente na estrutura antiga
    target_in_old = False
    if old_structure:
        for q in old_structure.get("questions", []):
            if target_value in q.get("options", []):
                target_in_old = True
                break

    # Se já existia e não é carregamento inicial, não submete novamente
    if target_in_old:
        if logger:
            logger.info(f"Filtro de auto-submissão: '{target_value}' já constava nas opções anteriormente.")
        return None

    # Encontrou pela primeira vez! Submeter o formulário
    form_url = cfg["form_url"]
    entry_id = found_question["id"]

    if logger:
        logger.warning(f"🚀 '{target_value}' encontrado na pergunta '{found_question['title']}'! Submetendo formulário...")

    success = submit_google_form(form_url, entry_id, target_value)

    if success:
        msg = f"⚡ Formulário submetido automaticamente para: {target_value} (Pergunta: {found_question['title']})"
        if logger:
            logger.warning(f"Sucesso: {msg}")
        return msg
    else:
        msg = f"❌ Falha ao submeter formulário automaticamente para: {target_value}"
        if logger:
            logger.error(msg)
        return msg
