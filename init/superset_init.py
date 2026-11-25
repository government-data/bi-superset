"""superset-init: run once at install and at every update, before the web
service starts (core decision 0089, point 6). Migrates Superset's metadata
database, runs `superset init`, makes the module's roles and superset-init's
own user. Every step can run twice. The shipped dashboards' import comes
with step 9. Prints names only, never a secret.

    python superset_init.py
"""

import os
import subprocess

# Role -> the Superset role it starts from. QD Guest gets no datasource
# permission: a guest reaches a dataset only through a chart of the
# dashboard its token names (decision 0089, V3).
ROLES = {"QD Viewer": "Gamma", "QD Author": "Alpha", "QD Guest": "Gamma"}
INIT_USER = "bi-superset-init"


def roles(sm):
    for role, base in ROLES.items():
        sm.copy_role(base, role, merge=False)
    every = sm.find_permission_view_menu("all_datasource_access", "all_datasource_access")
    for role in ("QD Viewer", "QD Author"):
        r = sm.find_role(role)
        add = [every] + (list(sm.find_role("sql_lab").permissions) if role == "QD Author" else [])
        for pvm in add:
            if pvm and pvm not in r.permissions:
                r.permissions.append(pvm)


def init_user(sm):
    """The importers make the current user the owner of what they import:
    superset-init's own user, an Admin that cannot sign in."""
    user = sm.find_user(username=INIT_USER)
    if user is None:
        user = sm.add_user(INIT_USER, "superset-init", "bi-superset", "bi-superset-init@invalid.example",
                           [sm.find_role("Admin")], password=os.urandom(24).hex())
    user.active = False


def main():
    subprocess.run(["superset", "db", "upgrade"], check=True)
    subprocess.run(["superset", "init"], check=True)
    from superset.app import create_app

    with create_app().app_context():
        from superset import db, security_manager as sm

        roles(sm)
        init_user(sm)
        db.session.commit()
        print("roles:", ", ".join(sorted(r.name for r in sm.get_all_roles())))


if __name__ == "__main__":
    main()
