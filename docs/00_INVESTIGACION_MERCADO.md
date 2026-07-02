# Investigación de mercado — TerraQuantum (2026-07-02)

Investigación con fuentes verificables sobre viabilidad comercial. Base factual para
toda decisión de producto. NO asumir un comprador distinto sin re-investigar.

## Veredicto ejecutivo

Existe un negocio, pero es **más chico y distinto del imaginado**:
1. La junior sin geofísico NO compra software DIY de inversión — compra **respuestas**
   (contrata consultores por días o el survey con inversión incluida).
2. El mercado chileno de juniors son **76 empresas** (Cochilco 2024) — es un piloto, no
   un mercado.
3. El precedente del desarrollador solo existe (Res2DInv/Loke, Zond/Kaminsky) y su techo
   fue: **negocio de nicho unipersonal estable o absorción por un grande**. Ninguno se
   volvió "empresa de software industrial".

## 1. Product-Market Fit

- **El dolor es real**: perforación diamantina US$150–600/m → pozo de 300–500 m =
  US$50k–300k. Errar el pozo es el error más caro de una junior. La inversión 3D para
  targeting ES práctica estándar del workflow.
- **PERO ya está resuelto**: Seequent vende acceso diario barato exactamente para este
  caso — *Consultants Daily* (Leapfrog Geo **US$156/día**, tope US$2.340/mes), *Oasis
  montaj Pay & Go* diario, *VOXI* por consumo (Azure). Contratistas (Abitibi, Viridien)
  entregan survey+inversión como paquete. SimPEG/UBC gratis (exige Python).
- **La verdadera competencia NO es la licencia de US$11k** — es "llamar al consultor de
  siempre" (~US$3–5k por campaña, criterio experto incluido).
- **Usuario vs comprador**: en la junior decide el gerente de exploración (geólogo, no
  geofísico). No quiere software, quiere la respuesta. **El usuario natural del producto
  es el CONSULTOR geofísico**, no la minera.
- **Foso defensivo**: técnico = casi ninguno (física pública, SimPEG gratis). El único
  foso real: **robustez + simplicidad + precio + servicio local en español**. Foso de
  ejecución, no de tecnología.

## 2. Precios (la cancha real)

| Opción | Precio |
|---|---|
| Leapfrog Works (asiento anual) | US$11.010/año |
| Leapfrog Geo consultores (Consultants Daily) | US$156/día, tope US$2.340/mes |
| Oasis montaj Pay & Go | diario (precio no público) |
| VOXI | por consumo (créditos Azure) |
| Zond (ZondGM3D) | licencia perpetua c/dongle, pocos miles € una vez |
| SimPEG / UBC-GIF | gratis (requiere expertise Python) |

- Financiamiento de juniors cayó 12% en 2024 (mínimo en 5 años) → software es lo primero
  que se corta. Precio ancla del mercado: **US$156/día**.
- **Precio realista TQ**: a consultores US$50–150/mes o US$300–800/proyecto; a juniors
  SOLO por proyecto (US$500–1.500), nunca suscripción anual (gasto episódico).
- Freemium (malla chica/marca de agua) = único canal de marketing gratuito realista.

## 3. Costos operativos (para un dev solo)

- **Cómputo**: inversiones CPU-bound de minutos → servidor dedicado 8–16 núcleos
  (US$40–100/mes) con cola de trabajos basta. No se necesita GPU. Es lo barato.
- **CAC (lo caro)**: venta B2B minera = confianza, ciclos 6–18 meses, ferias caras.
  Canal viable para uno solo: contenido técnico + LinkedIn + tier gratis + boca a boca
  de consultores.
- **Soporte = riesgo personal #1**: 20 h/semana de soporte para un cliente de US$50/mes
  es quiebra. **La robustez no es una feature: es la estructura de costos.**

## 4. Riesgos

- **Confidencialidad (el más subestimado)**: los datos de survey de una junior listada
  son price-sensitive. Subirlos a la nube de una persona natural = barrera de compliance
  seria. Mitigación: **versión desktop/local primero** (la arquitectura actual ya casi
  lo es), nube después.
- **Legal**: mundo NI 43-101/JORC → firma una Persona Calificada (QP). Producto =
  *decision support* con disclaimers; el reporte honesto (B1/B2/B3) es un activo legal.
- **Riesgo Seequent**: ya tienen tiers baratos; pueden aplastar el nicho con precio.
  Defensa: ser irrelevante para ellos (nicho LatAm/español/pequeña minería).
- **Precedentes**: Loke (Res2DInv) solo → estándar mundial 2D → Aarhus → Seequent.
  Zond = negocio unipersonal sostenible con licencias perpetuas baratas. Ambos eran PhDs
  del dominio con credibilidad académica.

## 5. Tamaño de mercado

- Chile: 87 exploradoras, **76 juniors**, 223 proyectos (Cochilco 2024). 10% de captura
  a US$1.500/proyecto ≈ US$11k/año. **Chile = piloto.** Mercado real = LatAm +
  consultores hispanohablantes + juniors chicas globales.

## 6. Camino de entrada recomendado (en orden)

1. **Consultores geofísicos LatAm como primer cliente** (no las mineras): ya pagan
   US$156/día, expertos (menos soporte), uso repetido, venden POR ti a las juniors.
2. **Desktop/local primero, nube después** — resuelve confidencialidad + costo infra.
3. **Servicio productizado**: tú + TerraQuantum vendiendo la inversión HECHA a juniors
   chilenas (US$2–4k/proyecto). El software no necesita ser perfecto (lo operas tú),
   aprendes el mercado real, generas casos y contactos, financia el desarrollo.

## Advertencias

- Mayor barrera: credibilidad (estudiante 2º año sin track record en industria que
  compra por confianza). Mitigación: casos públicos (validaciones DO-27/Raglan/Laguna
  del Maule = usar como material), partnership académico, empezar por servicio.
- Prerequisito de TODOS los caminos: que el producto cumpla "siempre funciona" (plan de
  robustez). No es opcional.

## Fuentes principales

Seequent Consultants Daily / Pay&Go / VOXI (seequent.com) · Leapfrog pricing
(alternatives.co) · Cochilco Catastro Exploración 2024 (cochilco.cl) · Costos
perforación (platinumdiamonddrilling.ca, S&P) · Presupuestos juniors (mining.com/S&P) ·
Res2DInv→Aarhus→Seequent (LinkedIn Søltoft, seequent.com) · Zond (zond-geo.com) · Nube
en minería (nridigital, darktrace) · San Nicolás cost-effectiveness (ResearchGate).
