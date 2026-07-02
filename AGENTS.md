# AGENTS.md

Guía operativa de agentes para Willy en entornos de laboratorio (IoT/electrónica), con foco en seguridad, trazabilidad y operación multiplataforma.

## 1. Objetivo

Este documento define cómo debe comportarse Willy cuando ejecuta acciones asistidas por IA:

1. Qué puede hacer cada rol operativo.
2. Qué nivel de seguridad aplica según perfil.
3. Cómo forzar políticas por estación de trabajo.
4. Cómo auditar lo ocurrido en sesiones de práctica.

## 2. Modelo de operación de agentes

Willy utiliza un agente principal (`AIAgent`) con herramientas de:

1. Terminal y archivos.
2. Búsqueda/lectura web.
3. Flujos IoT (detección de placa, build, upload, escaneo I2C, esquemáticos).

El agente NO re-entrena modelos. Su "aprendizaje" es operativo:

1. Reutiliza contexto reciente (proyecto/puerto/env exitosos).
2. Registra sesiones y eventos para trazabilidad.
3. Aplica reglas de seguridad antes de ejecutar herramientas sensibles.

## 3. Perfiles de seguridad (`security_profile`)

Define cuán restrictiva es la política de comandos:

1. `lab_safe` (recomendado):
	Política estricta para laboratorios.
	Usa allowlist por sistema operativo y bloqueo de patrones peligrosos.

2. `standard`:
	Permite más comandos, manteniendo bloqueo de alto riesgo.

3. `permissive`:
	Sin restricciones de perfil (usar solo en entornos controlados).

## 4. Roles operativos (`operation_role`)

Define qué herramientas puede usar el agente:

1. `student` (Alumno):
	Lectura, navegación, diagnóstico y flujos IoT acotados.
	Bloquea herramientas sensibles como ejecución arbitraria de comandos y escritura de archivos.

2. `instructor` (Docente):
	Flujo completo de laboratorio guiado.

3. `admin` (Administrador):
	Acceso total para mantenimiento y soporte avanzado.

## 5. Confirmación de comandos

`require_command_confirmation` controla confirmaciones de comandos de terminal:

1. `true` (recomendado en laboratorio): siempre confirmar.
2. `false`: confirmar según reglas específicas adicionales.

## 6. Política forzada por estación (`station_policy.json`)

Para despliegues institucionales, cada estación puede forzar configuración local.

Ubicación:

1. Raíz del proyecto: `station_policy.json`.

Formato:

```json
{
  "enforced": {
	 "security_profile": "lab_safe",
	 "operation_role": "student",
	 "require_command_confirmation": true,
	 "api_key_source": "env"
  }
}
```

Comportamiento:

1. Las claves en `enforced` se aplican al iniciar.
2. Esas claves se bloquean visualmente en Configuración (UI).
3. La app registra qué claves fueron bloqueadas al iniciar.

## 7. Auditoría y trazabilidad

Willy registra sesiones en `sessions/` y permite exportar reportes de auditoría JSON.

Exportación desde Configuración:

1. Últimos 7 días.
2. Sesión actual.

Salida:

1. `outputs/audit/`.

El reporte incluye totales por sesión (eventos, mensajes, comandos, system_events, errores), sin secretos en texto plano.

## 8. Endurecimiento recomendado para laboratorios

Aplicar como baseline institucional:

1. `security_profile = lab_safe`
2. `operation_role = student` (o `instructor` en equipos docentes)
3. `require_command_confirmation = true`
4. `api_key_source = env`
5. No guardar claves API en `config.json`.

## 9. Matriz sugerida por tipo de equipo

1. Equipo Alumno:
	`security_profile=lab_safe`, `operation_role=student`

2. Equipo Docente:
	`security_profile=lab_safe` o `standard`, `operation_role=instructor`

3. Equipo Soporte/Mantenimiento:
	`security_profile=standard` o `permissive`, `operation_role=admin`

## 10. Procedimiento de validación post-despliegue

Después de instalar en una estación nueva:

1. Iniciar Willy y confirmar que carga sin errores.
2. Verificar en Configuración que los campos forzados aparecen bloqueados.
3. Ejecutar una acción permitida para el rol y validar éxito.
4. Intentar una acción restringida y validar bloqueo por política.
5. Exportar auditoría y confirmar que el reporte se genera en `outputs/audit/`.

## 11. Mantenimiento

1. Revisar periódicamente reglas de bloqueo y allowlists por SO.
2. Mantener la retención de sesiones según política institucional.
3. Auditar cambios en `station_policy.json` como artefacto crítico.
4. Re-ejecutar tests tras cada ajuste de seguridad/roles.

## 12. Nota final

La seguridad efectiva depende de combinar:

1. Rol operativo correcto.
2. Perfil de seguridad adecuado.
3. Política de estación forzada en equipos compartidos.
4. Auditoría continua.

Para laboratorios con alumnos, la combinación mínima recomendada es:

1. `operation_role=student`
2. `security_profile=lab_safe`
3. `require_command_confirmation=true`
