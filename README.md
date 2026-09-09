# 🐊 YacaréPy — Monitoreo de Fuego y Deforestación | Sur del Alto Paraná, Paraguay

Sistema abierto de monitoreo ambiental que cruza cuatro fuentes satelitales
con latencias declaradas:

- **Fuego activo (horas):** NASA FIRMS VIIRS/MODIS, validación multisensor.
- **Perturbación de vegetación (semanas):** GFW Integrated Alerts (SQL oficial).
- **Pérdida de bosque anual (12-15 meses):** Hansen/UMD, filtro de bosque primario.
- **Priorización jurisdiccional:** whitelist oficial WDPA/IFL/KBA por distrito.

️ Visor: [visor.html](visor.html) · 📊 Datos: [alertas.geojson](alertas.geojson)

Cobertura: 7/9 distritos del sur del Alto Paraná (Tavapy y Dr. Raúl Peña
sin código oficial en la fuente GFW; monitoreados solo por fuego).
Los números declaran siempre su fuente y su latencia.