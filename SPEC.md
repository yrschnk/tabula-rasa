# Tabula Rasa — Архитектура и инструкция реализации (MVP)
> Tabula Rasa — персональная когнитивная память (второй мозг) для агентов и человека.
> Спецификация для разработки и вайбкодинга. Каждый слой расписан до уровня
> конкретных задач, схем, промптов и псевдокода. На основе этого файла можно кодить.

---

## 1. Цель и гипотеза

**Цель MVP:** выбить максимальный скор на публичных бенчмарках памяти (LongMemEval, LOCOMO) и доказать, что spreading activation по графу даёт прирост поверх обычного поиска.

**Гипотеза (измеримая):**
> Spreading activation по графу концептов даёт лучший контекст для ответа, чем плоский полнотекстовый поиск по тем же данным.

Проверка: один датасет в двух режимах (`fts5` vs `fts5 + activation`); разница в скоре = доказательство.

---

## 2. Зафиксированные решения

| Вопрос | Решение |
|---|---|
| Источник данных | Формат бенчмарков (реплики: text + speaker + session_id + timestamp) |
| Источник правды | **SQLite**; markdown — проекция для Obsidian (только просмотр) |
| Структура wiki | Гибрид: концепт-хабы + атомарные факты |
| Граф | LLM-links + co-occurrence: **record-рёбра сильные + session-рёбра слабые (×0.3)** |
| Векторы | **Обязательны сразу после baseline** (sqlite-vec): recall + A.U.D.N + канонизация концептов |
| Ingest | Пачкой по сессии, Haiku на extract, кэш по content_hash |
| Канонизация концептов | Embedding-кластеризация (на тех же векторах) + алиасы |
| Атрибуция | Поле `attributed_to` (user/assistant) на факте — для assistant/preference вопросов |
| Knowledge-update | Версионирование `valid_from`/`valid_to` |
| Retrieval | One-shot сборка контекста, структурный вывод |
| Dedup/Update | **Гибрид:** content-hash (точные дубли) + A.U.D.N через LLM (похожие) |
| Грейдинг | **Оба судьи через config:** Claude (dev) / GPT-4o (финал, как офиц. LongMemEval) |
| Abstention | **Да, явная логика** «не знаю» при пустой/слабой активации |
| Изоляция бенча | Свежий стор памяти на каждый вопрос (у каждого своя история ~115k токенов) |

---

## 3. Принципы

1. **SQLite — канон, markdown — проекция.** Бенч читает SQLite, не парсит markdown.
2. **Память — процесс:** факт живёт create → reinforce → supersede → archive.
3. **Не хранить сырьё в памяти:** raw иммутабелен, в память идут сжатые факты.
4. **Вход абстрактен от источника:** личный ввод и бенч проходят один ingest.
5. **Время — first-class:** `timestamp` + `valid_from`/`valid_to` на каждом факте.
6. **Всё пакетно и программно.**
7. **Namespacing:** стор работает в namespace (для изоляции бенч-инстансов).

---

## 4. Поток данных (end-to-end)

```
INPUT (turn: text + speaker + session_id + timestamp)
   ↓
RAW LAYER (JSON, иммутабельно)
   ↓
INGEST (LLM): compress → atomic facts + entities + предложенные links
   ↓
DEDUP/UPDATE: content-hash → (если похоже) A.U.D.N через LLM
   ↓
VERSIONING: valid_from/valid_to при UPDATE/DELETE
   ↓
CANONICAL STORE (SQLite): facts + edges + FTS5
   ↓
GRAPH BUILD: wikilinks + co-occurrence → рёбра с весами
   ↓
PROJECTION: markdown wiki (Obsidian-совместимый)
   ─────────────────────────────────────────────
QUERY:
   вопрос → FTS5 (seed) → spreading activation (expand, фильтр по времени)
   → abstention-check → сборка контекста (token budget)
   → one-shot LLM → структурный ответ {answer, sources, activated, confidence}
```

---

## 5. Слой за слоем (детально)

### 5.1 Вход (Input)

Единица — **реплика (turn)**:
```json
{
  "raw_id": "uuid4",
  "text": "документы для ВНЖ готовы, нужно приехать в Барселону",
  "speaker": "user",
  "session_id": "sess_2026_06_03",
  "timestamp": "2026-06-03T14:20:00Z",
  "source": "cli | longmemeval | locomo | import",
  "namespace": "default"
}
```
- `tabula add "текст"` → одна запись, `source=cli`, `timestamp=now`, `speaker=user`.
- Бенч-загрузчик разворачивает датасет в поток таких записей, своя `namespace` на инстанс.

**Задачи:**
- [ ] `models.py`: dataclass `RawTurn`.
- [ ] Валидация и автозаполнение (uuid, now, speaker по умолчанию).

### 5.2 Raw Layer

Иммутабельный JSON-слой.
```
raw/{namespace}/{session_id}/{raw_id}.json
```
- Только append. Источник для реингеста и аудита.

