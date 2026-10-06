# Prospector 2.2 — Automação de Prospecção para Sites

Fluxo completo: **descoberta (Maps) → score → demo → hospedagem opcional →
mensagem (Groq) → CRM (SQLite) → envio opcional (WhatsApp)**.

```
prospector/
├── main.py
├── modules/
│   ├── discovery.py         # Google Maps (Playwright + google-maps-scraper)
│   ├── lead_scoring.py       # score 0-100
│   ├── demo_generator.py     # landing page estatica por lead
│   ├── hosting.py            # publicacao automatica no GitHub Pages (opcional)
│   ├── screenshot.py         # print da demo para enviar como imagem (opcional)
│   ├── message_generator.py  # Groq (API gratuita, compativel com OpenAI)
│   ├── phone.py              # normalizacao e classificacao celular/fixo
│   ├── lead_filters.py       # filtro de celular, fila de envio, retry via CRM
│   ├── approval.py           # aprovacao manual de cada mensagem
│   ├── crm.py                # SQLite: leads, score, demo, status, eventos, opt-outs
│   └── whatsapp_sender.py    # pywhatkit, drip mode, limite diario, warm-up, opt-out
├── tests/                    # pytest: lead_scoring, whatsapp_sender, crm
├── utils/logger.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Novidades da 2.2

| Área | O que mudou |
|---|---|
| Aprovação manual | **Padrão**: cada mensagem é mostrada (com demo e telefone) e só sai se você digitar `s`. Também dá para editar (`e`), pular (`n`) ou parar tudo (`q`). `--sem-aprovacao` desativa |
| Filtro de celular | Fixo, 0800 e números inválidos saem **antes** de gerar demo/mensagem (não gasta Groq nem GitHub). `--incluir-fixos` mantém os fixos |
| Opt-out | Vale para o **número**, em qualquer formato (`41999998888`, `(41) 99999-8888`, `+5541...`), numa tabela própria — continua valendo se o lead for redescoberto. Bancos antigos são migrados sozinhos |
| Limite diário | Agora é **por dia**, somado entre execuções (`envios_diarios.json`). Rodar 3 vezes não triplica o limite. Lead recusado na aprovação não conta |
| `--retry-falhas` | Corrigido: antes nunca reordenava nada. Agora também traz do CRM quem falhou, mesmo que a busca atual não o encontre de novo |
| Slug da demo | `Açaí do João` → `acai-do-joao-a1b2c3` (acentos preservados + hash do lead). Sem colisão entre homônimos e URL pública não enumerável |
| Demo | Mostra a **categoria real** do Maps, horário de funcionamento (quando a biblioteca fornece), nota e avaliações reais; textos de serviço são marcados como exemplo; `noindex` para o Google não indexar |
| CRM | Status atualizado de verdade: `contatado` após envio, `descartado` se recusado. O funil (`--relatorio`) passa a refletir o que aconteceu |
| Intervalo | O tempo gasto aprovando conta como parte do intervalo entre envios (não espera à toa) |
| Testes | `send_messages`, filtros, demo, opt-out e migração agora têm testes (65 no total) |

## Novidades da 2.1

| Área | O que foi adicionado |
|---|---|
| Demo | Cada lead ganha uma landing page real (`demos/<slug>/index.html`) |
| Hospedagem | Publicação automática no **GitHub Pages** — a demo passa a ter link público de verdade |
| Categoria | Usa a categoria real do Google Maps (não só o termo de busca) para o score |
| Score | 0–100, com `--min-score` para filtrar leads fracos |
| Mensagem | Varia o estilo entre leads (reduz padrão repetitivo); inclui o link da demo quando ela está hospedada, sem inventar links quando não está |
| Imagem | `--screenshot` captura um print da demo e envia como imagem com legenda |
| Warm-up | `--warmup` aumenta o limite diário aos poucos, em vez de sair enviando o máximo desde o primeiro dia |
| Reenvio | `--retry-falhas` prioriza quem falhou numa execução anterior |
| Opt-out | `python main.py --optout "+55..."` marca um número como "não contatar" — respeitado em todos os envios seguintes |
| CRM | Deduplicação real pelo link do perfil do Maps (antes, leads sem telefone podiam duplicar a cada execução) |
| Relatório | `python main.py --relatorio` mostra o funil (por status, score médio, top leads) |
| Testes | `tests/` com pytest cobrindo score, normalização de telefone e CRM |

## ⚠️ Leia antes de usar

- **Google Maps**: scraping pode violar os Termos de Serviço do Google. Use com moderação.
- **WhatsApp**: envio automatizado sem consentimento prévio pode ser tratado como spam e **banir o número**. Use listas pequenas, mensagens genuinamente personalizadas e prefira o modo `--warmup` em números novos.
- **Opt-out é manual**: o `pywhatkit` só envia mensagens, não lê respostas do WhatsApp. Se alguém pedir para não receber mais contato, rode `--optout` você mesmo — não existe detecção automática de resposta.
- **Aprovação manual precisa de terminal interativo**: durante o envio o navegador abre e fecha abas; se o terminal perder o foco, clique nele para responder.
- **Demos são públicas** quando hospedadas no GitHub Pages: contêm nome, telefone e endereço do negócio. Elas usam `noindex`, mas qualquer pessoa com o link vê. Prefira um token fine-grained restrito ao repositório de demos.
- **Horário de funcionamento**: depende de a biblioteca `google-maps-scraper` expor o campo; se não expuser, a demo simplesmente não mostra essa seção.
- **LGPD**: nome, telefone e endereço de estabelecimentos são dados pessoais. Trate com cuidado e não guarde além do necessário.
- **Nomes duplicados**: o gerador de demo usa o nome do negócio como slug da pasta; duas redes com o mesmo nome em endereços diferentes vão sobrescrever a demo uma da outra. Não é um problema comum, mas fique de olho em buscas com muitas franquias.

## Requisitos

- Python 3.10+
- Google Chrome (ou navegador padrão) **já logado no WhatsApp Web**
- Ambiente com interface gráfica (o `pywhatkit` controla a tela — não roda em servidor 100% headless)
- Conta gratuita na Groq: https://console.groq.com/keys
- (Opcional, para hospedar as demos) Um repositório no GitHub com **GitHub Pages** habilitado, e um token em https://github.com/settings/tokens

## Instalação

```bash
cd prospector
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install firefox

