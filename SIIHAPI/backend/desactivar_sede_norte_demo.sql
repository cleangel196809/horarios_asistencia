-- ============================================================================
-- Desactiva 'Sede Norte (Demo)' (igual que se hizo con 'Sede Calle 73
-- (Demo)'): no se borra la fila, solo se le pone estado='I' para que deje
-- de aparecer en el landing (que filtra por estado='A').
-- ============================================================================

-- 1) Verifica primero que el nombre coincide antes de tocar nada:
SELECT id, nombre, direccion, estado
  FROM sedes
 WHERE nombre ILIKE '%norte%demo%' OR nombre ILIKE '%demo%norte%';

-- 2) Si la fila de arriba es la correcta, desactívala:
UPDATE sedes
   SET estado = 'I'
 WHERE nombre ILIKE '%norte%demo%' OR nombre ILIKE '%demo%norte%';

-- 3) Verificación final: sedes activas que quedan.
SELECT nombre, direccion, estado
  FROM sedes
 ORDER BY nombre;