**Задачи:**
- [ ] `raw_store.py`: `write_raw(turn)`, `read_raw(raw_id)`, `iter_session(session_id)`.

### 5.3 Ingest (LLM compress + extract)

**Пачкой по сессии** (не по реплике) — один extract-вызов на всю сессию. Дешёвая модель (**Haiku**) на extract, дорогая только на reconstruct. Кэш по `content_hash` (повтор не извлекаем заново). Вывод строго JSON.

Извлекаем:
- **facts** — атомарные, но **самодостаточные** утверждения (включать контекст: «приехать в Барселону **для ВНЖ**», а не «приехать в Барселону»)
- **attributed_to** — кто заявил факт (`user`/`assistant`) — критично для assistant/preference вопросов
- **entities** — люди/места/организации
- **concept** — основная концепт-страница факта (имя сверяется с реестром концептов, см. ниже)
- **links** — предложенные связи концепта с другими
- **temporal** — дата/относительное время → нормализовать в ISO (опираясь на timestamp реплики)

**Канонизация концептов (embedding-кластеризация):**
Чтобы «ВНЖ»/«residency»/«вид на жительство» не плодили разные узлы:
1. При создании концепта считаем embedding его имени.
2. Ищем существующий концепт namespace с близким embedding (cosine > порога).
3. Нашли → переиспользуем канон-имя, новое пишем в `aliases`. Не нашли → новый концепт.
Реестр концептов + алиасы хранится в таблице `concepts`.

**Задачи:**
- [ ] `ingest.py`: `extract_facts_for_session(turns) -> list[FactCandidate]` (Haiku, JSON parse, валидация).
- [ ] Кэш по `content_hash` (skip уже извлечённого).
- [ ] Ретраи и жёсткий JSON-парсинг (на невалидный JSON — повтор «верни только JSON»).
- [ ] `concepts.py`: `canonicalize(name, ns) -> canon_name` (embedding-сверка + алиасы).

### 5.4 Dedup / Update (гибрид A.U.D.N)

Для каждого `FactCandidate`:
```
1. content_hash = sha256(normalize(content))
   если точный дубль существует → reinforce (strength += δ, reinforce_cnt++) → стоп
2. similar = поиск похожих внутри namespace, топ-k (k=5):
      - векторный поиск (sqlite-vec) по эмбеддингу кандидата  ← ловит перефразы/противоречия
      - ИЛИ concept-scoped: все факты того же концепта (их немного)
   если similar пуст → ADD (новый факт, valid_from=ts, valid_to=NULL)
3. иначе → LLM A.U.D.N (кандидат + similar): вернуть операцию
     ADD    → новый факт
     UPDATE → старому valid_to=ts, status=superseded; новый valid_to=NULL
     DELETE → старому valid_to=ts, status=archived (противоречие)
     NOOP   → reinforce ближайшего, ничего не добавлять
```
Промпт A.U.D.N — см. Приложение A.2.

**Задачи:**
- [ ] `dedup.py`: `normalize(text)`, `content_hash(text)`.
- [ ] `update.py`: `resolve_operation(candidate, similar) -> Op` (LLM).
- [ ] `update.py`: применение операций к стору (atomic transaction).

### 5.5 Canonical Store (SQLite)

DDL:
```sql
CREATE TABLE facts (
  fact_id        TEXT PRIMARY KEY,     -- uuid4
  namespace      TEXT NOT NULL,
  content        TEXT NOT NULL,
  content_hash   TEXT NOT NULL,
  concept        TEXT NOT NULL,        -- канон-имя концепт-страницы
  attributed_to  TEXT,                 -- 'user' | 'assistant' (кто заявил факт)
  entities       TEXT,                 -- JSON list
  timestamp      TEXT,                 -- ISO: когда заявлено/произошло
  valid_from     TEXT NOT NULL,
  valid_to       TEXT,                 -- NULL = актуально
  strength       REAL DEFAULT 1.0,
  reinforce_cnt  INTEGER DEFAULT 0,
  source_raw_id  TEXT,
  status         TEXT DEFAULT 'active',-- active|superseded|archived
  created_at     TEXT
);
CREATE INDEX idx_facts_ns_concept ON facts(namespace, concept);
CREATE INDEX idx_facts_hash       ON facts(namespace, content_hash);
CREATE INDEX idx_facts_valid      ON facts(namespace, valid_to);

CREATE TABLE edges (
  namespace   TEXT NOT NULL,
  src_concept TEXT NOT NULL,
  dst_concept TEXT NOT NULL,
  type        TEXT NOT NULL,           -- 'link' | 'cooccur'
  weight      REAL DEFAULT 0.0,
  updated_at  TEXT,
  PRIMARY KEY (namespace, src_concept, dst_concept, type)
);

CREATE TABLE concepts (
  namespace   TEXT NOT NULL,
  name        TEXT NOT NULL,           -- канон-имя
  aliases     TEXT,                    -- JSON list синонимов
  embedding   BLOB,                    -- эмбеддинг имени (для канонизации)
  PRIMARY KEY (namespace, name)
);

CREATE VIRTUAL TABLE facts_fts USING fts5(
  content, concept,
  content='facts', content_rowid='rowid',
  tokenize='porter'
);
-- триггеры синхронизации facts_fts с facts (insert/update/delete)

-- Векторный индекс (sqlite-vec), обязательный шаг после baseline:
-- CREATE VIRTUAL TABLE facts_vec USING vec0(fact_id TEXT, embedding FLOAT[N]);
```

