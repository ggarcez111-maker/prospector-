"""CRM local em SQLite para leads e histórico de prospecção."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from modules.phone import normalize_phone

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 dedup_key TEXT UNIQUE,
 nome TEXT NOT NULL,
 telefone TEXT,
 telefone_e164 TEXT,
 endereco TEXT,
 nota REAL,
 numero_avaliacoes INTEGER,
 link_perfil TEXT,
 website TEXT,
 categoria TEXT,
 lead_score INTEGER DEFAULT 0,
 score_reasons TEXT,
 demo_url TEXT,
 demo_public_url TEXT,
 mensagem TEXT,
 status TEXT DEFAULT 'novo',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS optouts (
 telefone_e164 TEXT PRIMARY KEY,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 lead_id INTEGER NOT NULL,
 event TEXT NOT NULL,
 details TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(lead_id) REFERENCES leads(id)
);
"""

# Status possiveis (livres, mas estes sao usados/reconhecidos pelo relatorio):
STATUS_NOVO = "novo"
STATUS_CONTATADO = "contatado"
STATUS_RESPONDEU = "respondeu"
STATUS_FECHOU = "fechou"
STATUS_SEM_INTERESSE = "sem_interesse"
STATUS_DESCARTADO = "descartado"  # recusado na aprovacao manual
STATUS_NAO_CONTATAR = "nao_contatar"  # opt-out

# Status em que nao faz sentido abordar o lead de novo.
STATUS_SEM_NOVO_ENVIO = {
    STATUS_CONTATADO, STATUS_RESPONDEU, STATUS_FECHOU,
    STATUS_SEM_INTERESSE, STATUS_DESCARTADO, STATUS_NAO_CONTATAR,
}


def _dedup_key(lead: dict) -> str:
    """
    Chave estavel para deduplicar leads entre execucoes.
    Prioriza o link do perfil no Google Maps (praticamente sempre unico e
    presente); cai para nome+telefone+endereco quando o link nao existir.
    """
    link = (lead.get("link_perfil") or "").strip()
    if link:
        return f"link:{link}"
    nome = (lead.get("nome") or "").strip().lower()
    telefone = (lead.get("telefone") or "").strip()
    endereco = (lead.get("endereco") or "").strip().lower()
    return f"combo:{nome}|{telefone}|{endereco}"