cp .env.example .env
# edite o .env: no minimo GROQ_API_KEY; opcionalmente GITHUB_TOKEN/GITHUB_REPO
```

### Configurando a hospedagem automática das demos (opcional, mas recomendado)

Sem isso, cada demo continua sendo gerada normalmente, só que fica **só no seu
disco** — a mensagem então pede permissão antes de mandar o link, em vez de
mandar um link de verdade.

1. Crie um repositório no GitHub (pode ser um só para isso, ex: `minhas-demos`).
2. Em **Settings → Pages**, habilite o GitHub Pages apontando para a branch
   `gh-pages` (crie essa branch vazia primeiro, se o repositório for novo).
3. Gere um token em https://github.com/settings/tokens com escopo `repo`
   (ou `public_repo` se o repositório for público).
4. No `.env`:
   ```
   GITHUB_TOKEN=ghp_xxx
   GITHUB_REPO=seu-usuario/minhas-demos
   GITHUB_BRANCH=gh-pages
   ```

Com isso configurado, cada demo é publicada automaticamente em
`https://seu-usuario.github.io/minhas-demos/demos/<slug-do-negocio>/` e esse
link entra na mensagem gerada pela Groq.

## Uso

Fluxo completo:
```bash
python main.py --cidade "Curitiba PR" --negocio "restaurantes" --max-leads 20
```

Só descobrir, pontuar, gerar demo e mensagem — sem enviar nada:
```bash
python main.py --cidade "Curitiba PR" --negocio "salões de beleza" --sem-envio
```

Filtrar só os leads mais promissores:
```bash
python main.py --cidade "Niterói RJ" --negocio "clínicas" --min-score 60
```

Enviar a demo como imagem (com a mensagem como legenda) e com warm-up ativo:
```bash
python main.py --cidade "Curitiba PR" --negocio "pet shops" --screenshot --warmup
```

Reenviar priorizando quem falhou da última vez:
```bash
python main.py --cidade "Curitiba PR" --negocio "pet shops" --retry-falhas
```

Ver o funil de leads acumulado no CRM:
```bash
python main.py --relatorio
```

Marcar um número como "não contatar" (opt-out manual):
```bash
python main.py --optout "+5541999998888"
```

### Argumentos principais

| Argumento | Padrão | Descrição |
|---|---|---|
| `--cidade` / `--negocio` | — | Alvo da busca (obrigatórios, exceto com `--relatorio`/`--optout`) |
| `--max-leads` | 30 | Máximo de estabelecimentos buscados |
| `--min-score` | 40 | Score mínimo para um lead seguir no funil |
| `--daily-limit` | 15 | Teto de mensagens **por dia**, somado entre execuções (respeitado também pelo warm-up) |
| `--sem-aprovacao` | false | Envia sem pedir aprovação manual (não recomendado) |
| `--incluir-fixos` | false | Mantém leads com telefone fixo (útil para ligar; o WhatsApp não os alcança) |
| `--sem-envio` | false | Roda tudo, menos o envio pelo WhatsApp |
| `--sem-demo` | false | Não gera landing page |
| `--sem-hospedagem` | false | Gera a demo mas não publica no GitHub Pages |
| `--screenshot` | false | Envia print da demo como imagem em vez de texto puro |
| `--warmup` | false | Ativa a rampa de aquecimento do número |
| `--retry-falhas` | false | Prioriza reenvio para quem falhou antes |
| `--relatorio` | — | Mostra o funil do CRM e encerra |
| `--optout TELEFONE` | — | Marca o telefone como "não contatar" (qualquer formato) e encerra |

## Arquivos gerados

- `leads.json`, `leads_com_mensagens.json` — saída bruta de cada etapa.
- `demos/<slug>/index.html` — landing page de cada lead.
- `prospector.db` — CRM SQLite (leads, score, status, eventos, link da demo).
- `envios.log` — log de tudo, incluindo cada tentativa de envio.
- `enviados.json` / `falhas.json` — controle de duplicidade e de reenvio (falhas usam o telefone E.164 como chave).
- `envios_diarios.json` — contagem de envios por dia (base do limite diário).
- `warmup_state.json` — dias de uso contados para a rampa de warm-up.

## Testes

```bash
pip install pytest
pytest tests/ -v
```

Cobre `phone`, `lead_filters`, `send_messages` (limite diário, retry, aprovação, opt-out, intervalo), `demo_generator`, `lead_scoring` (pontuação e filtro), `whatsapp_sender.normalize_phone`
(limite conhecido: números de 10–11 dígitos são tratados como DDD+número local, então um número internacional de 11 dígitos pode ser mal interpretado — ajuste `WHATSAPP_COUNTRY_CODE` se for prospectar fora do Brasil; fora do Brasil não há classificação celular/fixo) e `crm` (deduplicação, opt-out, status, relatório).

## Uso responsável

Scraping, automação de WhatsApp e prospecção comercial precisam respeitar os
termos dos serviços utilizados e a legislação aplicável (ex: LGPD). Mantenha
listas pequenas, revise leads e mensagens antes de disparar, e use
`--warmup` em números novos.
