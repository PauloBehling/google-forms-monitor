"""
=============================================================
  Google Forms Monitor — Monitoramento de Alterações
  Autor: Antigravity
  Descrição: Monitora alterações na estrutura (título,
             descrição e perguntas) de um Google Forms
             público e envia alertas por e-mail.
=============================================================
"""

import urllib.request
import re
import json
import time
import hashlib
import smtplib
import logging
import os
import threading
import winsound
import ctypes
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ─── Carregar configurações ────────────────────────────────
def load_config() -> dict:
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

# ─── Logging ───────────────────────────────────────────────
def setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("forms_monitor")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    # Console com encoding UTF-8 (corrige acentos no Windows)
    import sys
    ch = logging.StreamHandler(stream=open(
        sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1,
        closefd=False
    ))
    ch.setFormatter(fmt)
    # Arquivo
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger

# ─── Scraping do formulário ────────────────────────────────
def fetch_form_structure(url: str) -> dict | None:
    """
    Faz download do HTML do Google Forms e extrai
    a estrutura: título, descrição e lista de perguntas.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    except Exception as e:
        return {"error": str(e)}

    match = re.search(
        r"var FB_PUBLIC_LOAD_DATA_ = (\[.*?\]);\s*</script>",
        html,
        re.DOTALL
    )
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
        # O ID único da pergunta fica em q[4][0][0] (número inteiro)
        try:
            question_id = q[4][0][0]
        except (IndexError, TypeError):
            question_id = q[1]  # fallback: usa o título como chave
        questions.append({
            "id":       question_id,
            "title":    q[1] if len(q) > 1 else "",
            "type":     q[3] if len(q) > 3 else None,
            "required": bool(q[7]) if len(q) > 7 else False,
            "options":  _extract_options(q),
        })

    return {
        "title":       title,
        "description": description,
        "questions":   questions,
        "fetched_at":  datetime.now().isoformat(),
    }


def _extract_options(q: list) -> list[str]:
    """Extrai opções de múltipla escolha / checkbox, se houver."""
    try:
        choices = q[4][0][1]        # localização típica das opções
        return [c[0] for c in choices if c]
    except (IndexError, TypeError):
        return []


def structure_hash(structure: dict) -> str:
    """Gera um hash determinístico da estrutura (ignora fetched_at)."""
    comparable = {k: v for k, v in structure.items() if k != "fetched_at"}
    raw = json.dumps(comparable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()

# ─── Estado persistido ─────────────────────────────────────
def load_state(state_file: str) -> dict | None:
    path = Path(state_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(state_file: str, structure: dict, digest: str) -> None:
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    payload = {"hash": digest, "structure": structure}
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

# ─── Detecção de diferenças ────────────────────────────────
def detect_changes(old: dict, new: dict) -> list[str]:
    """Retorna lista de descrições das mudanças encontradas."""
    changes = []

    if old.get("title") != new.get("title"):
        changes.append(f"📌 Título alterado:\n   Antes: {old.get('title')}\n   Depois: {new.get('title')}")

    if old.get("description") != new.get("description"):
        changes.append("📝 Descrição do formulário foi alterada.")

    old_qs = {q["id"]: q for q in old.get("questions", [])}
    new_qs = {q["id"]: q for q in new.get("questions", [])}

    for qid, q in new_qs.items():
        if qid not in old_qs:
            changes.append(f"➕ Nova pergunta adicionada: \"{q['title']}\"")
        else:
            oq = old_qs[qid]
            if oq["title"] != q["title"]:
                changes.append(f"✏️  Pergunta alterada:\n   Antes: \"{oq['title']}\"\n   Depois: \"{q['title']}\"")
            if set(oq.get("options", [])) != set(q.get("options", [])):
                changes.append(f"🔄 Opções da pergunta \"{q['title']}\" foram modificadas.")
            if oq.get("required") != q.get("required"):
                status = "obrigatória" if q["required"] else "opcional"
                changes.append(f"⚠️  Pergunta \"{q['title']}\" agora é {status}.")

    for qid, q in old_qs.items():
        if qid not in new_qs:
            changes.append(f"❌ Pergunta removida: \"{q['title']}\"")

    return changes

# ─── Alerta sonoro + Popup nativo do Windows ─────────────
def notify_alert(title: str, changes: list[str]) -> None:
    """
    Toca um beep de alerta e exibe um popup nativo do Windows.
    Executado em thread separada para não bloquear o loop.
    """
    def _alert():
        # ── Som: 3 bipes de alerta ──────────────────────────
        for _ in range(3):
            winsound.Beep(1000, 300)   # frequência 1000 Hz, 300 ms
            time.sleep(0.15)

        # ── Popup nativo Windows (MessageBox) ───────────────
        MB_OK              = 0x00000000
        MB_ICONWARNING     = 0x00000030
        MB_SYSTEMMODAL     = 0x00001000   # fica por cima de outras janelas
        flags = MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL

        body = "\n".join(f"• {c}" for c in changes)
        message = (
            f"🚨 Alteração detectada em:\n{title}\n\n"
            f"{body}\n\n"
            f"Detectado em: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}"
        )
        ctypes.windll.user32.MessageBoxW(0, message, "⚠️ Google Forms Monitor", flags)

    threading.Thread(target=_alert, daemon=True).start()


# ─── Notificação por e-mail ────────────────────────────────
def send_email(cfg: dict, subject: str, body: str, logger: logging.Logger) -> bool:
    em_cfg = cfg.get("email", {})
    if not em_cfg.get("enabled", False):
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = em_cfg["from"]
        msg["To"]      = ", ".join(em_cfg["to"])
        msg["Subject"] = subject

        # Corpo texto plano
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Corpo HTML formatado
        html_body = body.replace("\n", "<br>")
        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333">
            <h2 style="color:#d9534f">🔔 Google Forms Monitor</h2>
            <p>{html_body}</p>
            <hr>
            <small style="color:#999">Mensagem automática gerada em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</small>
        </body></html>"""
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(em_cfg["smtp_host"], em_cfg["smtp_port"]) as server:
            server.starttls()
            server.login(em_cfg["smtp_user"], em_cfg["smtp_password"])
            server.sendmail(em_cfg["from"], em_cfg["to"], msg.as_string())

        logger.info("E-mail de alerta enviado com sucesso.")
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar e-mail: {e}")
        return False

