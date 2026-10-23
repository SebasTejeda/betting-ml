# Decisiones — spec 005 (rediseño UX/UI)

## 2026-10-23 — U00: diagnóstico y dirección
- Revisión en Chrome de todas las páginas, en los temas oscuro y claro, contra una instancia de prueba (base desechable). Los hallazgos están en `spec.md` §1.
- El dueño elige la dirección **fintech sobrio** (frente a "deportivo moderno" y "terminal de datos") y el **tema oscuro por defecto**.
- **Paleta.** Neutros grafito con un único acento azul sobrio; verde y rojo solo para cifras con signo; ámbar para lo experimental. Contraste calculado (OKLCH → sRGB → luminancia WCAG) para 16 pares por tema: todos ≥ 4,5:1. El menor es 4,96 (positivo sobre su fondo suave, en claro).

## 2026-10-23 — U01: sistema de diseño y piloto (Análisis)
- **Tokens.** Todo color sale de `index.css`. Se añade `--track` para el fondo de barras y medidores, que antes era un gris suelto. El contraste se comprueba en `design.test.ts` con 17 pares por tema (se suman texto sobre `secondary`, `muted` y `accent`, y el acento sobre la tarjeta y el fondo).
- **Tipografía.** Inter con cifras tabulares (`.num`) donde los números cambian o se alinean en columnas. Etiquetas pequeñas en mayúsculas (`.eyebrow`) para separar las secciones sin añadir cajas.
- **Superficies.** Las tarjetas tienen borde y no anillo, y solo llevan sombra en el tema claro. Las tablas tienen cabeceras pequeñas y apagadas y filas más altas. Los estados vacíos son una línea de texto y ya no una caja punteada dentro de otra caja.
- **Color con significado.** Las barras de probabilidad pasan de verde a azul, porque el verde queda reservado a cifras con signo positivo (EV, CLV, beneficio). Los avatares de equipo pasan a ser monogramas neutros: el color por equipo no aportaba información y competía con el acento.
- **Navegación.** Las tareas diarias van primero (Hoy, Top, Análisis, Calculadora, Mis apuestas). Backtest y Ajustes van detrás de un separador. En móvil, la barra inferior tiene 5 columnas y no 7; Backtest y Ajustes pasan a la cabecera como iconos con `aria-label`.
- **Análisis (piloto).**
  - El marcador muestra el 1X2 del modelo con cifras grandes y una barra repartida, y los goles esperados de cada equipo.
  - Orden de lectura: el partido primero, después los consejos, la forma y los mercados.
  - Las tarjetas de consejo tienen la misma altura y el botón siempre abajo.
  - Se mantienen todos los textos honestos (XII), el aviso EXPERIMENTAL y el "sin cuota".
- **Pendiente.** No se pudo verificar el móvil en Chrome porque la ventana no se reduce a 400 px. Queda para U05 (con las DevTools o un viewport de prueba).

## 2026-10-23 — U02: Hoy, Top del día y Partido
- **Datos para revisar.** La base de prueba se llenó con la respuesta grabada de la Premier (`tests/fixtures/the_odds_api/soccer_epl_odds.json`), movida a la fecha de hoy y en tres snapshots con pequeñas variaciones. No se hizo ninguna llamada a The Odds API ni se gastaron créditos.
- **Filtros.** Ya no van en una caja: son una barra sobre la página separada por una línea, para que el peso visual lo lleven los resultados.
- **Hoy.**
  - Cada tarjeta tiene, en orden: la liga y la hora, los equipos, y una tabla de tres columnas con la mejor cuota (cifra grande), la casa, la cuota justa y el EV.
  - El margen se resume en una línea.
  - Las acciones van abajo en todas las tarjetas: "Analizar" y "Cuotas por casa" (este enlace es nuevo, porque antes solo se llegaba al partido pulsando los nombres).
- **Top del día.**
  - Una sola lista ordenada dentro de una tarjeta, con cabecera de columnas fija y filas alineadas. Antes era una tarjeta por fila.
  - En móvil, cada fila muestra sus propias etiquetas.
  - El aviso EXPERIMENTAL es una franja compacta con el texto íntegro.
- **Partido.**
  - El marcador es igual que el de Análisis: la probabilidad justa 1X2 en grande con una barra repartida, y el modelo como segunda opinión.
  - Las probabilidades pasan de tres cajas a una tabla: resultado, cuota justa, justa y modelo.
  - La tabla de casas muestra primero las accesibles desde Perú; las de referencia se despliegan con un botón (`aria-expanded`). En el partido de prueba eran 39 filas de golpe.
  - La mejor cuota se marca con el acento azul y ya no en verde, porque el verde queda solo para cifras con signo.
  - La calculadora rápida va junto a la tabla de casas y se adapta a su contenedor (consulta de contenedor) en lugar de a la pantalla.
- **1X2 compartido.** Los tonos de Local, Empate y Visita y la barra repartida viven en `lib/outcome.ts` y `components/OutcomeSplit.tsx`, y los usan Análisis y Partido. El empate pasa del ámbar (que significa experimental) a un gris neutro, también en el gráfico.
- **Tablas.** Las cabeceras de fila (`scope="row"`) ya no heredan el estilo en mayúsculas de las cabeceras de columna.
- **Test.** El test de Partido comprueba ahora las probabilidades en la tabla "Referencia y modelo" y localiza la tabla de casas por su nombre. La información comprobada es la misma.