**Задачи:**
- [ ] `store.py`: init schema, триггеры FTS.
- [ ] CRUD: `add_fact`, `reinforce`, `supersede`, `archive`, `get_fact`.
- [ ] `search_fts(query, namespace, k)`.
- [ ] `upsert_edge(src,dst,type,Δweight)`.
- [ ] `namespace` во всех запросах.

### 5.6 Граф

Источники рёбер (три, чтобы граф не был разреженным):
1. **LLM-links** (`type=link`): из `links`, предложенных LLM при ingest. Базовый вес `w_link=1.0`.
2. **record co-occurrence** (`type=cooccur_rec`): концепты из одной реплики → **сильное** ребро, инкремент `+0.5`.
3. **session co-occurrence** (`type=cooccur_sess`): концепты в пределах одной сессии → **слабое** ребро, инкремент `+0.15` (×0.3 от record). Уплотняет граф, даёт activation по чему течь.

Итоговый вес для активации:
```
weight(A,B) = clamp(
    link_weight
  + log1p(rec_count)  * w_rec      # w_rec ≈ 0.3
  + log1p(sess_count) * w_sess,    # w_sess ≈ 0.09 (0.3 × 0.3)
  0, 1 )
```
(все веса тюнятся на dev-сабсете)

**Задачи:**
- [ ] `graph.py`: `update_edges_for_turn(concepts, links)` — record-рёбра при ingest.
- [ ] `graph.py`: `update_session_edges(session_concepts)` — session-рёбра в конце сессии.
- [ ] `graph.py`: `load_graph(namespace) -> networkx.Graph` (суммарные веса).
- [ ] `tabula sync` — пересборка рёбер из фактов (на случай ручных правок).

### 5.7 Wiki Projection (markdown, Obsidian-совместимый)

Генерируется из SQLite. Гибрид: концепт-страница (хаб) + атомарные факты (пункты с якорями `^id`).
```
wiki/{namespace}/
  index.md          -- каталог
  overview.md       -- синтез (LLM, опционально)
  log.md            -- append-only лог операций
  concepts/<Concept>.md
  entities/<Entity>.md
```
Шаблон страницы — см. Приложение B.

**Задачи:**
- [ ] `projection.py`: `render_concept_page(concept, namespace)`.
- [ ] `projection.py`: `rebuild_wiki(namespace)` (полная пересборка).
- [ ] `log.py`: append операций ingest/update.
- [ ] Проекция отключаема флагом (на бенч-прогонах не нужна — экономит время).

### 5.8 Поиск (Retrieval search)

- **Baseline:** FTS5 (porter, BM25-ранкинг) — даёт ~86%.
- **Обязательно после baseline:** векторный индекс (`sqlite-vec`) + **RRF-fusion** FTS5+vector. Это +9pp (до ~95%) и условие топ-скора. Те же эмбеддинги переиспользуются в A.U.D.N и канонизации концептов.

**Задачи:**
- [ ] `search.py`: `fts_search(query, ns, k)` (baseline).
- [ ] `search.py`: `vector_search(query, ns, k)` (sqlite-vec) — обязательный шаг.
- [ ] `search.py`: `rrf_fuse(fts_results, vec_results)` — Reciprocal Rank Fusion.
- [ ] `embeddings.py`: единый провайдер эмбеддингов (факты, концепты, запросы).

### 5.9 Spreading Activation

Параметры (дефолты, тюнить на бенче):
```
DECAY      = 0.5      # затухание на хоп
MAX_HOPS   = 2
THRESHOLD  = 0.2      # отсечка активации
TOP_SEED   = 5        # сколько узлов-точек входа из FTS5
TOP_NODES  = 15       # сколько активированных концептов в контекст
```
Алгоритм:
```python
def activate(question, ns):
    seeds = fts_search(question, ns, TOP_SEED)          # [(concept, score)]
    G = load_graph(ns)
    activation = {c: s for c, s in seeds}               # нормализовать score→0..1
    frontier = list(activation.items())
    for hop in range(MAX_HOPS):
        next_front = {}
        for node, act in frontier:
            for nbr, w in G[node].items():
                inc = act * DECAY * w
                if inc < THRESHOLD: continue
                activation[nbr] = max(activation.get(nbr,0), inc)
                next_front[nbr] = activation[nbr]
        frontier = next_front.items()
    return top_n(activation, TOP_NODES)                 # [(concept, activation)]
```
**Задачи:**
- [ ] `activation.py`: реализовать `activate()`.
- [ ] Параметры из config.
- [ ] Режим `fts5_only` (без активации) для сравнительного бенча.

