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

## 2026-10-23 — U03: Mis apuestas
- **Orden de lectura.**
  - Primero las cifras y los límites, después la tabla de apuestas (lo que se usa a diario) y al final los gráficos y la evidencia por mercado.
  - Antes la tabla estaba al fondo de la página.
  - La tabla se sigue mostrando aunque falle el resumen: las cifras de arriba y los gráficos de abajo son dos bloques separados.
- **Indicadores.** Las seis cajas pasan a ser una sola franja dividida. Las cifras se leen juntas: el CLV primero, y el ROI con su aviso de ruido.
- **Límite mensual (juego responsable).**
  - La pérdida del mes se muestra en grande.
  - La barra es azul mientras queda margen, ámbar desde el 80 % y roja en el límite. Antes era verde, y el verde queda reservado a cifras con signo positivo.
  - El límite y su bloqueo no cambian.
- **Acciones.** "Borrar" pasa de botón rojo relleno a botón discreto en rojo. Sigue siendo reconocible, pero ya no grita en cada fila.
- **Selecciones en español.** "over", "under", "yes", "no", "home", "draw" y "away" se muestran como "más de", "menos de", "sí", "no", "local", "empate" y "visita". Los códigos desconocidos se muestran tal cual. El test que leía "over 2.5" lee ahora "más de 2.5".
- **Gráficos.**
  - Las barras de CLV por liga y casa son verdes o rojas según el signo.
  - Sin apuestas liquidadas, los dos paneles vacíos (bankroll y CLV) se reducen a una sola línea.
- **Avisos.**
  - La nota "ROI con menos de 300 apuestas" pasa de caja informativa a texto junto al selector de tipo.
  - El texto de liquidación manual se mantiene íntegro.

## 2026-10-23 — U04: Calculadora, Backtest, Ajustes y Login
- **Calculadora.**
  - Es un flujo en tres pasos numerados: partido, evaluar la cuota y registrar.
  - Cada número se rellena con el acento al completar su paso, y lleva "Paso N" para los lectores de pantalla.
  - "¿El partido no aparece?" se mueve dentro del paso 1, que es donde surge la duda. Antes era una tarjeta aparte.
- **Fallo corregido (previo al rediseño).** Con la casa en el enlace (desde Top o Hoy), el selector "Casa" mostraba "Elige…" aunque el formulario sí tenía la casa, porque el valor llegaba antes que las opciones. Ahora se vuelve a fijar cuando carga la lista. Hay un test nuevo que lo cubre y que fallaba antes del arreglo.
- **Backtest.**
  - La conclusión, el nivel y la temporada de prueba son un resumen en cifras grandes.
  - El aviso de que la estrategia no le ganó al cierre es una franja ámbar con el texto íntegro.
  - Los márgenes ya no van en verde porque no son cifras con signo; la mejor paga contra el promedio sí lo es y conserva su color.
- **Ajustes.** Cada sección es una tarjeta: título y explicación a la izquierda, campos a la derecha. La explicación del límite recuerda que no se puede saltar desde la app y que el stake máximo avisa antes de una apuesta grande; no se cambió ninguna regla. "Guardar" va alineado a la derecha y la confirmación aparece a su lado.
- **Login.** Lleva la misma marca "b" que la cabecera, una tarjeta con el formulario y el botón a todo el ancho. Debajo hay una nota: "Acceso privado. Tras varios intentos fallidos se bloquea un momento.", que corresponde al límite de intentos de la spec 003.
- **Iconos.** Las páginas y los paneles ya no llevan iconos decorativos junto a los títulos. Los iconos se mantienen solo donde dan significado (estado, aviso, acción).

## 2026-10-23 — U05: revisión final (accesibilidad, móvil, estados y documentación)
- **Checkpoint 🔍 con `ml-reviewer`.** Veredicto: aprobado con observaciones. No hay regresiones de las reglas duras: EXPERIMENTAL siempre visible, nada de lenguaje de certeza, límite mensual intacto y nada de secretos en el navegador. Se corrigieron todas las observaciones salvo dos (ver abajo).
- **Teclado y lector de pantalla.**
  - Hay un enlace "Saltar al contenido" que aparece al recibir el foco y lleva a `<main>`.
  - Los iconos secundarios de la cabecera móvil van en una `nav` "Secundaria"; el enlace activo tiene fondo, no solo color.
  - Los botones "Registrar" de los mercados se anuncian con su selección (`aria-label`) y con `aria-expanded`.
  - Las tablas de mercados y de evidencia llevan un título oculto que describe sus columnas.
  - Los pasos completados de la Calculadora se anuncian como "Paso N (hecho)".
- **Contraste.** El borde de los campos tenía menos de 3:1 contra la tarjeta (WCAG 1.4.11) y se oscureció o aclaró según el tema. Un test nuevo lo calcula en los dos temas, igual que el del texto.
- **Color no como única señal.** En el gráfico de cuotas del Partido, las líneas del 1X2 tienen trazo continuo, punteado y discontinuo.
- **Móvil (390 px).**
  - Ninguna página tiene scroll horizontal.
  - Los botones pequeños, los selectores y los segmentados miden al menos 40 px de alto en pantallas táctiles.
  - Los nombres de equipo se apilan y cortan en dos líneas.
  - La navegación de escritorio entra desde `lg`, porque entre `md` y `lg` no cabía.
- **Partido.**
  - Una casa de referencia que paga la mejor cuota ya no queda oculta al plegar las demás. El botón dice cuántas faltan ("Ver N casas de referencia"), y hay un test que lo cubre.
  - "Volver" regresa a la página anterior si existe y, si no, a Hoy.
  - La tabla de casas se reinicia al cambiar de partido.
- **Detalles.**
  - La etiqueta EXPERIMENTAL sube a 12 px.
  - Las columnas del Top se alinean con `subgrid` en lugar de `contents`.
  - Se eliminó `teamHue`, que no se usaba.
- **No se cambia.**
  - Las tarjetas de consejos mantienen la misma altura en su fila aunque una abra el formulario: alinearlas pesa más.
  - "Borrar" sigue sin confirmación. Es el comportamiento de la spec 002, solo está permitido antes del inicio y no forma parte de un rediseño visual.
