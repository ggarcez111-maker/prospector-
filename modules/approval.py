"""
modules/approval.py

Aprovacao manual, uma mensagem por vez, antes de cada envio pelo WhatsApp.

O envio chama `ask_approval(lead, mensagem)` e recebe de volta:
  - o texto final a enviar (original ou editado por voce), ou
  - None para pular este lead.
Digitar `q` levanta ApprovalAbort e interrompe o envio de todos os restantes.
"""

from __future__ import annotations


class ApprovalAbort(Exception):
    """Levantada quando o usuario escolhe parar o envio (q)."""


def _read_multiline(prompt: str) -> str:
    print(prompt + " (termine com uma linha vazia; vazio = manter o original)")
    lines: list[str] = []
    while True:
        line = input()
        if not line:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def ask_approval(lead: dict, mensagem: str) -> str | None:
    nome = lead.get("nome", "negocio sem nome")
    telefone = lead.get("telefone") or "(sem telefone)"
    link = lead.get("demo_public_url") or lead.get("demo_path") or "(sem demo)"

    while True:
        print("\n" + "=" * 60)
        print(f"Negocio  : {nome}")
        print(f"Telefone : {telefone}")
        print(f"Score    : {lead.get('lead_score', '-')}")
        print(f"Demo     : {link}")
        print("-" * 60)
        print(mensagem)
        print("=" * 60)
        choice = input("[s] enviar  [n] pular  [e] editar mensagem  [q] parar tudo > ").strip().lower()

        if choice in ("s", "sim", "y", "yes"):
            return mensagem
        if choice in ("n", "nao", "não", "no"):
            return None
        if choice in ("q", "quit", "sair"):
            raise ApprovalAbort()
        if choice in ("e", "editar"):
            novo = _read_multiline("Digite a nova mensagem")
            if novo:
                mensagem = novo
            continue  # mostra de novo para confirmar
        print("Opcao invalida.")
