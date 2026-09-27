# Plan técnico — Spec 002

Extiende el repo de la spec 001 **sin romperlo**: misma arquitectura hexagonal, mismos comandos base, mismos estándares. Todo lo nuevo se agrega en módulos nuevos; lo existente solo se toca para inyectar dependencias o corregir bugs.

## 1. Stack nuevo

| Capa | Herramienta |
|---|---|
| Persistencia | SQLite + SQLAlchemy 2.0 (tipado) + Alembic (migraciones) |
| Cliente HTTP | `httpx` (ya está como dependencia de tests; pasa a dependencia normal) |
| Tareas programadas | APScheduler dentro del proceso de la API, **desactivado por defecto** (`ODDS_AUTO_REFRESH=false`) |
| Frontend | React 18 + TypeScript + Vite |
| Estado de servidor | TanStack Query |
| Estilos | Tailwind CSS |
| Gráficos | Recharts |
| Formularios | React Hook Form + Zod |
| Tests frontend | Vitest + React Testing Library; MSW para simular la API |
| Tipos de la API | Generados desde `/openapi.json` con `openapi-typescript` (sin escribir tipos a mano) |

## 2. Estructura (solo lo nuevo)

```
betting-ml/
├── configs/
│   └── bookmakers.yaml             # key, nombre, rol (reference|exchange|soft), accessible, source (api|manual)
├── migrations/                     # Alembic
├── data/app.db                     # SQLite (ignorado por git)
├── src/betting_ml/
│   ├── domain/
│   │   ├── entities.py             # + Bookmaker, OddsSnapshot, OddsQuote, Bet, BetStatus, BankrollSettings
│   │   ├── odds.py                 # + método de potencia; ajuste de comisión de exchange
│   │   ├── value.py                # evaluación de valor: fair prob, EV, veredicto, stake
│   │   ├── limits.py               # reglas de juego responsable (US6), puras y testeables
│   │   ├── clv.py                  # CLV de una apuesta frente a la cuota de referencia al cierre
│   │   └── ports.py                # + LiveOddsSource, OddsRepository, BetRepository, SettingsRepository, ResultsSource
│   ├── application/
│   │   ├── backtest_pinnacle.py    # US1
│   │   ├── refresh_odds.py         # US2
│   │   ├── compare_matches.py      # US3
│   │   ├── evaluate_manual_odds.py # US4
│   │   ├── manage_bets.py          # US5 + US6
│   │   └── settle_bets.py          # US5
│   ├── adapters/
│   │   ├── the_odds_api.py         # cliente + mapeo de eventos a match_id canónico + lectura de créditos
│   │   ├── sql/                    # modelos SQLAlchemy y repositorios
│   │   └── scheduler.py
│   └── api/routers/                # + odds, comparator, calculator, bets, settings, backtest
├── frontend/
│   ├── package.json
│   ├── vite.config.ts              # proxy /api → http://localhost:8000
│   ├── src/
│   │   ├── api/                    # cliente + tipos generados
│   │   ├── features/
│   │   │   ├── comparator/         # Hoy + Detalle de partido
│   │   │   ├── calculator/
│   │   │   ├── bets/               # Diario + Panel
│   │   │   ├── settings/
│   │   │   └── backtest/
│   │   ├── components/             # UI compartida (tabla de cuotas, badge de valor, aviso)
│   │   └── App.tsx                 # rutas con React Router
│   └── tests/
└── reports/
    ├── REPORT_002_backtest.md
    ├── backtest_002.json
    └── HOLDOUT_002_USED.lock
```

## 3. Backtest (US1)

- Reutiliza `matches.parquet` y los folds F1–F3 de la spec 001. El test es 2025-26 (`holdout.parquet`), con su **propio lock**.
- Justificación de reutilizar 2025-26: esta estrategia no tiene parámetros aprendidos del modelo, y el único hiperparámetro (umbral) se fija en F1–F3. Se registra en `decisions.md`.
- Referencia: Shin sobre `ps_odds_*` (Pinnacle **pre-cierre**; nunca `psc_` para decidir). CLV contra `psc_odds_*`.
- Escenarios de cuota: `max_odds_*` (optimista), `b365_odds_*` (realista), `avg_odds_*` (control: debería dar CLV ≈ 0 o negativo; si da muy positivo, sospechar un error).
- Variantes: sin filtro / con filtro `p_modelo ≥ p_justa` (usa predicciones out-of-fold del campeón y de `champion_no_odds`).
- Una apuesta por partido como máximo (la de mayor EV). Stake plano y Kelly 25 %.

## 4. The Odds API

