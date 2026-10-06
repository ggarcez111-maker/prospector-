"""Gera demos HTML estáticas e leves para apresentação comercial."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from pathlib import Path


def _slug(text: str) -> str:
    """Slug ASCII: 'Açaí do João' -> 'acai-do-joao' (acentos viram letra base, nao somem)."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^a-zA-Z0-9\s-]", "", ascii_text).strip().lower()
    return re.sub(r"[-\s]+", "-", ascii_text)[:60].strip("-") or "negocio"


def demo_slug(lead: dict) -> str:
    """
    Slug estavel e unico por lead: nome legivel + 6 caracteres de hash da
    identidade do lead (link do Maps, ou nome+endereco+telefone). Evita que
    duas filiais/homonimos sobrescrevam a demo um do outro e torna a URL
    publica impossivel de adivinhar/enumerar.
    """
    identity = (lead.get("link_perfil") or "").strip() or "|".join(
        str(lead.get(k) or "").strip().lower() for k in ("nome", "endereco", "telefone")
    )
    suffix = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:6]
    return f"{_slug(lead.get('nome') or 'negocio')}-{suffix}"


def _safe(value: object, fallback: str = "") -> str:
    return html.escape(str(value).strip()) if value else fallback


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _category(lead: dict) -> str:
    text = " ".join(str(lead.get(k) or "") for k in ("categoria", "segmento", "tipo", "nome")).lower()
    groups = {
        "food": ("restaurante", "lanchonete", "pizzaria", "hamburg", "bar ", "cafeteria", "padaria", "doceria", "açaí", "sorvete", "churrasc"),
        "beauty": ("barbearia", "salão", "cabeleire", "beleza", "estética", "manicure", "pedicure", "spa"),
        "auto": ("oficina", "mecânica", "mecanica", "automot", "auto center", "pneus", "funilaria", "moto peças"),
        "health": ("clínica", "clinica", "dentista", "odont", "fisioter", "psicolog", "médic", "medic", "laboratório", "farmácia", "farmacia"),
    }
    for key, terms in groups.items():
        if any(term in text for term in terms):
            return key
    return "general"


TEMPLATES = {
    "food": ("Sabor perto de você", "Seu próximo pedido começa aqui.", "Uma vitrine digital simples para apresentar o negócio, facilitar o contato e ajudar novos clientes a encontrar você.", [("Cardápio", "Apresente seus principais produtos e facilite a decisão do cliente."), ("Atendimento", "Um caminho direto para tirar dúvidas e fazer pedidos."), ("Localização", "Mostre onde o cliente pode encontrar seu negócio.")], "#f97316"),
    "beauty": ("Seu cuidado, sua presença", "Uma primeira impressão à altura do seu trabalho.", "Uma página elegante para apresentar o espaço, destacar serviços e transformar uma busca local em um novo contato.", [("Serviços", "Destaque os principais serviços de forma clara e visual."), ("Agendamento", "Deixe o caminho para falar com você sempre visível."), ("Localização", "Ajude clientes da região a encontrar seu espaço.")], "#d946ef"),
    "auto": ("Serviço automotivo", "Seu cliente procura. Sua empresa precisa aparecer.", "Uma presença online objetiva para mostrar serviços, localização e facilitar o contato com quem precisa de atendimento.", [("Serviços", "Mostre rapidamente o que sua empresa pode resolver."), ("Contato", "Um botão direto para solicitar informações e orçamento."), ("Localização", "Facilite a chegada de clientes da região.")], "#22c55e"),
    "health": ("Atendimento e confiança", "Informação clara antes do primeiro contato.", "Uma demonstração de página profissional para apresentar o atendimento, facilitar o contato e orientar o cliente até sua empresa.", [("Atendimento", "Apresente sua área de atuação sem excesso de informação."), ("Contato", "Deixe o canal de atendimento fácil de encontrar."), ("Localização", "Mostre onde o cliente pode ser atendido.")], "#06b6d4"),
    "general": ("Presença local", "Mais presença quando alguém procura por você.", "Uma página demonstrativa pensada para apresentar o negócio, facilitar o contato e criar uma presença digital profissional.", [("Apresentação", "Mostre rapidamente quem é sua empresa e o que ela oferece."), ("Contato", "Um caminho simples para o cliente falar com você."), ("Localização", "Facilite a descoberta do negócio na sua região.")], "#8b5cf6"),
}


