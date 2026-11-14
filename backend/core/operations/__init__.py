"""
Operations (BUILD_ORDER 9.5; OPERATIONS.md §§ 9, 10): verified backups, restore, and the hold that
makes a restore of another environment's data safe. The deploy driver (scripts/deploy.py) calls
`manage.py backup` and `manage.py restore`; nothing here deploys.
"""