### 5.10 Retrieval / Query (one-shot + abstention)

```python
def query(question, ns, as_of=None, mode="activation"):
    if mode == "fts5":
        concepts = fts_search(question, ns, TOP_NODES)
    else:
        concepts = activate(question, ns)

    facts = collect_facts(concepts, ns, as_of)   # актуальные (valid_to IS NULL
                                                 # или valid_to > as_of), фильтр по времени
    # ABSTENTION
    if not facts or max_activation(concepts) < ABSTAIN_THRESHOLD:
        return {"answer": "Информации об этом нет.",
                "sources": [], "activated_nodes": [c for c,_ in concepts],
                "confidence": 0.0, "abstained": True}

    context = build_context(facts, token_budget=TOKEN_BUDGET)  # сорт по activation*strength
    answer = llm_reconstruct(question, context, as_of)        # one-shot, см. A.3
    return {"answer": answer.text,
            "sources": answer.used_fact_ids,
            "activated_nodes": [c for c,_ in concepts],
            "confidence": answer.confidence,
            "abstained": False}
```
Промпт reconstruct (с разрешением сказать «нет данных») — Приложение A.3.

**Задачи:**
- [ ] `retrieval.py`: `collect_facts`, `build_context`, `llm_reconstruct`.
- [ ] Abstention-порог `ABSTAIN_THRESHOLD` в config.
- [ ] Структурный вывод (dataclass `QueryResult`).
- [ ] `as_of` поддержка для temporal-вопросов.

---

## 6. Бенчмарки

