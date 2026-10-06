"""Testes para modules/demo_generator.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.demo_generator import _slug, demo_slug, generate_demo


def test_slug_preserva_letras_acentuadas_como_base():
    assert _slug("Açaí do João") == "acai-do-joao"
    assert _slug("Café & Cia") == "cafe-cia"
    assert _slug("ÁÉÍ") == "aei"


def test_slug_sem_nenhuma_letra_ascii_usa_fallback():
    assert _slug("!!!") == "negocio"


def test_homonimos_com_links_diferentes_nao_colidem():
    a = {"nome": "Padaria Central", "link_perfil": "https://maps/a"}
    b = {"nome": "Padaria Central", "link_perfil": "https://maps/b"}
    assert demo_slug(a) != demo_slug(b)


def test_slug_e_estavel_entre_execucoes():
    lead = {"nome": "Padaria Central", "link_perfil": "https://maps/a"}
    assert demo_slug(lead) == demo_slug(dict(lead))


def test_slug_sem_link_usa_nome_endereco_telefone():
    a = {"nome": "Loja", "endereco": "Rua A", "telefone": "1"}
    b = {"nome": "Loja", "endereco": "Rua B", "telefone": "1"}
    assert demo_slug(a) != demo_slug(b)


def test_demo_usa_dados_reais_e_escapa_html(tmp_path):
    path = generate_demo(
        {
            "nome": "Pet <Shop>", "telefone": "(41) 99999-8888", "endereco": "Rua X, 1",
            "nota": 4.8, "numero_avaliacoes": 120, "categoria": "Pet shop",
            "link_perfil": "https://maps/p", "horarios": ["Segunda: 08:00–18:00", "Domingo: Fechado"],
        },
        str(tmp_path),
    )
    page = Path(path).read_text(encoding="utf-8")
    assert "&lt;Shop&gt;" in page and "<Shop>" not in page
    assert "Segunda: 08:00–18:00" in page          # horario real
    assert ">Pet shop<" in page                     # categoria real no destaque
    assert "120 avaliações" in page
    assert 'name="robots" content="noindex,nofollow"' in page
    assert "são exemplos" in page                   # textos genericos sinalizados


def test_demo_sem_horarios_nao_inventa_secao(tmp_path):
    path = generate_demo({"nome": "Loja", "link_perfil": "https://maps/l"}, str(tmp_path))
    assert "Horário de funcionamento" not in Path(path).read_text(encoding="utf-8")
