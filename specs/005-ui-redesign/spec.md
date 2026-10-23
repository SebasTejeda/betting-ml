# Spec 005 — Rediseño UX/UI del frontend

Pedido del dueño (2026-10-23): "no me gusta para nada como se ve todo; mejora el diseño con buenas prácticas de UX/UI". Dirección elegida por el dueño: **fintech sobrio**, con el **tema oscuro por defecto**.

## 1. Diagnóstico (revisión en Chrome, 2026-10-23)

1. **Sin jerarquía.** Todo es una tarjeta del mismo peso, con títulos pequeños y texto de 12–13 px. En Análisis, el pronóstico pesa lo mismo que un aviso de créditos.
2. **Texto explicativo que compite con los datos.** Hay párrafos legales y técnicos en gris diminuto en cada sección.
3. **Tablas con ruido.** Cada fila repite "sin cuota", "EV —", "Solo información" y "Registrar", y la probabilidad usa el verde de "bueno": sugiere valor donde solo hay probabilidad.
4. **Composición desequilibrada.** Hay columnas medio vacías junto a otras muy largas, y estados vacíos con una caja dentro de otra caja.
5. **Aspecto genérico.** Es la plantilla por defecto de shadcn: un acento verde chillón, avatares iguales y un logo de icono genérico.
6. **Navegación.** Siete entradas planas. En móvil, la barra inferior tiene 6 columnas para 7 enlaces.

## 2. Principios

- **Jerarquía por importancia.** Primero el dato que responde a la pregunta de la página (probabilidades, resultado, saldo); después el detalle; al final las notas.
- **Cifras primero.** Números grandes y tabulares; etiquetas pequeñas y discretas.
- **El color tiene significado.** Un acento neutro (azul sobrio) para la interfaz y la probabilidad. Verde y rojo solo para resultados con signo (EV, CLV, beneficio). Ámbar solo para lo experimental y los avisos. Nunca el color solo: siempre con texto, icono o signo.
- **Divulgación progresiva.** Las explicaciones largas quedan a un clic ("Cómo leer esto"). Los avisos que protegen al usuario (juego responsable, EXPERIMENTAL, sin certezas) se quedan siempre visibles.
- **Menos cajas.** Secciones separadas por espacio y tipografía, no por bordes anidados.
- **Accesibilidad.** Contraste WCAG AA verificado por cálculo en los dos temas, foco visible, objetivos táctiles de al menos 40 px en móvil y `prefers-reduced-motion` respetado.

## 3. Restricciones (no negociables)

- **Constitución IX y XIII.** Nada que empuje a apostar: sin urgencia, sin colores de "ganador" en la probabilidad y sin lenguaje de certeza. El aviso de juego responsable y la etiqueta "EXPERIMENTAL — solo papel" siguen visibles donde estaban.
- **CSP de la spec 003.** Nada externo (la fuente Inter va empaquetada) y nada de scripts inline.
- **Ningún secreto en el navegador.** Solo el tema en `localStorage`.
- **Comportamiento intacto.** Los textos y roles en los que se apoyan los tests y la accesibilidad no cambian sin motivo, y los tests de frontend siguen en verde. No hay cambios en la API ni en el backend.

## 4. Criterio de éxito

| Nivel | Condición |
|---|---|
| Mínimo | Sistema de diseño nuevo y la página Análisis rediseñada, aprobados por el dueño. |
| Bueno | Todas las páginas rediseñadas con el mismo sistema, en escritorio y en móvil. |
| Excelente | Lo anterior + revisión final sin hallazgos de accesibilidad (contraste calculado, teclado, lector de pantalla en los flujos clave). |