- Endpoint: `GET /v4/sports/{sport_key}/odds?regions=eu,uk&markets=h2h&oddsFormat=decimal`.
- `sport_key` por liga en `configs/leagues.yaml` (`soccer_epl`, `soccer_spain_la_liga`, `soccer_germany_bundesliga`, `soccer_italy_serie_a`, `soccer_france_ligue_one`). Verificar los keys reales con `GET /v4/sports` en T004 y registrarlos.
- Costo: créditos = mercados × regiones por llamada → 5 ligas × 1 × 2 = **10 créditos por refresco completo**. Con 500/mes y reserva de 50 → ~45 refrescos al mes.
- Guardar siempre los headers de créditos. Reintentos con backoff solo en 5xx/timeout; nunca reintentar en 4xx.
- Emparejar eventos con `match_id` por liga + fecha (± 1 día) + equipos canónicos.
- Tests con respuestas JSON grabadas en `tests/fixtures/the_odds_api/` (sin red).

## 5. Base de datos

Tablas: `bookmakers`, `odds_snapshots` (id, fetched_at, source, credits_remaining), `odds_quotes` (snapshot_id, match_id, bookmaker_key, market, outcome, odds, last_update), `bets`, `settings`, `settings_history`.

- Índices: `odds_quotes(match_id, bookmaker_key, outcome)`, `bets(status, kind)`.
- Dinero con `Decimal` (columnas `Numeric(12,2)`), no `float`.
- Migración inicial con Alembic; `make db-upgrade`.

## 6. Reglas de dominio clave (con tests)

- `fair_probabilities(odds, method="shin"|"power")` → suma 1.
- Referencia: Pinnacle; si falta, Betfair Exchange ajustado por comisión (configurable, 5 % por defecto); si falta, `None` (no se recomienda nada).
- `verdict(ev, min_edge)` según el contrato.
- `kelly_stake(p, odds, bankroll, fraction, cap_pct)` nunca negativo, nunca mayor al tope.
- `clv(taken_odds, closing_fair_prob) = taken_odds × closing_fair_prob − 1`.
- `check_limits(bet, settings, month_loss)` → `ok` | `warning(...)` | `blocked(...)`. Pérdida mensual = suma de pérdidas netas de apuestas `real` liquidadas en el mes calendario de Lima.
- Subir el límite mensual aplica recién desde el mes siguiente (se guarda en `settings_history`).

## 7. Frontend

Páginas:
1. **Hoy** (`/`): selector de fecha y liga, tabla de partidos con la mejor cuota por resultado, EV coloreado, badge "el modelo coincide", botón "Actualizar cuotas" con créditos restantes.
2. **Partido** (`/match/:id`): tabla casas × resultados, mejor cuota resaltada, margen por casa, gráfico de la cuota de referencia en el tiempo, formulario rápido de calculadora.
3. **Calculadora** (`/calculator`): buscador de partido, resultado, casa (incluye casas manuales), cuota → veredicto, stake y botón "Registrar apuesta".
4. **Mis apuestas** (`/bets`): tabla filtrable, liquidación, y panel con KPIs (ROI, CLV medio, % CLV positivo, beneficio), curva de bankroll, barras por liga y casa. Filtro real/papel. Aviso fijo sobre el ruido del ROI.
5. **Backtest** (`/backtest`): resultados de US1 con sus IC.
6. **Ajustes** (`/settings`): bankroll, límites, Kelly, umbral.

Reglas:
- Todo texto de la UI en español; montos con la moneda de `settings` (PEN por defecto).
- Nunca se muestra una "recomendación" sin cuota de referencia.
- Diseño responsive; en el celular, la tabla de Hoy se muestra como tarjetas.
- Accesible: contraste AA, navegación con teclado en tablas y formularios.
- La API key para escribir se pide una vez y se guarda en `localStorage` (es una herramienta personal y local; documentarlo).

## 8. Comandos nuevos

| Comando | Qué hace |
|---|---|
| `make backtest-002` | Backtest en F1–F3 (repetible) |
| `make backtest-002-final` | Evaluación única en 2025-26 (lock) |
| `make db-upgrade` | Migraciones |
| `make odds` | Refresco manual de cuotas |
| `make settle` | Liquidar apuestas |
| `make web` | `npm run dev` del frontend |
| `make web-test` | Tests del frontend |
| `make dev` | API + frontend juntos |

Cada comando tiene su equivalente `uv run ...` / `npm ...` documentado en el README (la máquina del dueño no tiene `make`).

## 9. Configuración (`.env.example`, agregar)

```
ODDS_API_KEY=
ODDS_API_REGIONS=eu,uk
ODDS_MIN_CREDITS_RESERVE=50
ODDS_AUTO_REFRESH=false
ODDS_AUTO_REFRESH_TIMES=10:00,16:00
EXCHANGE_COMMISSION=0.05
APP_API_KEY=cambia-esto
DATABASE_URL=sqlite:///data/app.db
```

## 10. CI

Agregar al workflow: job de frontend (`npm ci`, `npm run lint`, `npm run typecheck`, `npm test`). Los tests de backend siguen sin red.