_CSS = r'''
:root{--accent:ACCENT;--bg:#0b0b0c;--panel:#141416;--text:#f7f7f5;--muted:#a7a7aa;--line:#28282b}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}a{color:inherit}.demo-bar{position:fixed;z-index:20;top:14px;right:14px;padding:7px 11px;border:1px solid #3a3a3d;background:#111114dd;backdrop-filter:blur(10px);border-radius:999px;color:#a7a7aa;font-size:11px;letter-spacing:.08em;text-transform:uppercase}.wrap{width:min(1120px,calc(100% - 32px));margin:auto}
header{display:flex;justify-content:space-between;align-items:center;padding:24px 0;border-bottom:1px solid var(--line)}.brand{font-weight:800;letter-spacing:-.03em;max-width:65%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.nav{display:flex;gap:20px;color:var(--muted);font-size:14px}.nav a{text-decoration:none}.hero{padding:92px 0 80px;display:grid;grid-template-columns:1.35fr .65fr;gap:50px;align-items:end}.eyebrow{color:var(--accent);font-size:13px;font-weight:800;letter-spacing:.13em;text-transform:uppercase}h1{font-size:clamp(44px,7vw,82px);line-height:.96;letter-spacing:-.055em;margin:18px 0 24px;max-width:820px}.intro{font-size:19px;color:var(--muted);max-width:650px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:30px}.btn{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:0 18px;border-radius:12px;text-decoration:none;font-weight:800;border:1px solid var(--line);background:var(--text);color:#0b0b0c}.btn.secondary{background:transparent;color:var(--text)}
.facts{border:1px solid var(--line);border-radius:22px;background:linear-gradient(145deg,#171719,#101012);padding:24px}.facts-label{font-size:11px;color:#77777b;letter-spacing:.12em;text-transform:uppercase}.facts h2{font-size:25px;line-height:1.1;margin:8px 0 20px}.rating{display:inline-block;color:#fbbf24;font-weight:800;margin-bottom:14px}.address{color:var(--muted);font-size:14px;margin:0 0 12px}.hours{list-style:none;padding:0;margin:16px 0 0;font-size:13px;color:var(--muted)}.hours li{padding:5px 0;border-top:1px solid var(--line)}.hours-title{font-size:11px;color:#77777b;letter-spacing:.12em;text-transform:uppercase;margin-top:18px}.contact-line{display:block;text-decoration:none;font-weight:700;margin-top:6px}.section{padding:74px 0;border-top:1px solid var(--line)}.section-head{display:flex;justify-content:space-between;gap:30px;align-items:end;margin-bottom:30px}.section h2{font-size:clamp(30px,5vw,48px);line-height:1;margin:0;letter-spacing:-.04em}.section-head p{color:var(--muted);max-width:420px;margin:0}.features{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.feature{padding:26px;border:1px solid var(--line);border-radius:20px;background:var(--panel);min-height:210px}.feature-number{color:var(--accent);font-weight:900;font-size:12px;letter-spacing:.1em}.feature h3{font-size:23px;margin:50px 0 8px}.feature p{color:var(--muted);margin:0}.cta{border:1px solid var(--line);border-radius:26px;padding:42px;background:var(--panel);display:flex;justify-content:space-between;align-items:center;gap:30px}.cta h2{font-size:clamp(30px,5vw,50px);line-height:1;margin:0 0 10px;letter-spacing:-.04em}.cta p{color:var(--muted);margin:0}footer{padding:35px 0 55px;color:#77777b;font-size:12px;display:flex;justify-content:space-between;gap:20px}
@media(max-width:760px){.demo-bar{top:10px;right:10px}.nav{display:none}.hero{grid-template-columns:1fr;padding:65px 0 55px;gap:30px}h1{font-size:48px}.features{grid-template-columns:1fr}.section-head,.cta{display:block}.section-head p{margin-top:15px}.cta .btn{margin-top:24px}footer{display:block}footer span{display:block;margin-top:8px}}
'''


