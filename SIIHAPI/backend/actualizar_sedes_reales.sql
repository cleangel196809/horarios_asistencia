-- ============================================================================
-- Actualiza las direcciones de 'sedes' con la informacion real del sitio
-- oficial del Politecnico Internacional (footer institucional), 2026-09-03.
-- No renombra las sedes (columna 'nombre'), solo corrige 'direccion'.
-- ============================================================================

UPDATE sedes SET direccion = 'Calle 73 N° 10-45, Bogotá'
 WHERE nombre = 'Sede Calle 73';

UPDATE sedes SET direccion = 'Av. Boyacá 138 - 70, Bogotá'
 WHERE nombre = 'Sede Norte';

UPDATE sedes SET direccion = 'Autopista Sur No 67 - 71, Bogotá'
 WHERE nombre = 'Sede Sur';

UPDATE sedes SET direccion = 'Campus virtual'
 WHERE nombre = 'Sede Virtual';

-- Verificacion: deberian quedar 4 sedes activas con estas direcciones
-- (si ya corriste limpiar_sedes_landing.sql antes, 'Calle 73 (Demo)' y
-- 'Calle 80' ya deberian aparecer con estado='I').
SELECT nombre, direccion, estado
  FROM sedes
 ORDER BY nombre;
