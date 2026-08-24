"""Interactive settings menu -- run with: python -m cognitive_rpg.settings_wizard

Lets you pick which AI provider powers the Expert role (baseline "A") and the
Small role (baseline "B", and "F" = Small+Librarian), and enters API keys for
you. Everything is written to .env (see env_file.py) -- there is still no web UI,
this is a terminal menu, appropriate for a research CLI project (§71 of the
design review: RPG UI is explicitly last-priority, after the science).

API key input is NOT masked (plain input(), not getpass) -- masked input via
msvcrt on Windows console has caused pasted keys to come through duplicated/
garbled for at least one user, and this tool never leaves the local machine, so
visibility during entry is worth more here than screen-shoulder-surfing
protection. Whatever you paste is echoed back to you before it's saved so you
can catch a bad paste before it's written to .env.
"""

from . import config
from .env_file import read_env_file, update_env_file
from .providers import PROVIDER_ORDER, PROVIDERS

TEMPLATE_PATH = config.ROOT_DIR / ".env.example"


def _print_provider_menu():
    print("\nProvider disponibili:")
    for i, key in enumerate(PROVIDER_ORDER, start=1):
        p = PROVIDERS[key]
        print(f"  {i}) {p.label}")


def _choose_provider(role_label: str) -> str:
    _print_provider_menu()
    while True:
        raw = input(f"Scegli il provider per il ruolo {role_label} [1-{len(PROVIDER_ORDER)}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(PROVIDER_ORDER):
            return PROVIDER_ORDER[int(raw) - 1]
        print("Scelta non valida, riprova.")


def _choose_model(provider_key: str, existing_value: str) -> str | None:
    provider = PROVIDERS[provider_key]
    if provider.model_env is None:
        return None
    current = existing_value or provider.default_model
    raw = input(
        f"  Modello per {provider.label} [invio per tenere '{current}']: "
    ).strip()
    return raw or current


def _ensure_api_key(provider_key: str, existing: dict[str, str], updates: dict[str, str]):
    provider = PROVIDERS[provider_key]
    if provider.api_key_env is None:
        return
    keys_env = f"{provider.api_key_env}S"  # e.g. GEMINI_API_KEYS (comma-separated)
    current_raw = updates.get(keys_env) or existing.get(keys_env) or existing.get(provider.api_key_env) or ""
    current_keys = [k.strip() for k in current_raw.split(",") if k.strip()]

    if current_keys:
        print(f"  {len(current_keys)} key gia' presenti per {provider.label}.")
        if input("  Sostituirle con key nuove? [s/N]: ").strip().lower() != "s":
            print("  Le lascio invariate.")
            return
        current_keys = []

    print(f"  Incolla una o piu' API key per {provider.label} (invio vuoto per finire, cosi' puoi usarne piu' di una per aggirare i limiti del piano gratuito):")
    while True:
        key = input(f"  key #{len(current_keys) + 1} (o invio per finire): ").strip()
        if not key:
            break
        print(f"    ricevuta: {len(key)} caratteri, inizia con '{key[:7]}'. Controlla che sia giusta.")
        current_keys.append(key)

    if current_keys:
        updates[keys_env] = ",".join(current_keys)
        updates[provider.api_key_env] = current_keys[0]  # back-compat single-key var, kept in sync
    else:
        print(f"  Nessuna key inserita: {provider.label} restera' inutilizzabile finche' non la aggiungi a .env.")


def _ensure_vertex_config(provider_key: str, existing: dict[str, str], updates: dict[str, str]):
    """For providers authenticated via GCP project + service account (currently
    only gemini_vertex) instead of a plain API key. Nothing here is echoed back
    or sent anywhere -- it's written straight to .env on this machine, same as
    the wizard already does for API keys."""
    provider = PROVIDERS[provider_key]
    if provider.project_env is None:
        return

    print(f"\n{provider.label} richiede un progetto GCP con Vertex AI / Agent Platform abilitato.")

    current_project = existing.get(provider.project_env, "")
    project = input(f"  Project ID [{current_project or 'nessuno'}]: ").strip() or current_project
    if project:
        updates[provider.project_env] = project
    else:
        print(f"  Nessun project ID inserito: {provider.label} restera' inutilizzabile finche' non lo aggiungi a .env.")

    current_location = existing.get(provider.location_env, "") or "global"
    location = input(f"  Region [{current_location}]: ").strip() or current_location
    updates[provider.location_env] = location

    current_creds = existing.get(provider.credentials_env, "")
    prompt_default = "invariato" if current_creds else "nessuno"
    creds = input(
        f"  Path al file JSON della service account [{prompt_default}]: "
    ).strip() or current_creds
    if creds:
        updates[provider.credentials_env] = creds
    else:
        print(f"  Nessun file di credenziali: {provider.label} restera' inutilizzabile finche' non lo aggiungi a .env.")


def main():
    print("=== Cognitive RPG -- impostazioni provider ===")
    print("Ogni ruolo (Expert = baseline 'A', Small = baseline 'B' e 'F') puo' usare un provider diverso.")

    existing = read_env_file(config.ENV_PATH)
    updates: dict[str, str] = {}

    expert_provider = _choose_provider("EXPERT (baseline 'A')")
    small_provider = _choose_provider("SMALL (baseline 'B' / 'F' = Small+Librarian)")

    updates["EXPERT_PROVIDER"] = expert_provider
    updates["SMALL_PROVIDER"] = small_provider

    shared_provider = expert_provider == small_provider

    for role, provider_key in (("expert", expert_provider), ("small", small_provider)):
        if provider_key == "mock":
            continue
        provider = PROVIDERS[provider_key]
        _ensure_api_key(provider_key, existing, updates)
        _ensure_vertex_config(provider_key, existing, updates)
        # When both roles use the same provider, a single shared *_MODEL var can't
        # hold two different models -- ask per role instead (EXPERT_GEMINI_MODEL /
        # SMALL_GEMINI_MODEL), which adapters/factory.py checks before the shared var.
        model_env = f"{role.upper()}_{provider.model_env}" if shared_provider else provider.model_env
        model = _choose_model(provider_key, existing.get(model_env, ""))
        if model is not None:
            updates[model_env] = model

    update_env_file(config.ENV_PATH, updates, template=TEMPLATE_PATH)

    print(f"\nSalvato in {config.ENV_PATH}")
    print(f"EXPERT_PROVIDER={expert_provider}   SMALL_PROVIDER={small_provider}")
    for provider_key in {expert_provider, small_provider}:
        provider = PROVIDERS[provider_key]
        if provider.pricing_input_env and provider.pricing_output_env:
            print(
                f"Nota: il costo per {provider.label} viene tracciato come $0 finche' non compili "
                f"{provider.pricing_input_env} / {provider.pricing_output_env} in .env "
                "(nessuno skill in questa sessione conferma i prezzi attuali)."
            )


if __name__ == "__main__":
    main()
