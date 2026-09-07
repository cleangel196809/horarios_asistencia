-- ============================================================================
-- Limpieza de datos en 'sedes' para que el footer del landing de SIIHAPI
-- muestre solo sedes reales (Fase 2 - 2026-09-03).
--
-- No borra nada: solo desactiva (estado='I') las filas que no deben salir
-- en el listado publico. El landing filtra por estado='A', asi que basta
-- con este cambio para que dejen de aparecer.
-- ============================================================================

-- 1) 'Sede Calle 73 (Demo)' es un duplicado de 'Sede Calle 73' (la real).
UPDATE sedes
   SET estado = 'I'
 WHERE nombre = 'Sede Calle 73 (Demo)';

-- 2) 'Sede Calle 80' no tiene direccion registrada todavia (NULL).
UPDATE sedes
   SET estado = 'I'
 WHERE nombre = 'Sede Calle 80';

-- Verificacion: deberian quedar 4 sedes activas (Calle 73, Norte, Sur, Virtual).
SELECT nombre, direccion, estado
  FROM sedes
 ORDER BY nombre;
