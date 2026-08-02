ACTIVE_HANDLER_VERSIONS = {
    'translation_ru': 1,
    'translation_cn': 1,
    'multiple_choice': 1,
    'writing': 1,
    'matching': 2,
}


def active_handler_version(kind: str) -> int:
    return ACTIVE_HANDLER_VERSIONS.get(kind, 1)
