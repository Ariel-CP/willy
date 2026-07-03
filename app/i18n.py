"""
i18n.py — UI strings in Spanish and English.
Use get(key) to fetch the string for the active language.
Call set_language(lang) before building the UI.
"""

_STRINGS = {
    "es": {
        # General
        "app_title": "Willy — Asistente de Terminal con IA",
        "ready": "Listo",
        "settings_btn": "⚙ Configuración",
        # Chat panel
        "chat_header": " WILLY",
        "new_chat_btn": "Nuevo chat",
        "send_btn": "Enviar",
        "input_placeholder": "Escribí un mensaje…",
        "chat_cleared": "Chat limpiado. ¿En qué puedo ayudarte?",
        "welcome": (
            "¡Hola! Soy Willy, tu asistente con acceso al terminal.\n"
            "Podés pedirme cosas como:\n"
            "  • «listá los archivos de mi home»\n"
            "  • «mostrá el contenido de ~/.bashrc»\n"
            "  • «instalá htop»\n"
            "  • «creá un script que haga backup de /home»"
        ),
        "file_selected": "📄 Archivo seleccionado: {path}",
        "file_send_msg": "Mostrá el contenido de: {path}",
        "ai_thinking": "IA pensando…",
        "chat_mode_ask": "Preguntar",
        "chat_mode_plan": "Planificar",
        "chat_mode_agent": "Agente",
        # Terminal panel
        "terminal_header": " TERMINAL",
        "stop_btn": "■ Detener",
        "clear_btn": "Limpiar",
        "run_btn": "Ejecutar",
        "cmd_placeholder": "$ escribí un comando…",
        "interrupted": "\n[Interrumpido]\n",
        # File browser
        "files_header": " ARCHIVOS",
        "open_folder_btn": "Abrir",
        "new_project_btn": "Nuevo",
        "recent_projects_btn": "Recientes",
        "project_deps_btn": "Librerias",
        "workspace_opened": "Carpeta activa: {path}",
        "project_created": "Proyecto creado: {path}",
        "project_dialog_title": "Nuevo proyecto IoT",
        "project_name_label": "Nombre del proyecto:",
        "project_location_label": "Carpeta base:",
        "project_board_label": "Placa objetivo:",
        "project_template_label": "Plantilla inicial:",
        "project_downloads_label": "Preparar carpeta local para descargas del proyecto",
        "project_dialog_hint": "Se crearán src, lib, include, test, outputs y .willy.",
        "project_create_btn": "Crear proyecto",
        "project_context_loaded": "Contexto del proyecto cargado desde: {path}",
        "project_context_missing": "No se encontro .willy/AGENTS.md en el proyecto activo. Crealo para mejorar respuestas del chat.",
        "recent_projects_title": "Proyectos recientes",
        "recent_projects_empty": "Todavia no hay proyectos recientes.",
        "recent_projects_remove_btn": "Quitar",
        "recent_projects_favorite_btn": "Favorito",
        "recent_projects_unfavorite_btn": "Quitar fav",
        "project_deps_title": "Dependencias del proyecto",
        "project_deps_current": "Dependencias actuales declaradas en platformio.ini:",
        "project_deps_add": "Agregar dependencia lib_deps:",
        "project_deps_add_btn": "Agregar",
        "project_deps_install_btn": "Agregar e instalar",
        "project_deps_search": "Buscar libreria en PlatformIO:",
        "project_deps_search_btn": "Buscar",
        "project_deps_searching": "Buscando librerias...",
        "project_deps_search_empty": "No se encontraron librerias para esa busqueda.",
        "project_deps_downloads_btn": "Preparar carpeta de descargas",
        "project_deps_no_active": "No hay un proyecto PlatformIO activo.",
        "project_deps_added": "Dependencia agregada al proyecto: {spec}",
        "project_deps_exists": "La dependencia ya existe en este proyecto.",
        "project_deps_ready": "Carpeta de descargas lista: {path}",
        "project_deps_installing": "Instalando dependencias del proyecto...",
        "project_deps_installed": "Dependencias instaladas correctamente.",
        "project_deps_install_error": "No se pudieron instalar dependencias: {error}",
        # Confirm dialog
        "confirm_cancel": "Cancelar",
        "confirm_ok": "Confirmar",
        # Settings dialog
        "settings_title": "Configuración",
        "settings_api_key": "API Key de OpenAI:",
        "settings_api_source": "Fuente API Key:",
        "api_source_env": "Variable de entorno",
        "api_source_config": "Guardada en configuración",
        "settings_api_hint_env": "Se usará {env_name}. Estado: {status}",
        "settings_api_hint_env_note": "Si pegás una clave aquí, se guardará pero no se usará hasta cambiar la fuente a \"Guardada en configuración\".",
        "settings_api_hint_config": "API key local en config.json. Estado: {status}",
        "api_status_ok": "configurada",
        "api_status_missing": "faltante",
        "show_btn": "Mostrar",
        "hide_btn": "Ocultar",
        "settings_model": "Modelo:",
        "settings_initial_dir": "Directorio inicial:",
        "settings_theme": "Tema:",
        "settings_language": "Idioma:",
        "settings_confirm_readonly": "Confirmar comandos de lectura:",
        "settings_security_profile": "Perfil de seguridad:",
        "security_profile_lab_safe": "Laboratorio seguro (recomendado)",
        "security_profile_standard": "Estándar",
        "security_profile_permissive": "Permisivo",
        "settings_security_hint": (
            "Laboratorio seguro: solo comandos permitidos y bloqueo de patrones peligrosos.\n"
            "Estándar: permite más comandos, manteniendo bloqueo de alto riesgo.\n"
            "Permisivo: sin restricciones de perfil (solo para entornos controlados)."
        ),
        "settings_operation_role": "Rol operativo:",
        "operation_role_student": "Alumno",
        "operation_role_instructor": "Docente",
        "operation_role_admin": "Administrador",
        "settings_operation_role_hint": (
            "Alumno: restringe herramientas sensibles (no ejecuta comandos arbitrarios ni escritura de archivos).\n"
            "Docente: flujo completo de laboratorio y operaciones IoT guiadas.\n"
            "Administrador: acceso total para mantenimiento y soporte avanzado."
        ),
        "settings_audit_export": "Exportación de auditoría:",
        "settings_audit_hint": (
            "Genera reportes JSON sin secretos desde las sesiones locales para seguimiento de prácticas."
        ),
        "export_audit_7d_btn": "Exportar últimos 7 días",
        "export_audit_session_btn": "Exportar sesión actual",
        "audit_export_ok": "Auditoría exportada: {path}",
        "audit_export_error": "No se pudo exportar auditoría: {error}",
        "settings_locked_notice": "Política de estación activa: los siguientes ajustes están bloqueados: {keys}",
        "settings_cancel": "Cancelar",
        "settings_save": "Guardar",
        "save_btn": "Guardar",
        "browse_btn": "Examinar",
        "lang_es": "Español",
        "lang_en": "English",
        "restart_notice": "Reiniciá la app para aplicar el cambio de idioma.",
    },
    "en": {
        # General
        "app_title": "Willy — AI Terminal Assistant",
        "ready": "Ready",
        "settings_btn": "⚙ Settings",
        # Chat panel
        "chat_header": " WILLY",
        "new_chat_btn": "New chat",
        "send_btn": "Send",
        "input_placeholder": "Type a message…",
        "chat_cleared": "Chat cleared. How can I help?",
        "welcome": (
            "Hi! I'm Willy, your AI assistant with terminal access.\n"
            "You can ask me things like:\n"
            "  • «list the files in my home»\n"
            "  • «show me ~/.bashrc»\n"
            "  • «install htop»\n"
            "  • «create a backup script for /home»"
        ),
        "file_selected": "📄 Selected file: {path}",
        "file_send_msg": "Show me the contents of: {path}",
        "ai_thinking": "AI thinking…",
        "chat_mode_ask": "Ask",
        "chat_mode_plan": "Plan",
        "chat_mode_agent": "Agent",
        # Terminal panel
        "terminal_header": " TERMINAL",
        "stop_btn": "■ Stop",
        "clear_btn": "Clear",
        "run_btn": "Run",
        "cmd_placeholder": "$ type a command…",
        "interrupted": "\n[Interrupted]\n",
        # File browser
        "files_header": " FILES",
        "open_folder_btn": "Open",
        "new_project_btn": "New",
        "recent_projects_btn": "Recent",
        "project_deps_btn": "Libraries",
        "workspace_opened": "Active folder: {path}",
        "project_created": "Project created: {path}",
        "project_dialog_title": "New IoT project",
        "project_name_label": "Project name:",
        "project_location_label": "Base folder:",
        "project_board_label": "Target board:",
        "project_template_label": "Starter template:",
        "project_downloads_label": "Prepare a local project downloads folder",
        "project_dialog_hint": "This creates src, lib, include, test, outputs and .willy.",
        "project_create_btn": "Create project",
        "project_context_loaded": "Project context loaded from: {path}",
        "project_context_missing": "No .willy/AGENTS.md found in the active project. Create it to improve chat answers.",
        "recent_projects_title": "Recent projects",
        "recent_projects_empty": "There are no recent projects yet.",
        "recent_projects_remove_btn": "Remove",
        "recent_projects_favorite_btn": "Favorite",
        "recent_projects_unfavorite_btn": "Unfavorite",
        "project_deps_title": "Project dependencies",
        "project_deps_current": "Current dependencies declared in platformio.ini:",
        "project_deps_add": "Add lib_deps dependency:",
        "project_deps_add_btn": "Add",
        "project_deps_install_btn": "Add and install",
        "project_deps_search": "Search library in PlatformIO:",
        "project_deps_search_btn": "Search",
        "project_deps_searching": "Searching libraries...",
        "project_deps_search_empty": "No libraries found for that query.",
        "project_deps_downloads_btn": "Prepare downloads folder",
        "project_deps_no_active": "There is no active PlatformIO project.",
        "project_deps_added": "Dependency added to project: {spec}",
        "project_deps_exists": "This dependency already exists in the project.",
        "project_deps_ready": "Downloads folder ready: {path}",
        "project_deps_installing": "Installing project dependencies...",
        "project_deps_installed": "Dependencies installed successfully.",
        "project_deps_install_error": "Could not install dependencies: {error}",
        # Confirm dialog
        "confirm_cancel": "Cancel",
        "confirm_ok": "Confirm",
        # Settings dialog
        "settings_title": "Settings",
        "settings_api_key": "OpenAI API Key:",
        "settings_api_source": "API Key Source:",
        "api_source_env": "Environment variable",
        "api_source_config": "Saved in config",
        "settings_api_hint_env": "Will use {env_name}. Status: {status}",
        "settings_api_hint_env_note": "If you paste a key here, it will be saved but not used until you switch source to \"Saved in config\".",
        "settings_api_hint_config": "Local API key in config.json. Status: {status}",
        "api_status_ok": "configured",
        "api_status_missing": "missing",
        "show_btn": "Show",
        "hide_btn": "Hide",
        "settings_model": "Model:",
        "settings_initial_dir": "Initial Directory:",
        "settings_theme": "Theme:",
        "settings_language": "Language:",
        "settings_confirm_readonly": "Confirm read-only cmds:",
        "settings_security_profile": "Security profile:",
        "security_profile_lab_safe": "Lab safe (recommended)",
        "security_profile_standard": "Standard",
        "security_profile_permissive": "Permissive",
        "settings_security_hint": (
            "Lab safe: allowlisted commands plus dangerous-pattern blocking.\n"
            "Standard: broader commands while keeping high-risk block rules.\n"
            "Permissive: profile restrictions disabled (controlled environments only)."
        ),
        "settings_operation_role": "Operation role:",
        "operation_role_student": "Student",
        "operation_role_instructor": "Instructor",
        "operation_role_admin": "Administrator",
        "settings_operation_role_hint": (
            "Student: restricts sensitive tools (no arbitrary command execution or file writes).\n"
            "Instructor: full lab workflow and guided IoT operations.\n"
            "Administrator: full access for maintenance and advanced support."
        ),
        "settings_audit_export": "Audit export:",
        "settings_audit_hint": (
            "Generate redacted JSON reports from local sessions for lab traceability."
        ),
        "export_audit_7d_btn": "Export last 7 days",
        "export_audit_session_btn": "Export current session",
        "audit_export_ok": "Audit exported: {path}",
        "audit_export_error": "Audit export failed: {error}",
        "settings_locked_notice": "Station policy active: the following settings are locked: {keys}",
        "settings_cancel": "Cancel",
        "settings_save": "Save",
        "save_btn": "Save",
        "browse_btn": "Browse",
        "lang_es": "Español",
        "lang_en": "English",
        "restart_notice": "Restart the app to apply the language change.",
    },
}

_current_lang = "es"


def set_language(lang: str) -> None:
    global _current_lang
    if lang in _STRINGS:
        _current_lang = lang


def get(key: str, **kwargs) -> str:
    text = _STRINGS.get(_current_lang, _STRINGS["es"]).get(key, key)
    return text.format(**kwargs) if kwargs else text
