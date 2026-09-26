# Protocolo de experimentos — Spec 001

## 1. Reglas

1. Máximo **15 experimentos** (E01–E15). Cada uno responde **una** hipótesis.
2. Antes de correr: escribir la hipótesis en el YAML (`hypothesis:`). Después: escribir la conclusión (`conclusion:`) en la fila de `reports/experiments.csv`.
3. Todos se evalúan con los folds F1–F3 de `plan.md` §5. **Nunca** con el holdout.
4. Un experimento = un commit `exp(E07): xgboost con features de xG — val ll 0.9712`.
5. Parada anticipada (spec §6): nivel "Bueno" alcanzado en validación, o 4 experimentos seguidos sin mejorar el mejor log loss de validación en más de 0.002.
6. Si un experimento falla por un bug, se arregla y se vuelve a correr con el **mismo** ID (no cuenta como uno nuevo). Si falla porque la idea no sirve, se registra igual.

## 2. Backlog sugerido

El orden va de simple a complejo. E14 y E15 son libres: el agente elige qué probar según lo aprendido y justifica la hipótesis.

| ID | Modelo | Features | Usa cuotas | Hipótesis |
|---|---|---|---|---|
| E01 | Líneas base: frecuencias por liga, mercado `Avg` pre-cierre, Pinnacle cierre | — | ref. | Fija el piso (frecuencias) y el techo realista (mercado). |
| E02 | Regresión logística multinomial | solo Elo | no | Un Elo bien calibrado ya supera claramente a las frecuencias. |
| E03 | Poisson independiente (Maher) con decaimiento temporal | goles históricos | no | Modelar goles captura fuerza ofensiva/defensiva mejor que Elo. |
| E04 | Dixon-Coles con decaimiento ξ (búsqueda en {0.0005, 0.001, 0.0019, 0.003}) | goles históricos | no | Corregir marcadores bajos mejora la predicción de empates. |
| E05 | Logística multinomial | Elo + forma (goles, puntos, tiros) + calendario | no | La forma reciente aporta sobre Elo. |
| E06 | Logística multinomial | E05 + xG | no | xG es la señal más predictiva disponible. |
| E07 | XGBoost | E06 | no | Relaciones no lineales mejoran sobre la logística. |
| E08 | LightGBM + Optuna (≤ 40 trials, validación interna) | E06 | no | Ajuste de hiperparámetros exprime más al boosting. |
| E09 | Dixon-Coles sobre xG (ratings con xG en vez de goles) | xG históricos | no | xG es menos ruidoso que los goles para estimar fuerza. |
| E10 | Mejor modelo sin cuotas + calibración (isotónica vs temperature scaling) | — | no | Calibrar reduce log loss y ECE. |
| E11 | Blend de mejor ML + mejor Dixon-Coles (pesos en validación interna) | — | no | Modelos distintos se complementan. |
| E12 | Mejor ML | E06 + probabilidades del mercado pre-cierre (Shin) | **sí** | El mercado + nuestras señales > mercado solo. |
| E13 | Stacking: logística sobre `[p_modelo_sin_cuotas, p_mercado_avg]` | — | **sí** | Una mezcla aprendida corrige los sesgos del mercado (ej. favorito-longshot). |
| E14 | Libre | — | — | La decide el agente con base en E01–E13. |
| E15 | Libre | — | — | La decide el agente con base en E01–E14. |

## 3. Métricas por experimento

Por fold y promedio: **log loss** (principal), Brier multiclase, RPS, ECE (10 bins), accuracy. Más la simulación de apuestas de §5.

Esquema de `reports/experiments.csv`:

```
exp_id, name, hypothesis, model, feature_groups, uses_odds,
val_ll_f1, val_ll_f2, val_ll_f3, val_ll_mean, val_brier, val_rps, val_ece, val_acc,
bet_threshold, n_bets, roi_flat, roi_ci_low, roi_ci_high, clv_mean,
runtime_s, git_commit, timestamp, conclusion
```

Figuras por experimento en `reports/figures/{exp_id}_calibration.png` y `{exp_id}_roi.png`.

## 4. Regla para elegir al campeón

1. Candidatos: experimentos con `val_ece < 0.03` que en **ningún** fold sean peores que E02 por más de 0.01 de log loss (estabilidad).
2. Ganador: el de menor `val_ll_mean`.
3. Desempate por simplicidad: si otro candidato más simple está a menos de 0.001, gana el más simple. Orden de simplicidad: logística < Poisson/DC < blend < boosting < stacking.
4. Además se guarda el **mejor modelo sin cuotas** (`champion_no_odds`), que la API usa cuando no hay cuotas y que sirve como opinión independiente del mercado.
5. `make select` escribe `models/champion.json` con ambos y la justificación.

## 5. Simulación de apuestas

- Para cada partido y resultado: `EV = p_modelo × cuota − 1`.
- Se apuesta si `EV > umbral`. El umbral se elige en F1–F3 dentro de {0.02, 0.05, 0.08, 0.10} y queda **fijo** para el holdout.
- Máximo una apuesta por partido (la de mayor EV).
- Dos escenarios de cuotas:
  - **Realista:** `avg_odds` pre-cierre.
  - **Optimista:** `max_odds` pre-cierre (la mejor casa; anticipa el valor del comparador de la spec 002).
- Stakes: plano (1 unidad) y Kelly fraccional 25 % con tope de 2 % del bankroll.
- Reportar: nº de apuestas, % de aciertos, ROI, IC 95 % por bootstrap (2000 remuestreos), máximo drawdown, **CLV** medio frente a `psc_odds`.

## 6. Evaluación final (una sola vez)

`make holdout`:
1. Verifica que no exista `reports/HOLDOUT_USED.lock`.
2. Entrena campeón y `champion_no_odds` con 2014-15 … 2024-25.
3. Evalúa en 2025-26: campeón, `champion_no_odds`, E01 (frecuencias, mercado `Avg`, Pinnacle cierre) y E02.
4. Aplica la simulación de apuestas con el umbral ya fijado.
5. Escribe `reports/holdout_results.json`, figuras, y crea el `.lock` con fecha, commit y versión del modelo.
6. Determina el nivel alcanzado (Mínimo / Bueno / Excelente / No alcanzado) según spec §6.
