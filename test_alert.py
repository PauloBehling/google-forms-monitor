# test_alert.py — Testa o som e o popup de alerta
import time
import threading
import winsound
import ctypes
from datetime import datetime, timezone, timedelta

changes = [
    'Nova pergunta adicionada: "PLACA DO VEICULO"',
    'Opcoes da pergunta "NOME COMPLETO" foram modificadas.',
]
title = "SMG15 - Contagem 2"


def _alert():
    # Beep de alerta
    for _ in range(3):
        winsound.Beep(1000, 300)
        time.sleep(0.15)

    # Popup nativo Windows
    MB_OK          = 0x00000000
    MB_ICONWARNING = 0x00000030
    MB_SYSTEMMODAL = 0x00001000
    flags = MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL

    body    = "\n".join(f"- {c}" for c in changes)
    message = (
        f"ALERTA: Alteracao detectada em:\n{title}\n\n"
        f"{body}\n\n"
        f"Detectado em: {datetime.now(timezone(timedelta(hours=-3))).strftime('%d/%m/%Y as %H:%M:%S')}"
    )
    ctypes.windll.user32.MessageBoxW(0, message, "Google Forms Monitor", flags)


t = threading.Thread(target=_alert)
t.start()
t.join()
print("Teste concluido!")