# ─── Loop principal ────────────────────────────────────────
def run():
    cfg        = load_config()
    logger     = setup_logging(cfg.get("log_file", "monitor.log"))
    url        = cfg["form_url"]
    state_file = cfg.get("state_file", "form_state.json")
    interval   = cfg.get("check_interval_seconds", 300)

    logger.info("=" * 55)
    logger.info("  Google Forms Monitor iniciado")
    logger.info(f"  URL: {url}")
    logger.info(f"  Intervalo de verificação: {interval}s")
    logger.info("=" * 55)

    while True:
        logger.info("Verificando formulário...")
        new_structure = fetch_form_structure(url)

        if new_structure is None:
            logger.warning("Não foi possível extrair a estrutura do formulário.")
        elif "error" in new_structure:
            logger.error(f"Erro ao acessar o formulário: {new_structure['error']}")
        else:
            new_hash = structure_hash(new_structure)
            state    = load_state(state_file)

            if state is None:
                # Primeira execução — salva estado inicial
                save_state(state_file, new_structure, new_hash)
                logger.info(f"Estado inicial salvo. Título: \"{new_structure['title']}\" | Perguntas: {len(new_structure['questions'])}")
            elif state["hash"] != new_hash:
                # Mudança detectada!
                changes = detect_changes(state["structure"], new_structure)
                logger.warning(f"🚨 ALTERAÇÃO DETECTADA! {len(changes)} mudança(s) encontrada(s).")

                body = (
                    f"Alterações detectadas no formulário:\n"
                    f"{new_structure['title']}\n"
                    f"URL: {url}\n\n"
                    + "\n\n".join(changes)
                    + f"\n\nDetectado em: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}"
                )
                for c in changes:
                    logger.warning(f"  → {c}")

                notify_alert(new_structure["title"], changes)
                send_email(cfg, f"[ALERTA] Formulário alterado: {new_structure['title']}", body, logger)
                save_state(state_file, new_structure, new_hash)
            else:
                logger.info("Nenhuma alteração detectada.")

        logger.info(f"Próxima verificação em {interval}s.\n")
        time.sleep(interval)


if __name__ == "__main__":
    run()
