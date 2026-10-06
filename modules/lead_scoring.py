"""Qualificação e pontuação de leads."""
from __future__ import annotations


def score_lead(lead: dict) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if not lead.get("website"):
        score += 30; reasons.append("sem site")
    if lead.get("telefone"):
        score += 20; reasons.append("tem telefone")
    if lead.get("numero_avaliacoes") is not None:
        reviews = int(lead.get("numero_avaliacoes") or 0)
        if reviews >= 100: score += 15; reasons.append("muitas avaliações")
        elif reviews >= 20: score += 10; reasons.append("avaliações suficientes")
        elif reviews > 0: score += 5; reasons.append("tem avaliações")
    rating = lead.get("nota")
    if rating is not None:
        try:
            rating = float(rating)
            if rating >= 4.5: score += 10; reasons.append("nota alta")
            elif rating >= 4.0: score += 7; reasons.append("boa nota")
        except (TypeError, ValueError):
            pass
    category = (lead.get("categoria") or "").lower()
    high_intent = ("restaurante", "salão", "barbearia", "clínica", "dent", "estética", "academia", "pousada", "hotel", "pet", "advoc")
    if any(x in category for x in high_intent):
        score += 10; reasons.append("categoria com potencial para presença online")
    if lead.get("endereco"):
        score += 5; reasons.append("endereço identificado")
    return min(score, 100), reasons


def qualify_leads(leads: list[dict], minimum_score: int = 0) -> list[dict]:
    enriched = []
    for lead in leads:
        score, reasons = score_lead(lead)
        enriched.append({**lead, "lead_score": score, "score_reasons": reasons})
    return sorted(
        [x for x in enriched if x["lead_score"] >= minimum_score],
        key=lambda x: x["lead_score"], reverse=True,
    )
