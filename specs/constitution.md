# Constitución del proyecto — betting-ml

Principios que **no se negocian**. Toda spec, plan, tarea y línea de código debe respetarlos. Si una tarea choca con un principio, gana el principio y se documenta el conflicto en `specs/001-prediction-model/decisions.md`.

## I. Cero fuga de información (no leakage)

1. Toda variable (feature) de un partido jugado en la fecha `d` se calcula **solo** con información disponible **antes** del inicio de ese partido.
2. Las cuotas de cierre (`PSCH/PSCD/PSCA`, `AvgCH`, `MaxCH`, etc.) **nunca** se usan como feature. Solo sirven como referencia de evaluación (línea base del mercado y CLV).
3. Como feature solo se permiten cuotas *pre-cierre* (`AvgH/AvgD/AvgA`, `PSH/PSD/PSA`, `B365H/...`).
4. Los estadísticos del propio partido (goles, tiros, xG del partido) jamás entran como feature del mismo partido.
5. Hay tests automáticos que verifican los puntos 1–4 (ver `plan.md` §7).

## II. Holdout sagrado

1. La temporada **2025-26** es el conjunto de prueba final (*holdout*). Vive en un archivo separado.
2. Ningún experimento, ajuste de hiperparámetros, selección de variables ni elección de modelo puede mirar el holdout.
3. El holdout se evalúa **una sola vez**, al final, con el modelo campeón ya elegido y las líneas base. Queda registrado en `reports/HOLDOUT_USED.lock`. Si ese archivo existe, el código se niega a volver a evaluar sobre el holdout.

## III. Validación temporal

Nada de `train_test_split` aleatorio ni `KFold` mezclado. La validación es *walk-forward* por temporada (ventana expansiva). Ver `plan.md` §5.

## IV. Honestidad en los resultados

1. Todos los experimentos (buenos y malos) quedan registrados en `reports/experiments.csv`.
2. Las métricas de rentabilidad (ROI) siempre se reportan con intervalo de confianza (bootstrap) y número de apuestas.
3. Si el modelo no le gana al mercado, el informe lo dice claramente. No se "maquillan" resultados.

## V. Arquitectura limpia (hexagonal)

1. El dominio (`domain/`) no importa pandas-IO, requests, FastAPI ni nada de infraestructura.
2. Las fuentes de datos, almacenamiento y registro de modelos se acceden por **puertos** (interfaces `Protocol`) implementados por **adaptadores**.
3. La API (FastAPI) solo llama a casos de uso de `application/`; no contiene lógica de negocio ni de ML.

## VI. Reproducibilidad

1. Semillas fijas (`SEED=42`) en todo proceso aleatorio.
2. Cada experimento se define en un YAML en `configs/experiments/` y se puede volver a correr con un solo comando.
3. Los datos crudos descargados se guardan tal cual en `data/raw/` con fecha de descarga; nunca se editan a mano.

## VII. Calidad de código

1. Python ≥ 3.11, type hints en todo el código público.
2. `ruff` (lint + format) y `pytest` deben pasar antes de cada commit.
3. Cobertura mínima: 80 % en `domain/` y `ml/features/`; 60 % global.
4. Funciones pequeñas, nombres en inglés en el código; documentación y reportes en español.
5. Sin secretos en el repo: todo va en `.env` (hay un `.env.example`).

## VIII. Commits

1. Un commit por tarea completada, con *Conventional Commits* (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`, `exp:` para experimentos).
2. Nunca se suben al repo: `data/`, modelos binarios pesados (`models/*.joblib`), `.env`.
3. El agente **no hace push**; eso lo hace el dueño del repo.

## IX. Juego responsable

1. El software no incluye funciones que incentiven perseguir pérdidas (martingala, subir stakes tras perder, "recuperar").
2. Los límites de juego responsable (spec 002, US6) no se pueden desactivar ni saltar desde la API o el frontend; solo editando la configuración a mano.

## X. Respeto a términos de uso

1. No se hace scraping de casas de apuestas sin una spec que lo justifique y revise sus términos.
2. Las APIs de terceros se usan dentro de sus límites (créditos, frecuencia) y sus claves viven solo en `.env`.

## XI. Evidencia antes de construir

1. Ninguna estrategia de apuesta se expone en el frontend sin un backtest que la respalde (puerta de la spec 002, US1).
2. Si la evidencia es negativa, se detiene la construcción y se informa al dueño.

## XII. Seguridad e integridad

1. Toda ruta de la API exige autenticación, salvo las explícitamente públicas (`/health` y el login).
2. Ningún secreto se guarda en el navegador ni en el repo; las contraseñas solo se guardan como hash Argon2id.
3. Los datos de dinero y de límites tienen restricciones en la base, control de concurrencia y una auditoría de solo inserción.
4. Todo control de seguridad tiene tests negativos, y el CI de seguridad (dependencias y secretos) debe estar en verde antes de cada commit a la rama principal.
5. En producción, la aplicación no arranca con una configuración insegura.

## XIII. Consejos honestos

1. Todo consejo muestra su probabilidad, su precio y su porqué con datos verificables (cada número es trazable en la evidencia del análisis).
2. Nunca usa lenguaje de certeza ("segura", "fija", "garantizada", "no falla" o similares).
3. Una apuesta probable pero mal pagada se presenta como tal: probabilidad alta no es lo mismo que valor.

_Enmienda agregada por la spec de análisis de partido (2026-10-21, rama `Sebastian`, allí numerada XII y spec 003); renumerada XIII y spec 004 al integrarse (2026-10-22)._
