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
        # Terminal panel
        "terminal_header": " TERMINAL",
        "stop_btn": "■ Detener",
        "clear_btn": "Limpiar",
        "run_btn": "Ejecutar",
        "cmd_placeholder": "$ escribí un comando…",
        "interrupted": "\n[Interrumpido]\n",
        # File browser
        "files_header": " ARCHIVOS",
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
        # Terminal panel
        "terminal_header": " TERMINAL",
        "stop_btn": "■ Stop",
        "clear_btn": "Clear",
        "run_btn": "Run",
        "cmd_placeholder": "$ type a command…",
        "interrupted": "\n[Interrupted]\n",
        # File browser
        "files_header": " FILES",
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
