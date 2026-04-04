MODULE_PATH_MAP = {
    '/maths/': 'maths',
    '/coding/': 'coding',
    '/music/': 'music',
    '/science/': 'science',
    '/billing': 'billing',
    '/attendance': 'attendance',
    '/progress': 'progress',
    '/audit/': 'audit',
    '/ai-import/': 'ai_import',
    '/invoic': 'invoicing',
    '/salar': 'salaries',
    '/school-hierarchy': 'hierarchy',
    '/help/': 'help',
}


def help_context(request):
    if not request.user.is_authenticated:
        return {}

    path = request.path
    help_module = 'classroom'
    for prefix, module in MODULE_PATH_MAP.items():
        if path.startswith(prefix):
            help_module = module
            break

    return {'help_module': help_module}