### Датасеты
| Датасет | Меряет | Источник |
|---|---|---|
| **LongMemEval-S** | 500 Q, 5 способностей (IE, MR, KU, TR, ABS) | [github.com/xiaowu0162/LongMemEval](https://github.com/xiaowu0162/LongMemEval) |
| **LOCOMO** | многосессионная память + время | [github.com/snap-research/locomo](https://github.com/snap-research/locomo) |

Типы вопросов LongMemEval: single-session-user (70), single-session-assistant (56), single-session-preference (30), multi-session (133), knowledge-update (78), temporal-reasoning (133). Abstention-вопросы помечены (id с `_abs`).

**Dev-сабсет (обязателен для итераций):** ~50 вопросов, **стратифицированно по типам** (по несколько каждого). Все параметры (DECAY/THRESHOLD/веса рёбер/TOKEN_BUDGET/ABSTAIN_THRESHOLD) тюнятся на нём. Полный прогон 500 — только на вехах. Перед запуском — оценка стоимости (токены × цена).

### Раннер (ключевая логика)
```
для каждого question_instance в датасете:
    ns = f"bench_{question_id}"
    reset_store(ns)                      # изоляция: своя память на вопрос
    для каждой session в haystack_sessions (в порядке дат):
        для каждого turn в session:
            ingest(turn, ns)             # проекцию wiki выключить
    pred = query(question, ns, as_of=question_date)
    grade = judge(question, gold_answer, pred.answer, qtype)  # LLM-judge
    записать в results
агрегировать: overall + by_type + abstention_accuracy + latency
```
Грейдинг — Приложение A.4. Судья выбирается config-флагом: `claude` (dev) / `gpt-4o` (финал).

### Команды
```bash
tabula bench --dataset longmemeval-s --judge claude
tabula bench --dataset longmemeval-s --judge gpt-4o --mode activation
tabula bench --compare fts5,activation --dataset longmemeval-s
```

### Метрики
```
overall_accuracy
accuracy_by_type        # IE / MR / KU / TR / ABS
abstention_accuracy     # отдельно: верно ли отказался
latency_p50 / p95
cost_estimate           # токены × цена
```
Сравнение режимов `fts5` vs `activation` на одном датасете = доказательство гипотезы.

**Задачи:**
- [ ] `bench/datasets/longmemeval.py`: загрузка + разворот в turns + `as_of`.
- [ ] `bench/datasets/locomo.py`.
- [ ] `bench/runner.py`: цикл с изоляцией namespace.
- [ ] `bench/judge.py`: Claude/GPT-4o judge (config).
- [ ] `bench/metrics.py`: агрегация + by_type + abstention.
- [ ] `bench/results/`: JSON + сводная таблица в stdout.

### Где фиксировать результаты
| Площадка | Что | Зачем |
|---|---|---|
| **Papers With Code** | результат к задаче LongMemEval | публичный рейтинг |
| **GitHub README** | таблица + код воспроизведения | доверие |
| **Hacker News** | Show HN + цифры + демо | трафик |
| **arxiv** | короткий paper при топ-скоре | академ. признание |

---

## 7. Стек

| Что | Инструмент |
|---|---|
| CLI | Typer |
| Канон-стор | SQLite + FTS5 |
| Граф | NetworkX (из SQLite) |
| Wiki-проекция | Markdown (Obsidian-совместимый) |
| LLM (система) | Claude API |
| LLM-судья | Claude / GPT-4o (config) |
| Векторы (позже) | sqlite-vec / Qdrant |
| Обёртка (позже) | MCP Python SDK |

Всё локально. Python 3.11+. Конфиг — `config.py` / `.env`.

---

## 8. Структура проекта

```
memory-os/
  raw/                          # иммутабельное сырьё (по namespace/session)
  wiki/                         # markdown-проекция (по namespace)
  db/memory.db                  # SQLite (канон)
  memory/
    models.py                   # RawTurn, FactCandidate, QueryResult, Op
    config.py                   # параметры, ключи, пороги
    raw_store.py
    store.py                    # SQLite CRUD + FTS
    ingest.py                   # extract_facts (LLM)
    dedup.py                    # hash, normalize
    update.py                   # A.U.D.N
    graph.py                    # build/load граф
    activation.py               # spreading activation
    search.py                   # fts (+ vector позже)
    retrieval.py                # query: collect/build/reconstruct/abstain
    projection.py               # SQLite → markdown
    log.py
    llm.py                      # обёртки Claude/OpenAI, JSON-парсинг, ретраи
    cli.py                      # Typer
    mcp_server.py               # MCP-сервер: 4 инструмента + server instructions
  prompts/
    mcp_rubric.md               # decision rubric для авто-захвата (отдаётся агенту)
  bench/
    runner.py
    judge.py
    metrics.py
    datasets/{longmemeval.py,locomo.py}
    results/
  prompts/                      # все промпты отдельными файлами (см. Приложение A)
  tests/
```

---

## 9. CLI

```bash
tabula add "текст"                      # ingest → store → (опц.) sync wiki
tabula ask "вопрос" [--as-of DATE] [--mode fts5|activation]
tabula sync [--namespace NS]            # пересборка графа + wiki из SQLite
tabula status [--namespace NS]          # концепты, факты, размер графа
tabula bench ...                        # см. раздел 6
```

---

## 10. Порядок реализации (вехи, без сроков)

1. **Скелет:** `models`, `config`, `store` (schema+FTS+concepts), `llm` (Claude/Haiku+JSON+ретраи).
2. **Запись:** `ingest`(пачкой по сессии, Haiku, кэш) → `dedup` → `update`(ADD only) → `store`. CLI `add`.
3. **Поиск-baseline:** `search.fts` + `retrieval`(mode=fts5, one-shot). CLI `ask --mode fts5`.
4. **Граф+активация:** `graph`(record+session рёбра), `activation`, `retrieval`(mode=activation).
5. **Векторы (обязательно):** `embeddings`, `vector_search`, `rrf_fuse`; канонизация концептов; similar для A.U.D.N.
6. **Версионирование:** полный A.U.D.N (UPDATE/DELETE + valid_from/to).
7. **Abstention:** пороги + ветка «не знаю».
8. **Бенч:** `datasets/longmemeval` → `runner`(изоляция ns) → `judge`(claude) → `metrics`. Прогон на dev-сабсете (~50).
9. **Сравнение:** `--compare fts5,activation`. Зафиксировать прирост.
10. **Финал-скор:** полный прогон 500, judge=gpt-4o, тюнинг параметров.
11. **Проекция/Obsidian:** `projection` + `sync` (для просмотра, не для бенча).
12. **MCP-сервер:** `mcp_server` (4 инструмента) — личное использование в Claude Code/Codex/Cursor.

---

## 10.4 LLM-backend (pluggable)

LLM нужен в 4 точках: extract (ingest), A.U.D.N, reconstruct (ответ), judge (бенч). Плюс эмбеддинги. Бэкенд выбирается в конфиге — единый интерфейс, реализации подменяются.

### Принцип: zero-config из коробки
**Backend по умолчанию = MCP sampling.** Пользователь подключает MCP-сервер к Claude Code/Codex/Cursor — и всё работает: ни API-ключа, ни Ollama, ни внешней инфры. LLM-роль выполняет хост-агент. Всё остальное — через конфиг.

### Бэкенды
| Backend | Роль | Стоимость | Примечание |
|---|---|---|---|
| **MCP sampling** | **дефолт**, личное использование | бесплатно (подписка хоста) | хост-агент = LLM; ноль инфры. `tabula_add` вызывается изредка (батч по сессии) → подтверждения не мешают |
| **API** (Claude/OpenAI) | бенч, через конфиг | платно (см. ниже) | воспроизводимо, нужно для лидерборда |
| **Ollama (локально)** | приватный офлайн, через конфиг | бесплатно | качество ниже |

> Bulk-ingest с подтверждениями — проблема только для бенча (500 инстансов), а бенч и так на API. Для личного использования sampling полностью годится.

### Эмбеддинги (тоже zero-config)
Всегда **локально**, без внешней инфры: fastembed (ONNX, без PyTorch), модель качается автоматически при первом запуске. sqlite-vec для индекса. Не зависит от выбранного LLM-backend.

Выбор модели через конфиг:
| Профиль | Модель | Размер | Назначение |
|---|---|---|---|
| **personal (дефолт)** | `paraphrase-multilingual-MiniLM-L12-v2` | ~470 МБ | **RU + EN**, личное использование |
| bench | `bge-small-en-v1.5` | ~130 МБ | английский, легче, воспроизводимость |
| quality | `multilingual-e5-large` | ~2.2 ГБ | максимум качества, многоязычно |

> Важно: размерность вектора зависит от модели → `facts_vec` пересоздаётся при смене модели (хранить имя модели в метаданных стора; при несовпадении — переиндексация).

### Интерфейс
```python
class LLMBackend:
    def complete(prompt, model_hint) -> str        # extract / AUDN / reconstruct
    def embed(texts) -> list[vector]                # всегда локально по умолчанию
# config: backend = "mcp_sampling" (default) | "api" | "ollama"
#         модели по точкам только для api/ollama (extract=haiku, reconstruct=sonnet)
```

### Стоимость (приблизительно, порядок величины)
**Бенч LongMemEval-S (500 Q), API:**
```
Extract (Haiku, ~57M токенов истории):  ~$60-70  (разово, кэшируется на диск)
A.U.D.N / эмбеддинги:                   ~$6-11
Reconstruct (Sonnet):                   ~$15-20
Judge:                                  ~$10-20
Полный прогон:  ~$90-150 ; повтор без ingest (кэш): ~$30 ; dev-сабсет ~50: ~$8-15
```
**Личное использование:** `add` — доли цента, `ask` — 1-3 цента/вопрос → ~единицы $/мес (или $0 на sampling/Ollama).

**Задачи:**
- [ ] `llm.py`: интерфейс `LLMBackend`; **`SamplingBackend` (дефолт)** + `ApiBackend` + `OllamaBackend`.
- [ ] `mcp_server.py`: проброс MCP sampling в `SamplingBackend`.
- [ ] `embeddings.py`: вшитая локальная embed-модель (fastembed), авто-загрузка при первом запуске.
- [ ] Кэш extract на диск (для дешёвых повторных прогонов бенча).
- [ ] Config: `backend` (default=mcp_sampling) + модели по точкам только для api/ollama.

---

## 10.5 Интеграция с агентами (MCP-сервер)

Цель: пользоваться памятью не только для бенча, но и для личных нужд — чтобы Claude Code / Codex / Cursor писали и читали память.

**Решение: MCP-сервер** поверх готового ядра. Универсален для всех MCP-клиентов. Добавляется без переписывания (CLI и namespace уже заложены).

### Инструменты MCP
```
tabula_add(text, namespace?)        → ingest реплики/заметки в память
tabula_ask(question, namespace?)    → query → структурный ответ
tabula_search(query, namespace?)    → сырые факты без LLM-реконструкции (дёшево)
tabula_status(namespace?)           → концепты, размер графа
```

### Namespaces для личного использования
- `personal` — общая личная память по умолчанию
- `proj:<repo>` — память по конкретному проекту/репозиторию
- `bench_<id>` — изолированные стораы бенча (не пересекаются с личными)

Тот же namespace-механизм, что и для изоляции бенча → личные данные и бенч физически разделены.

### Как подключается
- Claude Code / Codex / Cursor: запись MCP-сервера в конфиг клиента (stdio).
- В режиме MCP используется **MCP sampling** (LLM-backend = хост-агент) → личное использование без API-ключа.

---

### Авто-захват: как сделать память «почти автоматической» без хуков

**Проблема.** Голый MCP — это набор инструментов. Агент вызовет `tabula_add`/`tabula_ask` только если *догадается*. Без подсказок пользователю пришлось бы пинать агента каждый раз («запиши это», «загляни в память»). Это плохой UX.

**Решение (модель mem0): server instructions + decision rubric.**
MCP-протокол позволяет серверу отдавать клиенту **инструкции**, которые хост-агент получает автоматически в начале работы (тот самый блок «MCP Server Instructions», который агент видит в системном контексте). Мы используем это, чтобы задать агенту правила поведения с памятью — тогда он ходит в память **сам**, без пинков.

#### Что сервер передаёт агенту (decision rubric)
```
Ты подключён к Tabula Rasa — персональной памяти пользователя.
Правила использования (выполняй проактивно, без напоминаний):

1. В НАЧАЛЕ сессии / новой темы:
   вызови tabula_ask("<текущая задача/тема>") чтобы поднять релевантный контекст.

2. КОГДА пользователь сообщает факт о себе, решение, предпочтение,
   договорённость, важную деталь проекта:
   вызови tabula_add("<факт>") — кратко, своими словами, по-русски/по-английски как сказал пользователь.

3. КОГДА пользователь спрашивает о прошлом ("что мы решали", "что я говорил про X"):
   вызови tabula_search / tabula_ask ПЕРЕД ответом, не выдумывай.

4. НЕ записывай: секреты, токены, пароли, разовый шум.
5. НЕ переспрашивай разрешение на каждый вызов — действуй, это ожидаемое поведение.
```
Текст рубрики — конфигурируемый (файл `prompts/mcp_rubric.md`), чтобы тюнить поведение.

#### Уровни автоматизации (от простого к полному)
| Уровень | Механизм | Авто? | Клиенты | Когда |
|---|---|---|---|---|
| **L1 — Tools only** | 4 MCP-инструмента | ручной (пинать) | все | базовый |
| **L2 — Tools + rubric (наш дефолт)** | + server instructions | **почти авто** | все MCP-клиенты | MVP |
| **L3 — Hooks** | SessionStart/End/PostToolUse | полностью авто | только Claude Code | опция позже |

**В MVP реализуем L2.** Это даёт «работает само» в любом клиенте без сложной настройки. L3 (хуки) — отдельный опциональный пакет для тех, кому нужен 100% бесшумный захват именно в Claude Code.

#### Подробно про каждый инструмент в авто-режиме
- **`tabula_ask(question, namespace?)`** — агент зовёт в начале темы и перед ответами о прошлом. Внутри: retrieval (FTS5+vectors+activation) → reconstruct → структурный ответ. LLM-роль через sampling (бесплатно).
- **`tabula_add(text, namespace?)`** — агент зовёт при появлении факта/решения. Внутри: полный ingest-пайплайн (extract → dedup A.U.D.N → store → эмбеддинг). Идемпотентно: дубликаты отсекаются по hash, так что повторный вызов безопасен.
- **`tabula_search(query, namespace?)`** — дешёвый поиск сырых фактов без reconstruct. Для случаев, когда агенту нужны факты, а ответ он сформулирует сам.
- **`tabula_status(namespace?)`** — диагностика: число концептов, фактов, размер графа, текущая embed-модель.

#### Выбор namespace в авто-режиме
- По умолчанию `personal`.
- Если сервер запущен в контексте репозитория (есть git-root) → `proj:<repo-name>` автоматически, чтобы память проекта не смешивалась с личной.
- Пользователь может переопределить через переменную окружения/конфиг клиента.

### Замечания
- На бенче MCP не используется — раннер ходит в ядро напрямую.
- Запись из агента идёт через тот же ingest-пайплайн (compress → dedup → store), что гарантирует одинаковое качество памяти для бенча и личного использования.
- L2 не гарантирует 100% срабатывания (агент может пропустить вызов) — это компромисс за кроссклиентность и простоту. Для гарантии — L3 (хуки).

**Задачи:**
- [ ] `mcp_server.py`: MCP Python SDK, stdio, 4 инструмента выше.
- [ ] `mcp_server.py`: отдавать **server instructions** (decision rubric) из `prompts/mcp_rubric.md`.
- [ ] `SamplingBackend`: проброс LLM-вызовов в хост через MCP sampling.
- [ ] Авто-выбор namespace (`personal` / `proj:<repo>` по git-root).
- [ ] Идемпотентность `tabula_add` (hash-дедуп на входе).
- [ ] README: как прописать сервер в Claude Code / Codex / Cursor (пример JSON-конфига).
- [ ] (L3, позже, опц.) пакет хуков SessionEnd/SessionStart/PostToolUse для Claude Code.

---

## 11. Открытые вопросы (решать на тюнинге, не блокеры)

- Параметры активации (DECAY/THRESHOLD/HOPS) — подбор на dev-сабсете LongMemEval.
- TOKEN_BUDGET — сколько фактов влезает в one-shot без потери качества.
- ABSTAIN_THRESHOLD — баланс precision abstention vs ложные отказы.
- Ingest пачкой (по реплике vs по сессии) — компромисс цена/качество извлечения.
- Концепт-нормализация: как сводить «ВНЖ»/«residency»/«вид на жительство» к одному узлу (алиасы в frontmatter + LLM-канонизация имени концепта при ingest).

---

## 11.5 Риски и митигации

| # | Риск | Серьёзность | Митигация (заложена в спеку) |
|---|---|---|---|
| 1 | Потеря атрибуции (кто сказал) → провал assistant/preference (86 Q) | Высокая | Поле `attributed_to` + в extract-промпте |
| 2 | Стоимость ingest (LLM × реплики × 500) | Высокая | Пачкой по сессии + Haiku + кэш по hash |
| 3 | Over-splitting фактов теряет смысл | Средняя | Требование самодостаточности факта + `source_raw_id` |
| 4 | Фрагментация концептов рушит граф | Высокая | Embedding-канонизация + реестр `concepts` + алиасы |
| 5 | A.U.D.N не ловит перефразы → провал knowledge-update (78 Q) | Высокая | Векторный поиск похожих (sqlite-vec) + concept-scoped |
| 6 | Разреженный граф → activation не работает | Высокая | record-рёбра + session-рёбра (×0.3) |
| 7 | FTS5-only потолок ~86% | Высокая | Векторы обязательны: RRF-fusion (+9pp) |
| 8 | Активация добавляет шум → падает precision | Средняя | Режим `--compare`, тюнинг THRESHOLD на dev |
| 9 | One-shot не тянет multi-session (133 Q) | Средняя | Ставка на activation за один проход; abstention калибровать |
| 10 | Дорогой полный прогон при отладке | Средняя | Dev-сабсет ~50 стратифицированный |

### Мета-риск (зафиксирован честно, решение отложено)
Граф строится **внутри одного инстанса = одна короткая беседа**. На таком графе spreading activation может дать **мизерный прирост** — наш главный дифференциатор рискует не проявиться именно на LongMemEval.

Лидеры (agentmemory 95%) выигрывают **гибридным поиском**, а не графом. Поэтому:
- **Для топ-скора** опираемся на hybrid search (FTS5 + векторы + RRF) — как у всех.
- **Ценность activation** честно измеряем через `--compare`. Если на стандартном бенче прирост мал — фиксируем это и **позже** решаем про cross-session конфигурацию (слить много инстансов в один большой namespace, где activation реально нужна). Решение отложено до первых цифр.

Вывод: две цели (высокий скор vs уникальность) разведены сознательно. Бенч закрываем гибридом, дифференциатор измеряем отдельно и не выдаём желаемое за действительное.

---

## 12. Приложение A — Промпты (черновики)

### A.1 Extract (compress) — пачкой по сессии
```
Ты — модуль памяти. Извлеки из сессии атомарные факты.
Правила:
- один факт = одно утверждение;
- факт ДОЛЖЕН быть самодостаточным: включай контекст
  (не "приехать в Барселону", а "приехать в Барселону для оформления ВНЖ");
- сохрани конкретику (числа, даты, имена);
- attributed_to = кто заявил факт (user/assistant);
- concept выбирай из списка существующих, если подходит (иначе новый).
Существующие концепты namespace: {concept_registry}
Верни СТРОГО JSON:
{
  "facts": [
    {"content": "...", "concept": "КанонИмя", "attributed_to": "user|assistant",
     "entities": ["..."], "timestamp": "ISO или null"}
  ],
  "links": [["КонцептA","КонцептB"], ...]
}
Сессия (реплики с ролями и временем):
{session_turns}
```

### A.2 A.U.D.N (update)
```
Новый факт-кандидат и список похожих существующих фактов.
Выбери операцию для кандидата:
- ADD: семантически нового нет
- UPDATE: кандидат обновляет/уточняет существующий (старый устарел)
- DELETE: кандидат противоречит существующему (старый неверен)
- NOOP: уже есть, ничего не менять
Верни JSON: {"op":"ADD|UPDATE|DELETE|NOOP","target_fact_id": "id|null","reason":"..."}
Кандидат: {candidate}
Похожие: {similar_list_with_ids_and_timestamps}
```

### A.3 Reconstruct (ответ, one-shot, с abstention)
```
Ответь на вопрос ТОЛЬКО на основе фактов ниже. Учитывай даты.
Если в фактах нет ответа — верни ровно: {"answer":"Информации об этом нет.","confidence":0,"used":[]}
Иначе верни JSON: {"answer":"...","confidence":0..1,"used":["fact_id",...]}
Текущая дата (as_of): {as_of}
Вопрос: {question}
Факты (id · дата · текст):
{facts}
```

### A.4 Judge (грейдинг)
```
Оцени, верен ли ответ модели по смыслу и по времени (не по точному совпадению строк).
Для abstention-вопросов: правильно, если модель отказалась/сказала что данных нет.
Верни JSON: {"correct": true|false, "reason":"..."}
Вопрос: {question}
Эталон: {gold}
Ответ модели: {pred}
Тип вопроса: {qtype}
```

---

## 13. Приложение B — Шаблон концепт-страницы (Obsidian)

```markdown
---
title: {Concept}
aliases: {aliases}
updated: {date}
links: {wikilinks}
---

# {Concept}

## Актуальные факты
- ({fact_id} · {date}) {content} ^{fact_id}

## История (superseded/archived)
- ({fact_id} · {valid_from} → {valid_to}) {content}
```

---

## 14. Источники и вдохновение

- [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — wiki-структура, ingest/query/lint
- [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) — compress, token budget, hybrid search, 95.2%
- [mem0](https://arxiv.org/pdf/2504.19413) — extraction + A.U.D.N (Add/Update/Delete/Noop)
- [SamurAIGPT/llm-wiki-agent](https://github.com/SamurAIGPT/llm-wiki-agent) — build_graph, детекция противоречий
- [Memory as Metabolism](https://arxiv.org/abs/2604.12034) — raw buffer → scheduled coherence
- [lucasastorian/llmwiki](https://github.com/lucasastorian/llmwiki) — MCP, SQLite FTS5
- [Spreading Activation for KG-RAG](https://arxiv.org/abs/2512.15922) — параметры активации
- [LongMemEval](https://github.com/xiaowu0162/LongMemEval) — формат, типы вопросов, грейдинг
```