def generate_demo(lead: dict, output_dir: str = "demos") -> str:
    name = _safe(lead.get("nome"), "Seu negócio")
    address = _safe(lead.get("endereco"), "Atendimento local")
    phone_raw = str(lead.get("telefone") or "").strip()
    phone = _safe(phone_raw)
    phone_digits = _digits(phone_raw)
    maps_raw = str(lead.get("link_perfil") or "https://www.google.com/maps")
    maps = html.escape(maps_raw, quote=True)
    rating = _safe(lead.get("nota"))
    reviews = _safe(lead.get("numero_avaliacoes"))
    category = _safe(lead.get("categoria"), "Negócio local")
    eyebrow, headline, intro, features, accent = TEMPLATES[_category(lead)]
    if lead.get("categoria"):
        eyebrow = str(lead["categoria"]).strip()  # categoria REAL do Google Maps
    horarios = [h for h in (lead.get("horarios") or []) if h]
    hours_block = (
        '<div class="hours-title">Horário de funcionamento</div><ul class="hours">'
        + "".join(f"<li>{_safe(h)}</li>" for h in horarios[:7])
        + "</ul>"
    ) if horarios else ""
    slug = demo_slug(lead)
    root = Path(output_dir) / slug
    root.mkdir(parents=True, exist_ok=True)

    wa = html.escape("https://wa.me/" + phone_digits if phone_digits else "#contato", quote=True)
    tel = html.escape("tel:" + phone_digits if phone_digits else "#contato", quote=True)
    label = "Falar no WhatsApp" if phone_digits else "Entrar em contato"
    rating_block = f'<span class="rating">★ {rating}' + (f' · {reviews} avaliações' if reviews else "") + '</span>' if rating else ""
    phone_block = f'<a class="contact-line" href="{tel}">{phone}</a>' if phone else '<span class="contact-line">Contato pelo WhatsApp</span>'
    cards = "".join(f'<article class="feature"><div class="feature-number">0{i}</div><h3>{_safe(a)}</h3><p>{_safe(b)}</p></article>' for i,(a,b) in enumerate(features,1))
    css = _CSS.replace("ACCENT", accent)
    page = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta name="description" content="Demonstração de presença online para {name}"><title>{name} — Demonstração</title><style>{css}</style></head><body><div class="demo-bar">Site demonstrativo</div><div class="wrap"><header><div class="brand">{name}</div><nav class="nav"><a href="#sobre">Sobre</a><a href="#servicos">Serviços</a><a href="#contato">Contato</a></nav></header><main><section class="hero" id="sobre"><div><div class="eyebrow">{_safe(eyebrow)}</div><h1>{_safe(headline)}</h1><p class="intro">{_safe(intro)}</p><div class="actions"><a class="btn" href="{wa}">{label}</a><a class="btn secondary" href="{maps}" target="_blank" rel="noopener">Ver localização</a></div></div><aside class="facts"><div class="facts-label">{category}</div><h2>{name}</h2>{rating_block}<p class="address">{address}</p>{phone_block}{hours_block}</aside></section><section class="section" id="servicos"><div class="section-head"><h2>Uma página que trabalha<br>pelo negócio.</h2><p>Estrutura simples e pensada primeiro para o celular. Os textos desta seção são exemplos: o conteúdo real é definido junto com você.</p></div><div class="features">{cards}</div></section><section class="section" id="contato"><div class="cta"><div><div class="eyebrow">Vamos conversar</div><h2>Facilite o próximo passo.</h2><p>Contato, localização e informações importantes em um só lugar.</p></div><div class="actions"><a class="btn" href="{wa}">{label}</a><a class="btn secondary" href="{maps}" target="_blank" rel="noopener">Como chegar</a></div></div></section></main><footer><span>{name}</span><span>Demonstração criada para apresentação comercial.</span></footer></div></body></html>'''
    path = root / "index.html"
    path.write_text(page, encoding="utf-8")
    return str(path)