class CRM:
    def __init__(self, path: str = "prospector.db", default_country_code: str = "55") -> None:
        self.path = Path(path)
        self.default_country_code = default_country_code
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _norm(self, telefone: str | None) -> str | None:
        return normalize_phone(telefone, self.default_country_code)

    def _migrate(self) -> None:
        """Atualiza bancos criados por versoes anteriores (sem telefone_e164 / optouts)."""
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(leads)")}
        if "telefone_e164" not in cols:
            self.conn.execute("ALTER TABLE leads ADD COLUMN telefone_e164 TEXT")
        for row in self.conn.execute(
            "SELECT id, telefone FROM leads WHERE telefone IS NOT NULL AND telefone_e164 IS NULL"
        ).fetchall():
            self.conn.execute(
                "UPDATE leads SET telefone_e164=? WHERE id=?", (self._norm(row["telefone"]), row["id"])
            )
        # Opt-outs antigos viviam so no status do lead: copia para a tabela propria.
        for row in self.conn.execute(
            "SELECT telefone_e164 FROM leads WHERE status=? AND telefone_e164 IS NOT NULL",
            (STATUS_NAO_CONTATAR,),
        ).fetchall():
            self.conn.execute(
                "INSERT OR IGNORE INTO optouts (telefone_e164) VALUES (?)", (row["telefone_e164"],)
            )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_e164 ON leads(telefone_e164)")

    # ---------- leads ----------

    def upsert_lead(self, lead: dict) -> int:
        key = _dedup_key(lead)
        cur = self.conn.execute(
            """
            INSERT INTO leads (dedup_key, nome, telefone, telefone_e164, endereco, nota, numero_avaliacoes,
              link_perfil, website, categoria, lead_score, score_reasons, demo_url,
              demo_public_url, mensagem, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedup_key) DO UPDATE SET
              telefone_e164=COALESCE(excluded.telefone_e164, leads.telefone_e164),
              endereco=excluded.endereco, nota=excluded.nota,
              numero_avaliacoes=excluded.numero_avaliacoes, link_perfil=excluded.link_perfil,
              website=excluded.website, categoria=excluded.categoria,
              lead_score=excluded.lead_score, score_reasons=excluded.score_reasons,
              demo_url=excluded.demo_url,
              demo_public_url=COALESCE(excluded.demo_public_url, leads.demo_public_url),
              mensagem=excluded.mensagem,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                key,
                lead.get("nome") or "Sem nome",
                lead.get("telefone"),
                lead.get("telefone_e164") or self._norm(lead.get("telefone")),
                lead.get("endereco"),
                lead.get("nota"),
                lead.get("numero_avaliacoes"),
                lead.get("link_perfil"),
                lead.get("website"),
                lead.get("categoria") or lead.get("negocio"),
                lead.get("lead_score", 0),
                ", ".join(lead.get("score_reasons", [])),
                lead.get("demo_path"),
                lead.get("demo_public_url"),
                lead.get("mensagem"),
                lead.get("status", STATUS_NOVO),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT id FROM leads WHERE dedup_key=?", (key,)).fetchone()
        return int(row["id"]) if row else int(cur.lastrowid)

    def get_lead(self, lead_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()

    def find_by_phone(self, telefone: str) -> sqlite3.Row | None:
        """Busca por telefone em qualquer formato (compara pelo numero normalizado)."""
        e164 = self._norm(telefone)
        if e164 is None:
            return self.conn.execute("SELECT * FROM leads WHERE telefone=?", (telefone,)).fetchone()
        return self.conn.execute(
            "SELECT * FROM leads WHERE telefone_e164=? ORDER BY id LIMIT 1", (e164,)
        ).fetchone()

    def get_leads_by_phones(self, telefones_e164: list[str]) -> list[dict]:
        """Leads ja salvos (com mensagem pronta) para os telefones E.164 dados - usado no retry."""
        if not telefones_e164:
            return []
        marks = ",".join("?" for _ in telefones_e164)
        rows = self.conn.execute(
            f"SELECT * FROM leads WHERE telefone_e164 IN ({marks}) AND mensagem IS NOT NULL",
            telefones_e164,
        ).fetchall()
        leads = []
        for row in rows:
            d = dict(row)
            d["crm_id"] = d["id"]
            d["demo_path"] = d.get("demo_url")
            leads.append(d)
        return leads

    def update_status(self, lead_id: int, status: str, detail: str = "") -> None:
        self.conn.execute(
            "UPDATE leads SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, lead_id),
        )
        self.conn.commit()
        self.event(lead_id, f"status:{status}", detail)

    def set_demo_public_url(self, lead_id: int, url: str) -> None:
        self.conn.execute(
            "UPDATE leads SET demo_public_url=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (url, lead_id),
        )
        self.conn.commit()
        self.event(lead_id, "demo_publicada", url)

    # ---------- opt-out ----------

    def mark_optout(self, telefone: str) -> str:
        """
        Marca um telefone como 'nao contatar', aceitando qualquer formato
        ("+5541999998888", "(41) 99999-8888", "41999998888"). O pywhatkit so
        envia mensagens (nao le respostas do WhatsApp), entao esse controle
        e sempre manual: rode `python main.py --optout "<telefone>"` quando um
        lead pedir para nao receber mais contato.

        O opt-out vale para o NUMERO (tabela propria), mesmo que o lead seja
        redescoberto depois com outro link ou formato. Retorna o E.164 gravado.
        Levanta ValueError se o telefone nao puder ser normalizado.
        """
        e164 = self._norm(telefone)
        if e164 is None:
            raise ValueError(f"Telefone invalido para opt-out: {telefone!r}")

        self.conn.execute("INSERT OR IGNORE INTO optouts (telefone_e164) VALUES (?)", (e164,))
        self.conn.commit()
        for row in self.conn.execute("SELECT id FROM leads WHERE telefone_e164=?", (e164,)).fetchall():
            self.update_status(int(row["id"]), STATUS_NAO_CONTATAR, "opt-out manual via CLI")
        return e164

    def is_optout(self, telefone: str) -> bool:
        e164 = self._norm(telefone)
        if e164 is None:
            return False
        row = self.conn.execute("SELECT 1 FROM optouts WHERE telefone_e164=?", (e164,)).fetchone()
        return row is not None

    # ---------- eventos ----------

    def event(self, lead_id: int, event: str, details: str = "") -> None:
        self.conn.execute(
            "INSERT INTO events (lead_id, event, details) VALUES (?, ?, ?)",
            (lead_id, event, details),
        )
        self.conn.commit()

    # ---------- relatorios ----------

    def funnel_report(self) -> dict:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS total FROM leads GROUP BY status"
        ).fetchall()
        por_status = {row["status"]: row["total"] for row in rows}

        agg = self.conn.execute(
            "SELECT COUNT(*) AS total, AVG(lead_score) AS media_score, "
            "MAX(lead_score) AS maior_score FROM leads"
        ).fetchone()

        top = self.conn.execute(
            "SELECT nome, lead_score, status, demo_public_url FROM leads "
            "ORDER BY lead_score DESC LIMIT 5"
        ).fetchall()

        return {
            "total_leads": agg["total"] or 0,
            "score_medio": round(agg["media_score"], 1) if agg["media_score"] else 0,
            "maior_score": agg["maior_score"] or 0,
            "por_status": por_status,
            "top_leads": [dict(r) for r in top],
        }

    def close(self) -> None:
        self.conn.close()
