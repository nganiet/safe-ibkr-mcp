# ibkr-mcp — Design

**Statut :** Draft pour relecture (issu d'une session brainstorming, 2026-05-29)
**Date :** 2026-05-29
**Auteur :** Franck
**Type :** Projet OSS standalone, hors du repo privé Aegis.
**Emplacement :** `/Users/fnganiet/projects/ibkr-mcp/` (repo git autonome, licence MIT).

---

## 1. Pourquoi ce projet existe

Exposer **Interactive Brokers** comme un serveur **MCP** (Model Context Protocol) utilisable par
n'importe quel agent IA — Claude Desktop, Claude Code, Cursor, agents tiers, et potentiellement
Aegis. Le marché des serveurs MCP IBKR est déjà encombré (≥10 projets, cf. §4), mais **aucun**
n'offre une sécurité d'exécution *câblée et auditable*. La différenciation de ce projet est exactement
là : **« le MCP IBKR qu'on peut donner à un LLM sans se faire vider le compte »**.

Ce projet est volontairement **séparé d'Aegis** :

- Aegis est un repo **privé** ; ce projet est **OSS public (MIT)**. Mélanger les deux est une erreur
  (fuite d'historique, sous-repo imbriqué, gouvernance Aegis appliquée à tort).
- L'usage communautaire est le moteur du design ; les besoins Aegis en sont un **sous-ensemble**.
- Ce projet **n'est pas** soumis au `CLAUDE.md` d'Aegis (pas de `sprint-status.yaml`, pas de BMAD,
  pas d'authoritative-paths). Il a sa propre vie.

### Relation à l'épic Aegis E9b

Aegis a déjà un ADR (`docs/architecture/ibkr-local-agent.md`, épic E9b) décrivant un **IBKR Local
Agent** : un service Python headless, esclave RPC du cloud Aegis, parlant à IB Gateway via `ib_async`
et communiquant par un protocole maison (long-poll + push, réconciliation, audit-log).

Ce projet MCP est une **bête différente** : un serveur conversationnel exposant des *tools/resources*
à un LLM. Mais les deux partagent le **cœur dur** : connexion `ib_async`, Watchdog, traduction
`Symbol`→`Contract`, mapping ordres/positions. Ce design isole ce cœur (`core/`) pour qu'il soit
**extractible plus tard** en package `ibkr-core` que le futur `IBKRBrokerAdapter` d'Aegis pourra
consommer (cf. §15). Aucun couplage n'est introduit maintenant.

---

## 2. Objectif & non-objectifs

### Objectif (v1)

Un serveur MCP stdio, lancé sur la machine de l'utilisateur à côté de son IB Gateway, qui expose :

- des **tools de lecture** (compte, positions, ordres, exécutions ; + données marché entitlement-aware),
- des **tools d'écriture sous garde-fous** (placement/annulation/modification d'ordres via un flux
  `preview → confirm` idempotent),
- des **tools de contrôle** (kill-switch, health),

avec une **sécurité câblée côté serveur** qui reste valable même si le client MCP auto-approuve tout.

### Non-objectifs (v1)

- **Pas d'orchestration du Gateway** : l'utilisateur lance et maintient son propre IB Gateway/TWS
  (login, 2FA, restart). On se connecte, on gère les reconnexions, on reporte l'état. (BYO Gateway.)
- **Pas de transport distant** : stdio local uniquement (credentials + Gateway sur la machine). HTTP/SSE
  = évolution future éventuelle, hors v1.
- **Pas de packaging .app/installeur grand public** : `pip` / `uvx` suffisent pour la cible v1
  (utilisateurs techniques). C'est le périmètre lourd d'E9b, explicitement écarté ici.
- **Pas de multi-broker** : IBKR uniquement. (Le cœur réutilise les shapes du port broker d'Aegis,
  mais ce projet n'abstrait pas plusieurs courtiers.)

---

## 3. Décisions cadrées (résumé de la session brainstorming)

| Axe | Décision | Justification |
|---|---|---|
| Usage prioritaire | **Outil communautaire OSS** ; Aegis = sous-ensemble | Choix explicite du PO |
| Portée / risque | **Read + write avec garde-fous imposés** (paper par défaut, confirm live explicite, caps, kill-switch, allowlist) | Rend un MCP IBKR public utile *et* défendable |
| Scope Gateway | **BYO Gateway + Watchdog** | Sortie rapide, robuste, faible surface de support |
| Relation Aegis | **Approche A — standalone, cœur extractible** | OSS-first sans couplage prématuré ; porte Aegis ouverte |
| MCP vs skill | **MCP = moteur ; skill = couche UX Claude-only future** | « any AI agent » exige MCP ; un skill ne parle pas IBKR seul |
| Langage / lib | **Python + ib_async + FastMCP** | `ib_async` forcé (callbacks riches, TRAIL, maintenu) ; cohérent ADR-2 |
| Transport | **stdio local** | Credentials et Gateway sur la machine ; jamais de réseau |

---

## 4. État de l'art & différenciation

Survol effectué le 2026-05-29 (≥10 serveurs MCP IBKR sur GitHub).

| Serveur | Write ? | Garde-fous documentés | Lib | Core réutilisable |
|---|---|---|---|---|
| Hellek1/ib-mcp | ❌ read-only | n/a (trading désactivé) | ib_async + FastMCP | non |
| ArjunDivecha/ibkr-mcp-server | ✅ `place_order` | paper par défaut, `MAX_ORDER_SIZE`, « safety checks » floues | n/c | non documenté |
| code-rabi/interactive-brokers-mcp | ✅ (toggle read-only) | paper toggle, **minimal**, monolithique | IB Gateway | non |
| rcontesti/IB_MCP | ✅ | tickler de session | Client Portal REST | non |
| +6 autres (xiao81, kelvingao, jinyiabc, omdv, YoungMoney, gpolydatas) | mixte | « test paper first » générique | mixte | non |

**Le trou dans le marché :** même le plus « pro » n'a **aucun** de ces éléments documentés :
idempotence/déduplication d'ordres, flux `preview→confirm` à deux appels, kill-switch fichier,
allowlist tickers, ni cœur extractible. Ils sont soit read-only, soit write avec garde-fous vagues
laissés à la responsabilité de l'utilisateur.

**Différenciation = sécurité câblée + auditable + cœur propre.** C'est l'argument de vente, et
la section « safety model » du README en sera la vitrine.

---

## 5. MCP vs skill — pourquoi MCP

- Un **serveur MCP** marche pour *n'importe quel* agent (Claude Desktop/Code, Cursor, agents tiers,
  Aegis). C'est ce qu'exige « used by any AI agent ».
- Un **skill Claude** est *Claude-only* et ne sait pas parler à IBKR tout seul ; il ne peut
  qu'orchestrer des tools déjà exposés.
- Donc : **MCP d'abord**. Plus tard, un petit **skill Claude optionnel** (« trading-copilot ») pourra
  scripter les bons enchaînements par-dessus le MCP (`preview` puis `confirm`, vérifs de discipline).
  Pas l'inverse. Hors scope v1.

---

## 6. Architecture — topologie & process

```
   MACHINE DE L'UTILISATEUR
   ┌─────────────────────────────┐       ┌──────────────────────┐
   │  Client MCP (Claude         │ stdio │  ibkr-mcp (ce projet) │  TCP     ┌──────────────┐
   │  Desktop/Code, Cursor, …)   │ ◄───► │  process Python       │ ◄──────► │  IB Gateway  │
   │  — possède le clic humain   │       │  ib_async + FastMCP   │ 127.0.0.1│  (BYO, login │
   └─────────────────────────────┘       └──────────────────────┘  4002/01 │   par l'user)│
                                                                            └──────────────┘
```

- **Process unique Python**, serveur MCP **stdio** (FastMCP). Lancé par le client MCP
  (`uvx ibkr-mcp` ou config `claude_desktop_config.json`).
- Détient **une seule** instance `ib_async.IB()`. `ib_async.Watchdog` surveille le heartbeat et
  reconnecte avec un `clientId` déterministe.
- **Le serveur ne voit jamais les identifiants IBKR** — c'est le Gateway (BYO) qui les détient. Le
  serveur ne connaît que `host/port/clientId`. Gain de sécurité majeur, mis en avant au README.

---

## 7. Frontière de modules — le cœur extractible (enjeu de l'approche A)

```
ibkr_mcp/
  core/                  ← importe ib_async, JAMAIS mcp/FastMCP. = futur package `ibkr-core`
    models.py            ← dataclasses domaine — COPIE des shapes de backend/app/brokers/base.py d'Aegis
                            (Symbol, OrderRequest, OrderConfirmation, PositionInfo, AccountInfo,
                             OrderStatus, OrderSide, OrderType, AssetClass, BrokerHealth…)
    connection.py        ← IBKRConnection : possède l'IB(), Watchdog, connect/reconnect, health,
                            déduit paper/live du port, client INJECTABLE (testabilité sans Gateway)
    contracts.py         ← Symbol → ib_async Contract, qualifyContracts, résolution chaînes d'options
    market_data.py       ← quotes / bars / option chains (entitlement-aware)
    account.py           ← positions, account summary, P&L (read)
    orders.py            ← OrderRequest → ib_async Order ; place/cancel/modify ; mapping statut
    errors.py            ← code erreur IBKR → erreurs domaine typées
    safety/              ← LE différenciateur — politique pure, agnostique au transport
      guardrails.py      ← GuardrailPolicy : caps taille/notional, allowlist, gate paper/live
      idempotency.py     ← IdempotencyStore : dédup client_order_id (SQLite ~/.ibkr-mcp/state.db)
      killswitch.py      ← KillSwitch : fichier ~/.ibkr-mcp/KILL ou flag runtime
  mcp/                   ← FIN. importe core/, ne touche JAMAIS ib_async directement
    server.py            ← app FastMCP, enregistre tools/resources, câble config → core
    tools_read.py
    tools_write.py
    config.py            ← env/toml → CoreConfig + GuardrailPolicy
    formatting.py        ← objets domaine → contenu lisible par le LLM
  __main__.py            ← console_script `ibkr-mcp`
```

**Règle d'or (invariant architectural) :**

- `core/` importe `ib_async` mais **jamais** `mcp`/FastMCP.
- `mcp/` importe `core/` mais **jamais** `ib_async` directement.

Cette couture rend l'extraction de `core/` en package `ibkr-core` un `git mv` + `pyproject.toml`,
**pas une réécriture**. Un test d'architecture (import-linter ou test maison) garde l'invariant.

**Payoff concret :** `core/models.py` **copie** les dataclasses de `backend/app/brokers/base.py`
d'Aegis. Le cœur parle déjà la langue du port broker Aegis → le futur `IBKRBrokerAdapter` (qui
implémente l'ABC `BrokerAdapter`) se pose trivialement par-dessus `core/orders.py` + `core/connection.py`.
Les shapes étant petites et stables, la copie est assumée (pas de dépendance inverse Aegis→ce-projet).

---

## 8. Cycle de vie de connexion (BYO Gateway)

- **Démarrage** : connect au loopback (`127.0.0.1:4002` paper / `:4001` live). Si le Gateway n'est pas
  loggé/joignable → le serveur **tourne quand même** ; `ibkr_health()` renvoie `connected=false, reason`.
  Les tools nécessitant IB renvoient une erreur propre `BROKER_UNAVAILABLE` + marche à suivre. **Pas de crash.**
- **Reconnexion** : `ib_async.Watchdog` ; `clientId` déterministe (dérivé de la config), constant sur la vie
  du process (évite les collisions `clientId` — pattern issu des issues `ib_async`).
- **Restart quotidien IBKR** (~23:55 ET) : traité comme **panne planifiée** → `BROKER_UNAVAILABLE`
  plutôt que pendre. On ne *gère* pas le restart (BYO), on en gère le **symptôme** proprement.
- **2FA / login hebdo (dimanche 01:00 ET)** : job de l'utilisateur (BYO). On reporte l'état déconnecté.

---

## 9. Surface de tools MCP

| Tool | Type | Fait quoi | Garde-fous |
|---|---|---|---|
| `ibkr_health` | read | état connexion, paper/live, version Gateway, indices d'entitlement market-data | — |
| `get_account_summary` | read | cash, buying power, net liq, marge | — (pas d'abonnement requis) |
| `get_positions` | read | positions, avg cost, valeur, uPnL | dégrade si pas d'entitlement (prix=null + note) |
| `get_open_orders` | read | ordres en cours | — |
| `get_order_status` | read | statut d'un ordre | — |
| `get_executions` | read | fills + commissions depuis `since` | — |
| `get_quote` | read⚠ | top-of-book | **entitlement payant** → erreur claire si non souscrit |
| `get_historical_bars` | read⚠ | barres OHLCV | entitlement selon données |
| `get_option_chain` | read⚠ | strikes/expiries (`reqSecDefOptParams`) | entitlement options |
| `preview_order` | write-prep | valide + passe TOUS les garde-fous + `whatIfOrder` (marge/commission) → **preview lisible + `confirm_token` opaque court** lié au hash des params. **Ne place rien.** | tous (voir §10) |
| `confirm_order` | write | **seul** à placer. Exige le `confirm_token` d'un preview + un `client_order_id`. Re-vérifie kill-switch + guardrails. | idempotence + tous |
| `cancel_order` | write | annule un ordre | guardrails |
| `modify_order` | write | modifie un ordre (repasse par un preview) | guardrails |
| `set_killswitch` | control | armer/désarmer le kill-switch depuis la conversation | — |
| `get_killswitch_status` | control | lire l'état du kill-switch | — |

**Resources MCP** (optionnel, nice-to-have) : `ibkr://positions`, `ibkr://account/summary` — pour
donner le contexte portefeuille au LLM sans round-trip de tool.

⚠ = nécessite un abonnement market-data IBKR (cf. §11).

---

## 10. Modèle de sécurité — le différenciateur

**Principe conceptuel directeur :** *le serveur doit rester sûr même si le client MCP auto-approuve
chaque tool.* On ne contrôle pas le clic humain dans Claude Desktop → la sûreté ne peut PAS reposer
sur « le LLM devrait demander avant ». Elle est **câblée côté serveur**.

Distinction explicite :

- **Server-enforceable** (conçu ici, inviolable par le client) : les 7 garde-fous ci-dessous.
- **Client-dependent** (qu'on ne peut pas forcer) : le clic d'approbation humain réel. Le flux
  `preview→confirm` *offre* un point naturel d'approbation humaine si le client le surface, mais sa
  valeur de sécurité (params re-validés, token lié, idempotence) **tient même en auto-approbation**.

### Les 7 garde-fous imposés par le serveur

1. **Paper par défaut.** Live exige `IBKR_ALLOW_LIVE=true` **ET** port live (4001). Config=paper mais
   port=live → **refus de démarrer** (ceinture + bretelles).
2. **preview→confirm à deux appels.** Aucun tool unique ne décide *et* exécute. `confirm_order` exige
   le token d'un `preview_order`. Empêche le one-shot fat-finger ; force la remontée des params.
3. **Idempotence / dédup.** `client_order_id` **obligatoire** au confirm. `IdempotencyStore` (SQLite)
   enregistre `(client_order_id → résultat)`. Un retry renvoie le résultat enregistré, **jamais de
   double fill**. *La* propriété qui sauve de l'argent réel (un client LLM retry sur timeout).
4. **Caps taille & notional.** `MAX_ORDER_QTY`, `MAX_ORDER_NOTIONAL_USD`, vérifiés au preview **ET**
   re-vérifiés au confirm (le token peut être périmé / le marché a bougé).
5. **Allowlist tickers** (optionnelle). Si définie, seuls ces symboles sont traçables (lecture libre).
6. **Kill-switch.** Fichier `~/.ibkr-mcp/KILL` **ou** flag runtime. Présent → tous les writes rejetés
   `KILL_SWITCH_ENGAGED`. Vérifié au confirm. `touch ~/.ibkr-mcp/KILL` gèle le trading instantanément
   en pleine session, sans toucher au process.
7. **Rate limit** ordres/s (protège aussi des *pacing violations* IBKR).

### Flux d'un ordre

```
preview_order(AAPL, BUY, LMT, 100, 230)
   └─► validate_order + guardrails (caps, allowlist, paper/live, killswitch) + whatIfOrder (marge/commission)
   └─► {preview lisible, confirm_token=abc lié au hash(params), expire 60s}

confirm_order(token=abc, client_order_id="cli-42")
   └─► token valide & non périmé ? hash(params) cohérent ?
   └─► re-check guardrails + killswitch
   └─► dédup : "cli-42" déjà vu ? ── oui ─► renvoie l'OrderConfirmation enregistrée (pas de re-place)
                                   └─ non ─► place via core/orders ─► OrderConfirmation + enregistre (cli-42 → résultat)
```

### Auditabilité

Chaque écriture (preview accepté, confirm placé, rejet guardrail, kill-switch déclenché) est journalisée
en local (`~/.ibkr-mcp/audit.log`, JSON structuré). Le `IdempotencyStore` SQLite est la trace des ordres
réellement placés. (Pas d'audit cloud — ce n'est pas E9b.)

---

## 11. Données marché & entitlements (à énoncer, pas à résoudre)

- **Gratuit (sans abonnement)** : compte, positions (avg cost), ordres, exécutions.
- **Payant (abonnement IBKR)** : quotes live, barres historiques temps-réel, chaînes d'options.
- Conséquence design : les tools `read⚠` **dégradent proprement** si non entitlé — champ annoté
  `market_data_not_entitled` plutôt qu'une erreur cryptique IBKR (codes 354/10089). `get_positions`
  renvoie position + coût même sans prix live (uPnL=null + note).
- Le README documente le stack d'abonnement minimal (cf. ADR-2 §6 : ~16 $/mo streaming actions+options,
  0 $ si waiver commission).

---

## 12. Config & secrets

- **Env vars** (standard MCP) + `~/.ibkr-mcp/config.toml` optionnel.
- Clés : `IBKR_HOST`, `IBKR_PORT` (4002 paper / 4001 live), `IBKR_CLIENT_ID`, `IBKR_ALLOW_LIVE`,
  `IBKR_READ_ONLY`, `IBKR_MAX_ORDER_QTY`, `IBKR_MAX_ORDER_NOTIONAL_USD`, `IBKR_TICKER_ALLOWLIST`.
- **Aucun identifiant IBKR dans le serveur** — détenus par le Gateway (BYO).
- État local sous `~/.ibkr-mcp/` : `state.db` (idempotence), `KILL` (kill-switch), `audit.log`,
  `config.toml`.

---

## 13. Gestion d'erreurs

- Map codes IBKR (`errorEvent` ib_async) → erreurs domaine typées (`core/errors.py`) → tool errors MCP
  avec messages **actionnables**. Cas notables :
  - `1100` connexion perdue → `BROKER_UNAVAILABLE`
  - `200` pas de définition contrat / `201` ordre rejeté → message clair
  - `354` / `10089` market-data non souscrit → **dégradation** (cf. §11), pas une erreur fatale
  - `502` TWS injoignable → guidage « lance/logge ton Gateway »
  - `2104` / `2106` data farm OK → info, non bloquant
- Aucune erreur silencieuse : tout rejet (guardrail, killswitch, entitlement) renvoie une raison typée.

---

## 14. Stratégie de tests

- **Unit pur** sur `core/safety/` (guardrails, idempotency, killswitch) — 100 % testable sans IB.
  Cas critiques : double `confirm_order` même `client_order_id` → un seul fill ; token périmé rejeté ;
  cap dépassé rejeté au preview ET au confirm ; kill-switch armé bloque tout write ; allowlist.
- **Unit core** (`contracts`, `orders` mapping) avec un **client IB injecté** (stub) — `IBKRConnection`
  accepte une fabrique de client → testable sans Gateway.
- **Intégration** sur compte **paper** (port 4002), gated/manuel (nécessite creds réels). CI déterministe
  = stub uniquement.
- **Test d'invariant d'architecture** : `core/` n'importe jamais `mcp/FastMCP` (import-linter).

---

## 15. Relation Aegis & chemin d'extraction futur

- **Maintenant :** aucun couplage. Aegis reste sur son chemin E9b. Ce projet vit seul.
- **Plus tard (si besoin) :** extraire `core/` en package pip `ibkr-core`. Le futur `IBKRBrokerAdapter`
  d'Aegis (`backend/app/brokers/ibkr.py`, topology `LOCAL_AGENT`) fait `pip install ibkr-core` et
  implémente l'ABC `BrokerAdapter` par-dessus `core/connection.py` + `core/orders.py`. Comme
  `core/models.py` copie déjà les shapes du port Aegis, l'adapter est mince.
- **Breadcrumb Aegis (optionnel, non bloquant) :** une ligne côté `sprint-status.yaml` Aegis notant
  « connectique IBKR prototypée en OSS standalone `ibkr-mcp` ; E9b pourra consommer `ibkr-core` extrait ».
  À décider hors de ce projet.

---

## 16. Packaging / distribution / licence

- **Distribution :** `uvx ibkr-mcp` (run zéro-install, chemin MCP moderne) + `pip install ibkr-mcp`.
  `pyproject.toml`, console_script `ibkr-mcp`.
- **Python 3.11 / 3.12 épinglé** (`nest_asyncio`, dépendance d'`ib_async`, cassé en 3.13/3.14 — cf. ADR-2).
- **Licence MIT** + `DISCLAIMER.md` + bannière README : *not financial advice, no warranty,
  responsabilité de l'utilisateur, tester en paper d'abord*. Obligatoire pour un OSS qui laisse un LLM trader.
- **README** : quickstart (lance ton Gateway → configure → ajoute au `claude_desktop_config.json`),
  référence des tools, **section « safety model »** (la vitrine de différenciation).
- **Nom de publication :** `ibkr-mcp` est déjà pris plusieurs fois sur GitHub. Nom local = `ibkr-mcp` ;
  le nom de publication (ex. `ibkr-mcp-guarded`, `safe-ibkr-mcp`, `ironbroker-mcp`) sera tranché avant publication.
- **Langue :** spec interne en français (artefact de travail) ; **README et docs publiques en anglais**
  (portée communautaire) au moment de la publication.

---

## 17. Ce que ce design NE décide PAS

- Le schéma exact des payloads de tools (signatures précises, champs) — détaillé au plan d'implémentation.
- La forme exacte du `confirm_token` (JWT court vs opaque + table) — choisi à l'implémentation (défaut :
  opaque random + entrée SQLite avec hash params + TTL).
- Le nom de publication définitif (cf. §16).
- Le support multi-compte IBKR par utilisateur (plusieurs `clientId`) — évolution future, hors v1.
- Le transport HTTP/SSE distant — évolution future, hors v1.
- Le skill Claude « trading-copilot » par-dessus le MCP — évolution future, hors v1.

---

## 18. Références

- Aegis ADR-2 : `docs/architecture/ibkr-local-agent.md` (choix `ib_async`, contraintes 2FA/restart,
  market-data pricing) — repo privé Aegis.
- Aegis contrat broker : `backend/app/brokers/base.py` (shapes copiées dans `core/models.py`).
- `ib_async` : https://github.com/ib-api-reloaded/ib_async (fork maintenu d'`ib_insync` archivé).
- MCP / FastMCP : https://modelcontextprotocol.io , https://github.com/jlowin/fastmcp
- État de l'art (survol 2026-05-29) : Hellek1/ib-mcp, ArjunDivecha/ibkr-mcp-server,
  code-rabi/interactive-brokers-mcp, rcontesti/IB_MCP, et al.
- IBKR API : https://www.interactivebrokers.com/campus/ibkr-api-page/ibkr-api-home/
- IBC (automatisation login, hors scope v1) : https://github.com/IbcAlpha/IBC
