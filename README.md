# 🔍 Google Forms Monitor

Aplicação Python para monitorar alterações na **estrutura** de formulários públicos do Google Forms.

## O que é monitorado

| Item | Descrição |
|---|---|
| 📌 Título | Detecta alteração no nome do formulário |
| 📝 Descrição | Detecta alteração no texto de descrição |
| ➕ Nova pergunta | Alerta quando uma pergunta é adicionada |
| ❌ Pergunta removida | Alerta quando uma pergunta é deletada |
| ✏️ Texto alterado | Alerta quando o enunciado de uma pergunta muda |
| 🔄 Opções alteradas | Detecta mudanças nas alternativas (múltipla escolha, etc.) |
| ⚠️ Obrigatoriedade | Detecta se uma pergunta passou a ser obrigatória ou não |

---

## 📁 Estrutura do Projeto

```
google-forms-monitor/
├── monitor.py        ← Script principal
├── config.json       ← Configurações (URL, e-mail, intervalo)
├── form_state.json   ← Estado salvo (gerado automaticamente)
├── monitor.log       ← Log de execução (gerado automaticamente)
└── README.md
```

---

## ⚙️ Configuração (`config.json`)

```json
{
  "form_url": "URL_DO_SEU_FORMULARIO",
  "check_interval_seconds": 300,   // intervalo em segundos (padrão: 5 min)
  "state_file": "form_state.json",
  "log_file": "monitor.log",

  "email": {
    "enabled": false,              // mude para true para ativar alertas
    "from": "seuemail@gmail.com",
    "to": ["destinatario@gmail.com"],
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "seuemail@gmail.com",
    "smtp_password": "SUA_SENHA_DE_APP_AQUI"
  }
}
```

### 📧 Como ativar o envio de e-mail (Gmail)

1. Acesse sua conta Google → **Segurança** → **Verificação em duas etapas** (ative se não tiver)
2. Vá em **Senhas de app** → Gere uma senha para "Email / Windows"
3. Cole essa senha no campo `smtp_password` do `config.json`
4. Mude `"enabled": true`

> ⚠️ **Nunca use sua senha normal do Gmail.** Use exclusivamente a "Senha de app".

---

## ▶️ Como Executar

### Pré-requisitos
- Python 3.10 ou superior (sem dependências externas!)

### Executar diretamente
```bash
python monitor.py
```

### Executar em segundo plano (Windows)
```bash
start /B pythonw monitor.py
```

### Executar como tarefa agendada (Windows Task Scheduler)
1. Abra o **Agendador de Tarefas** do Windows
2. Crie uma nova tarefa básica
3. Ação: **Iniciar um programa**
4. Programa: `python`
5. Argumentos: `C:\caminho\completo\monitor.py`

---

## 📋 Exemplo de saída no console

```
[2026-05-19 08:45:00] INFO - ═══════════════════════════════════════════════════
[2026-05-19 08:45:00] INFO -   Google Forms Monitor iniciado
[2026-05-19 08:45:00] INFO -   URL: https://docs.google.com/forms/d/e/...
[2026-05-19 08:45:00] INFO -   Intervalo de verificação: 300s
[2026-05-19 08:45:05] INFO - Estado inicial salvo. Título: "SMG15 - Contagem 2" | Perguntas: 1
[2026-05-19 08:50:05] INFO - Verificando formulário...
[2026-05-19 08:50:08] WARNING - 🚨 ALTERAÇÃO DETECTADA! 1 mudança(s) encontrada(s).
[2026-05-19 08:50:08] WARNING -   → ➕ Nova pergunta adicionada: "CPF"
```
